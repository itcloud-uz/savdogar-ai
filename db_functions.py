# db_functions.py

import mysql.connector
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode
import io
import base64
import jwt

def connect_db():
    try:
        return mysql.connector.connect(
            host="localhost", user="root", password="Clone1997#", database="Vican"
        )
    except mysql.connector.Error as e:
        print(f"❌ DB Connection Error: {e}")
        return None

def generate_user_login_token(user_id, secret_key):
    try:
        payload = {
            'exp': datetime.utcnow() + timedelta(days=365 * 5),
            'iat': datetime.utcnow(),
            'sub': user_id
        }
        return jwt.encode(payload, secret_key, algorithm='HS256')
    except Exception as e:
        print(f"Error generating token: {e}")
        return None

def _change_stock_and_log(cursor, product_id, quantity_change, movement_type, user_id, notes=""):
    update_query = "UPDATE products SET quantity = quantity + %s WHERE id = %s AND quantity + %s >= 0"
    cursor.execute(update_query, (quantity_change, product_id, quantity_change))
    if cursor.rowcount == 0:
        raise ValueError("Mahsulot qoldig'i yetarli emas yoki mahsulot topilmadi.")
    log_query = "INSERT INTO inventory_movements (product_id, quantity_change, movement_type, user_id, notes) VALUES (%s, %s, %s, %s, %s)"
    cursor.execute(log_query, (product_id, quantity_change, movement_type, user_id, notes))

def warehouse_movement(product_id, quantity, movement_type, user_id, notes=""):
    conn = connect_db()
    if not conn: return False, "Baza bilan ulanishda xato."
    try:
        cursor = conn.cursor()
        _change_stock_and_log(cursor, product_id, quantity, movement_type, user_id, notes)
        conn.commit()
        return True, "Operatsiya muvaffaqiyatli bajarildi."
    except (mysql.connector.Error, ValueError) as e:
        conn.rollback()
        return False, str(e)
    finally:
        if conn: conn.close()

def process_sale(product_id, quantity, user_id, customer_id=None):
    conn = connect_db()
    if not conn: return False, "Baza bilan ulanishda xato.", None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM products WHERE id = %s AND is_active = TRUE FOR UPDATE", (product_id,))
        product = cursor.fetchone()
        
        if not product: return False, f"Mahsulot (ID: {product_id}) topilmadi yoki faol emas.", None
        if product['quantity'] < quantity: return False, f"Omborda yetarli mahsulot yo'q. Qoldiq: {product['quantity']} dona.", None
        
        profit = (product['price'] - product['cost_price']) * quantity
        
        sql_sale = "INSERT INTO sales (product_id, quantity, user_id, customer_id, profit) VALUES (%s, %s, %s, %s, %s)"
        cursor.execute(sql_sale, (product_id, quantity, user_id, customer_id, profit))
        sale_id = cursor.lastrowid

        _change_stock_and_log(cursor, product_id, -abs(quantity), 'sotuv', user_id, f"Sotuv #{sale_id}")
        
        total_price = product['price'] * quantity
        
        if customer_id:
            bonus_points = int(total_price / 10000)
            if bonus_points > 0:
                cursor.execute("UPDATE customers SET bonus_points = bonus_points + %s WHERE id = %s", (bonus_points, customer_id))

        conn.commit()
        return True, f"Sotuv muvaffaqiyatli! Umumiy narx: {total_price:.2f}", sale_id
    except (mysql.connector.Error, ValueError) as e:
        conn.rollback()
        return False, str(e), None
    finally:
        if conn: conn.close()
        
def get_inventory_history():
    conn = connect_db()
    if not conn: return []
    try:
        cursor = conn.cursor(dictionary=True)
        query = "SELECT im.id, im.movement_date, p.name as product_name, im.quantity_change, im.movement_type, u.username as user_name FROM inventory_movements im JOIN products p ON im.product_id = p.id LEFT JOIN users u ON im.user_id = u.id ORDER BY im.movement_date DESC"
        cursor.execute(query)
        return cursor.fetchall()
    finally:
        if conn: conn.close()

def delete_inventory_movement(movement_id):
    conn = connect_db()
    if not conn: return False
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM inventory_movements WHERE id = %s", (movement_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        if conn: conn.close()

def view_customers(search_term=""):
    conn = connect_db()
    if not conn: return []
    try:
        cursor = conn.cursor(dictionary=True)
        query = "SELECT * FROM customers"
        params = []
        if search_term:
            query += " WHERE name LIKE %s OR phone_number LIKE %s"
            params.extend([f"%{search_term}%", f"%{search_term}%"])
        query += " ORDER BY id DESC"
        cursor.execute(query, params)
        return cursor.fetchall()
    finally:
        if conn: conn.close()

def add_customer(name, phone_number):
    conn = connect_db()
    if not conn: return False
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO customers (name, phone_number) VALUES (%s, %s)", (name, phone_number))
        conn.commit()
        return True
    except mysql.connector.IntegrityError:
        return False
    finally:
        if conn: conn.close()

def get_customer_by_id(customer_id):
    conn = connect_db()
    if not conn: return None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM customers WHERE id = %s", (customer_id,))
        return cursor.fetchone()
    finally:
        if conn: conn.close()

def update_customer(customer_id, name, phone_number):
    conn = connect_db()
    if not conn: return False
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE customers SET name = %s, phone_number = %s WHERE id = %s", (name, phone_number, customer_id))
        conn.commit()
        return True
    except mysql.connector.IntegrityError:
        return False
    finally:
        if conn: conn.close()

def add_expense(description, amount, expense_date, user_id):
    conn = connect_db()
    if not conn: return False
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO expenses (description, amount, expense_date, user_id) VALUES (%s, %s, %s, %s)", (description, amount, expense_date, user_id))
        conn.commit()
        return True
    finally:
        if conn: conn.close()

def get_expenses_by_date(start_date, end_date):
    conn = connect_db()
    if not conn: return [], 0
    try:
        cursor = conn.cursor(dictionary=True)
        query = "SELECT e.*, u.username FROM expenses e JOIN users u ON e.user_id = u.id WHERE e.expense_date BETWEEN %s AND %s ORDER BY e.expense_date DESC"
        cursor.execute(query, (start_date, end_date))
        expenses = cursor.fetchall()
        total_expenses = sum(exp['amount'] for exp in expenses)
        return expenses, total_expenses
    finally:
        if conn: conn.close()

def get_analytics_data(days=30):
    conn = connect_db()
    if not conn: return {}
    try:
        cursor = conn.cursor(dictionary=True)
        date_limit = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        sales_query = "SELECT DATE(s.sale_date) as date, SUM(s.quantity * p.price) as total_sales, SUM(s.profit) as total_profit FROM sales s JOIN products p ON s.product_id = p.id WHERE s.sale_date >= %s GROUP BY DATE(s.sale_date) ORDER BY date"
        cursor.execute(sales_query, (date_limit,))
        sales_data = cursor.fetchall()

        expenses_query = "SELECT expense_date as date, SUM(amount) as total_expenses FROM expenses WHERE expense_date >= %s GROUP BY expense_date ORDER BY date"
        cursor.execute(expenses_query, (date_limit,))
        expenses_data = cursor.fetchall()
        
        top_products_query = "SELECT p.name, SUM(s.quantity) as total_sold FROM sales s JOIN products p ON s.product_id = p.id WHERE s.sale_date >= %s GROUP BY p.name ORDER BY total_sold DESC LIMIT 5"
        cursor.execute(top_products_query, (date_limit,))
        top_products = cursor.fetchall()

        cursor.execute("SELECT SUM(s.quantity * p.price) FROM sales s JOIN products p ON s.product_id = p.id WHERE s.sale_date >= %s", (date_limit,))
        result_revenue = cursor.fetchone()
        total_revenue = result_revenue['SUM(s.quantity * p.price)'] if result_revenue and result_revenue['SUM(s.quantity * p.price)'] is not None else 0

        cursor.execute("SELECT SUM(profit) FROM sales WHERE sale_date >= %s", (date_limit,))
        result_profit = cursor.fetchone()
        total_profit = result_profit['SUM(profit)'] if result_profit and result_profit['SUM(profit)'] is not None else 0

        cursor.execute("SELECT SUM(amount) FROM expenses WHERE expense_date >= %s", (date_limit,))
        result_expenses = cursor.fetchone()
        total_expenses = result_expenses['SUM(amount)'] if result_expenses and result_expenses['SUM(amount)'] is not None else 0

        chart_data = {}
        for day in range(days, -1, -1):
            date_str = (datetime.now() - timedelta(days=day)).strftime('%Y-%m-%d')
            chart_data[date_str] = {'sales': 0, 'expenses': 0, 'profit': 0}

        for row in sales_data:
            date_str = row['date'].strftime('%Y-%m-%d')
            if date_str in chart_data:
                chart_data[date_str]['sales'] = float(row.get('total_sales', 0))
                chart_data[date_str]['profit'] = float(row.get('total_profit', 0))
        
        for row in expenses_data:
            date_str = row['date'].strftime('%Y-%m-%d')
            if date_str in chart_data:
                chart_data[date_str]['expenses'] = float(row.get('total_expenses', 0))
        
        return {
            "chart_data": chart_data,
            "top_products": top_products,
            "total_revenue": total_revenue,
            "total_profit": total_profit,
            "total_expenses": total_expenses
        }
    finally:
        if conn: conn.close()

def get_sale_details_for_receipt(sale_id):
    conn = connect_db()
    if not conn: return None
    try:
        cursor = conn.cursor(dictionary=True)
        query = "SELECT s.id, s.sale_date, p.name as product_name, s.quantity, p.price, (s.quantity * p.price) as total_amount, u.username as cashier_name, c.name as customer_name FROM sales s JOIN products p ON s.product_id = p.id JOIN users u ON s.user_id = u.id LEFT JOIN customers c ON s.customer_id = c.id WHERE s.id = %s"
        cursor.execute(query, (sale_id,))
        return cursor.fetchone()
    finally:
        if conn: conn.close()

def check_user_credentials(username, password):
    conn = connect_db()
    if not conn: return None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username = %s AND is_active = TRUE", (username,))
        user = cursor.fetchone()
        if user and check_password_hash(user.get('password', ''), password):
            return user
        return None
    finally:
        if conn: conn.close()

def view_users(search_term=""):
    conn = connect_db()
    if not conn: return []
    try:
        cursor = conn.cursor(dictionary=True)
        query = "SELECT id, username, role, is_active FROM users"
        params = []
        if search_term:
            query += " WHERE username LIKE %s"
            params.append(f"%{search_term}%")
        query += " ORDER BY id DESC"
        cursor.execute(query, params)
        return cursor.fetchall()
    finally:
        if conn: conn.close()

def get_user_by_id(user_id):
    conn = connect_db()
    if not conn: return None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return cursor.fetchone()
    finally:
        if conn: conn.close()

def add_user(username, password, role):
    conn = connect_db()
    if not conn: return False
    try:
        cursor = conn.cursor()
        hashed_password = generate_password_hash(password)
        sql = "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)"
        cursor.execute(sql, (username, hashed_password, role))
        conn.commit()
        return True
    finally:
        if conn: conn.close()

def update_user(user_id, username, role, is_active, password=None):
    conn = connect_db()
    if not conn: return False
    try:
        cursor = conn.cursor()
        if password:
            hashed_password = generate_password_hash(password)
            sql = "UPDATE users SET username = %s, role = %s, is_active = %s, password = %s WHERE id = %s"
            cursor.execute(sql, (username, role, is_active, hashed_password, user_id))
        else:
            sql = "UPDATE users SET username = %s, role = %s, is_active = %s WHERE id = %s"
            cursor.execute(sql, (username, role, is_active, user_id))
        conn.commit()
        return True
    finally:
        if conn: conn.close()

def hard_delete_user(user_id):
    conn = connect_db()
    if not conn: return False
    try:
        cursor = conn.cursor()
        # Bog'liq yozuvlar DB'da `ON DELETE SET NULL` orqali to'g'rilanadi
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        if conn: conn.close()

def view_products(search_term=""):
    conn = connect_db()
    if not conn: return []
    try:
        cursor = conn.cursor(dictionary=True)
        query = "SELECT * FROM products"
        params = []
        if search_term:
            query += " WHERE name LIKE %s"
            params.append(f"%{search_term}%")
        query += " ORDER BY id DESC"
        cursor.execute(query, params)
        return cursor.fetchall()
    finally:
        if conn: conn.close()

def get_product_by_id(product_id):
    conn = connect_db()
    if not conn: return None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        return cursor.fetchone()
    finally:
        if conn: conn.close()

def add_product(name, cost_price, price, quantity):
    conn = connect_db()
    if not conn: return False
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO products (name, cost_price, price, quantity) VALUES (%s, %s, %s, %s)", (name, cost_price, price, quantity))
        conn.commit()
        return True
    finally:
        if conn: conn.close()

def update_product(product_id, name, cost_price, price, quantity, is_active):
    conn = connect_db()
    if not conn: return False
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE products SET name = %s, cost_price = %s, price = %s, quantity = %s, is_active = %s WHERE id = %s", (name, cost_price, price, quantity, is_active, product_id))
        conn.commit()
        return True
    finally:
        if conn: conn.close()

def delete_product(product_id):
    conn = connect_db()
    if not conn: return False
    try:
        cursor = conn.cursor()
        # Haqiqiy o'chirish
        cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
        conn.commit()
        return cursor.rowcount > 0
    except mysql.connector.Error as e:
        print(f"Error deleting product: {e}")
        return False
    finally:
        if conn: conn.close()

def get_low_stock_products(threshold=10):
    conn = connect_db()
    if not conn: return []
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, quantity FROM products WHERE quantity < %s AND is_active = TRUE", (threshold,))
        return cursor.fetchall()
    finally:
        if conn: conn.close()

def get_sales_report(start_date, end_date):
    conn = connect_db()
    if not conn: return [], 0, 0
    try:
        cursor = conn.cursor(dictionary=True)
        query = "SELECT s.id as sale_id, s.sale_date, p.name, s.quantity, p.price, s.profit, (s.quantity * p.price) AS total_price FROM sales s JOIN products p ON s.product_id = p.id WHERE s.sale_date BETWEEN %s AND %s ORDER BY s.sale_date DESC"
        cursor.execute(query, (start_date, end_date))
        sales_data = cursor.fetchall()
        total_revenue = sum(s['total_price'] for s in sales_data)
        total_profit = sum(s['profit'] for s in sales_data)
        return sales_data, total_revenue, total_profit
    finally:
        if conn: conn.close()

def delete_sale_record(sale_id):
    conn = connect_db()
    if not conn: return False
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sales WHERE id = %s", (sale_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        if conn: conn.close()

def generate_qr_code_base64(data):
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def get_most_sold_products(days=30, limit=5):
    conn = connect_db()
    if not conn: return []
    try:
        cursor = conn.cursor(dictionary=True)
        date_limit = datetime.now() - timedelta(days=days)
        query = "SELECT p.id, p.name, p.quantity, SUM(s.quantity) as total_sold FROM sales s JOIN products p ON s.product_id = p.id WHERE s.sale_date >= %s AND p.is_active = TRUE GROUP BY p.id, p.name, p.quantity ORDER BY total_sold DESC LIMIT %s"
        cursor.execute(query, (date_limit, limit))
        return cursor.fetchall()
    finally:
        if conn: conn.close()

def generate_automated_order_list():
    recommendations = {}
    low_stock_items = get_low_stock_products(threshold=10)
    for item in low_stock_items:
        if item['id'] not in recommendations:
            recommendations[item['id']] = {'id': item['id'], 'name': item['name'], 'quantity': item['quantity'], 'reason': 'Qoldiq kam', 'recommended_order': 20 - item['quantity']}
    top_sellers = get_most_sold_products(days=30, limit=10)
    for item in top_sellers:
        if item['id'] not in recommendations and item['quantity'] < 25:
            recommendations[item['id']] = {'id': item['id'], 'name': item['name'], 'quantity': item['quantity'], 'reason': 'Ko\'p sotilgan', 'recommended_order': 30 - item['quantity']}
    return list(recommendations.values())

def get_cashier_performance_stats(days=30):
    conn = connect_db()
    if not conn: return []
    try:
        cursor = conn.cursor(dictionary=True)
        date_limit = datetime.now() - timedelta(days=days)
        query = "SELECT u.id as user_id, u.username, COUNT(s.id) as transaction_count, SUM(s.quantity) as total_items_sold, SUM(s.quantity * p.price) as total_sales_amount FROM sales s JOIN users u ON s.user_id = u.id JOIN products p ON s.product_id = p.id WHERE s.sale_date >= %s AND u.role = 'cashier' GROUP BY u.id, u.username ORDER BY total_sales_amount DESC"
        cursor.execute(query, (date_limit,))
        return cursor.fetchall()
    finally:
        if conn: conn.close()
