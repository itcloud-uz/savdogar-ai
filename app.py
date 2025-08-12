# app.py

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from functools import wraps
from datetime import datetime
import db_functions as db
import json
import jwt

app = Flask(__name__)
app.secret_key = 'bu_juda_maxfiy_kalit_!@#$%'

# --- Maxsus Jinja2 filtri pul formatlash uchun ---
def format_currency(value):
    if value is None: return "0.00"
    try:
        return "{:,.2f}".format(float(value)).replace(',', ' ')
    except (ValueError, TypeError):
        return value

app.jinja_env.filters['format_currency'] = format_currency

# --- Dekoratorlar (Foydalanuvchi huquqlarini tekshirish uchun) ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(role_name):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                return redirect(url_for('login'))
            
            user_role = session['user']['role']
            # Admin hamma sahifaga kira oladi
            if user_role == 'admin':
                return f(*args, **kwargs)
            
            allowed_roles = role_name if isinstance(role_name, list) else [role_name]
            if user_role not in allowed_roles:
                flash("Bu sahifaga kirish uchun sizda ruxsat yo'q.", "warning")
                return redirect(url_for('home'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# --- Asosiy va Autentifikatsiya ---
@app.route('/')
@login_required
def home():
    role = session['user']['role']
    if role == 'admin': return redirect(url_for('admin_dashboard'))
    if role == 'cashier': return redirect(url_for('cashier_dashboard'))
    if role == 'warehouse': return redirect(url_for('warehouse_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = db.check_user_credentials(request.form['username'], request.form['password'])
        if user:
            session['user'] = user
            return redirect(url_for('home'))
        else:
            flash('Login yoki parol noto\'g\'ri!', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('Tizimdan muvaffaqiyatli chiqdingiz.', 'info')
    return redirect(url_for('login'))

# --- QR-kod orqali kirish ---
@app.route('/qr-login', methods=['POST'])
def qr_login():
    token = request.form.get('token')
    if not token:
        return jsonify({'status': 'error', 'message': 'Token topilmadi.'})
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        user_id = payload['sub']
        user = db.get_user_by_id(user_id)
        if user and user['is_active']:
            session['user'] = user
            return jsonify({'status': 'success', 'redirect_url': url_for('home')})
        else:
            return jsonify({'status': 'error', 'message': 'Foydalanuvchi topilmadi yoki faol emas.'})
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return jsonify({'status': 'error', 'message': 'Token yaroqsiz.'})

# --- Admin Paneli va Analitika ---
@app.route('/admin')
@login_required
@role_required('admin')
def admin_dashboard():
    analytics_data = db.get_analytics_data(days=30)
    return render_template('admin_dashboard.html', **analytics_data)

# --- Mijozlarni Boshqarish ---
@app.route('/customers')
@login_required
@role_required('admin')
def customers_page():
    search_term = request.args.get('q', '')
    customers = db.view_customers(search_term)
    return render_template('customers.html', customers=customers, search_term=search_term)

@app.route('/customers/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def add_customer_page():
    if request.method == 'POST':
        if db.add_customer(request.form['name'], request.form['phone_number']):
            flash("Mijoz muvaffaqiyatli qo'shildi!", 'success')
        else:
            flash("Bu telefon raqami allaqachon mavjud.", 'danger')
        return redirect(url_for('customers_page'))
    return render_template('customer_form.html', title="Yangi Mijoz Qo'shish")

@app.route('/customers/edit/<int:customer_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_customer_page(customer_id):
    if request.method == 'POST':
        if db.update_customer(customer_id, request.form['name'], request.form['phone_number']):
            flash("Mijoz ma'lumotlari yangilandi!", 'success')
        else:
            flash("Mijozni yangilashda xatolik yoki bu raqam band.", 'danger')
        return redirect(url_for('customers_page'))
    
    customer = db.get_customer_by_id(customer_id)
    return render_template('customer_form.html', title="Mijozni Tahrirlash", customer=customer)

# --- Xarajatlarni Boshqarish ---
@app.route('/expenses', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def expenses_page():
    today = datetime.today()
    start_date = today.replace(day=1).strftime('%Y-%m-%d')
    end_date = today.strftime('%Y-%m-%d')
    
    if request.method == 'POST':
        if 'description' in request.form:
            db.add_expense(request.form['description'], request.form['amount'], request.form['expense_date'], session['user']['id'])
            flash("Xarajat muvaffaqiyatli qo'shildi!", "success")
            return redirect(url_for('expenses_page'))
        else:
            start_date = request.form.get('start_date', start_date)
            end_date = request.form.get('end_date', end_date)

    expenses, total_expenses = db.get_expenses_by_date(start_date, end_date)
    return render_template('expenses.html', 
                           expenses=expenses, 
                           total_expenses=total_expenses, 
                           start_date=start_date, 
                           end_date=end_date,
                           today_date=today.strftime('%Y-%m-%d'))

# --- Kassir Paneli ---
@app.route('/cashier')
@login_required
@role_required(['cashier', 'admin'])
def cashier_dashboard():
    return render_template('cashier_dashboard.html', 
                           products=db.view_products(),
                           customers=db.view_customers())

@app.route('/cashier/sell', methods=['POST'])
@login_required
@role_required(['cashier', 'admin'])
def sell_product():
    try:
        product_id = int(request.form['product_id'])
        quantity = int(request.form['quantity'])
        customer_id = request.form.get('customer_id')
        user_id = session['user']['id']
        
        success, message, sale_id = db.process_sale(product_id, quantity, user_id, customer_id if customer_id else None)
        
        if success:
            receipt_url = url_for('receipt_page', sale_id=sale_id)
            return jsonify({'status': 'success', 'message': message, 'receipt_url': receipt_url})
        else:
            return jsonify({'status': 'error', 'message': message})

    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': "Noto'g'ri ma'lumot kiritildi."})

# --- Chek Chop Etish ---
@app.route('/receipt/<int:sale_id>')
@login_required
def receipt_page(sale_id):
    sale_details = db.get_sale_details_for_receipt(sale_id)
    if not sale_details:
        return "Chek topilmadi", 404
    return render_template('receipt.html', sale=sale_details)

# --- Mahsulotlar, Xodimlar, Hisobotlar va boshqa admin funksiyalari ---
@app.route('/products')
@login_required
@role_required('admin')
def products_page():
    search_term = request.args.get('q', '')
    products = db.view_products(search_term)
    return render_template('products.html', products=products, search_term=search_term)

@app.route('/products/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def add_product_page():
    if request.method == 'POST':
        if db.add_product(request.form['name'], request.form['cost_price'], request.form['price'], request.form['quantity']):
            flash(f"'{request.form['name']}' mahsuloti qo'shildi!", 'success')
        else:
            flash("Mahsulot qo'shishda xatolik.", 'danger')
        return redirect(url_for('products_page'))
    return render_template('product_form.html', title="Yangi Mahsulot Qo'shish")

@app.route('/products/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_product_page(product_id):
    if request.method == 'POST':
        is_active = 'is_active' in request.form
        if db.update_product(product_id, request.form['name'], request.form['cost_price'], request.form['price'], request.form['quantity'], is_active):
            flash(f"Mahsulot (ID: {product_id}) yangilandi!", 'success')
        else:
            flash("Mahsulotni yangilashda xatolik.", 'danger')
        return redirect(url_for('products_page'))
    
    product = db.get_product_by_id(product_id)
    return render_template('product_form.html', title="Mahsulotni Tahrirlash", product=product)

@app.route('/products/delete/<int:product_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_product_route(product_id):
    if db.delete_product(product_id):
        flash(f"Mahsulot (ID: {product_id}) butunlay o'chirildi.", "success")
    else:
        flash(f"Mahsulotni o'chirishda xatolik.", "danger")
    return redirect(url_for('products_page'))

@app.route('/products/qr/<int:product_id>')
@login_required
@role_required('admin')
def qr_code_page(product_id):
    product = db.get_product_by_id(product_id)
    product_qr_data = f"ID: {product['id']}, Nomi: {product['name']}, Narx: {product['price']}"
    qr_code_b64 = db.generate_qr_code_base64(product_qr_data)
    return render_template('qr_code_display.html', product=product, qr_code=qr_code_b64)

@app.route('/users')
@login_required
@role_required('admin')
def users_page():
    search_term = request.args.get('q', '')
    users = db.view_users(search_term)
    return render_template('users.html', users=users, search_term=search_term)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def add_user_page():
    if request.method == 'POST':
        if db.add_user(request.form['username'], request.form['password'], request.form['role']):
            flash(f"'{request.form['username']}' foydalanuvchisi qo'shildi!", 'success')
        else:
            flash("Foydalanuvchi qo'shishda xatolik.", 'danger')
        return redirect(url_for('users_page'))
    return render_template('user_form.html', title="Yangi Xodim Qo'shish")

@app.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_user_page(user_id):
    if request.method == 'POST':
        password = request.form.get('password')
        is_active = 'is_active' in request.form
        if db.update_user(user_id, request.form['username'], request.form['role'], is_active, password if password else None):
            flash(f"Xodim (ID: {user_id}) yangilandi!", 'success')
        else:
            flash("Xodimni yangilashda xatolik.", 'danger')
        return redirect(url_for('users_page'))
    
    user = db.get_user_by_id(user_id)
    return render_template('user_form.html', title="Xodimni Tahrirlash", user=user)

@app.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_user_route(user_id):
    if db.hard_delete_user(user_id):
        flash(f"Xodim (ID: {user_id}) butunlay o'chirildi.", "success")
    else:
        flash(f"Xodimni o'chirishda xatolik.", "danger")
    return redirect(url_for('users_page'))

@app.route('/users/qr/<int:user_id>')
@login_required
@role_required('admin')
def user_qr_code_page(user_id):
    user = db.get_user_by_id(user_id)
    if not user:
        flash("Foydalanuvchi topilmadi!", "warning")
        return redirect(url_for('users_page'))
    
    login_token = db.generate_user_login_token(user['id'], app.secret_key)
    qr_code_b64 = db.generate_qr_code_base64(login_token)
    return render_template('user_qr_code.html', user=user, qr_code=qr_code_b64)

@app.route('/reports', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def reports_page():
    today = datetime.today()
    start_date = today.replace(day=1).strftime('%Y-%m-%d')
    end_date = today.strftime('%Y-%m-%d')

    if request.method == 'POST':
        if 'sale_id_to_delete' in request.form:
            sale_id = request.form['sale_id_to_delete']
            if db.delete_sale_record(sale_id):
                flash(f"Sotuv (ID: {sale_id}) o'chirildi.", "success")
            else:
                flash("Sotuvni o'chirishda xatolik.", "danger")
            return redirect(url_for('reports_page'))
        else:
            start_date = request.form.get('start_date', start_date)
            end_date = request.form.get('end_date', end_date)
    
    sales_data, total_revenue, total_profit = db.get_sales_report(start_date, end_date)
    return render_template('reports.html', 
                           sales=sales_data, 
                           total_revenue=total_revenue,
                           total_profit=total_profit,
                           start_date=start_date,
                           end_date=end_date)
                           
@app.route('/warehouse')
@login_required
@role_required(['warehouse', 'admin'])
def warehouse_dashboard():
    return render_template('warehouse_dashboard.html', products=db.view_products())

@app.route('/warehouse/receive', methods=['POST'])
@login_required
@role_required(['warehouse', 'admin'])
def receive_stock():
    try:
        product_id = int(request.form['product_id'])
        quantity = int(request.form['quantity'])
        user_id = session['user']['id']
        notes = request.form.get('notes', 'Omborga kirim')
        
        success, message = db.warehouse_movement(product_id, abs(quantity), 'kirim', user_id, notes)
        flash(message, 'success' if success else 'danger')
    except (ValueError, TypeError):
        flash("Noto'g'ri ma'lumot kiritildi.", "danger")
    return redirect(url_for('warehouse_dashboard'))

@app.route('/warehouse/dispatch', methods=['POST'])
@login_required
@role_required(['warehouse', 'admin'])
def dispatch_stock():
    try:
        product_id = int(request.form['product_id'])
        quantity = int(request.form['quantity'])
        user_id = session['user']['id']
        notes = request.form.get('notes', 'Do\'konga chiqim')

        success, message = db.warehouse_movement(product_id, -abs(quantity), 'chiqim', user_id, notes)
        flash(message, 'success' if success else 'danger')
    except (ValueError, TypeError):
        flash("Noto'g'ri ma'lumot kiritildi.", "danger")
    return redirect(url_for('warehouse_dashboard'))

@app.route('/order-recommendations')
@login_required
@role_required(['admin', 'warehouse'])
def order_recommendations_page():
    recommendations = db.generate_automated_order_list()
    return render_template('order_recommendations.html', recommendations=recommendations)

@app.route('/inventory-history')
@login_required
@role_required('admin')
def inventory_history_page():
    history = db.get_inventory_history()
    return render_template('inventory_history.html', history=history)

@app.route('/inventory-history/delete/<int:movement_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_movement_route(movement_id):
    if db.delete_inventory_movement(movement_id):
        flash(f"Harakat (ID: {movement_id}) o'chirildi.", "success")
    else:
        flash("Harakatni o'chirishda xatolik.", "danger")
    return redirect(url_for('inventory_history_page'))

@app.route('/cashier-performance')
@login_required
@role_required('admin')
def cashier_performance_page():
    cashiers_stats = db.get_cashier_performance_stats(days=30)
    
    for cashier in cashiers_stats:
        cashier['points'] = int((cashier.get('total_sales_amount') or 0) / 100000)
        cashier['stars_filled'] = min(cashier['points'] // 10, 5)
        
    return render_template('cashier_performance.html', cashiers=cashiers_stats)

#if __name__ == '__main__':
    app.run(debug=True)
