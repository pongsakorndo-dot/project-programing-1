import os
from flask import Flask, render_template, session, redirect, url_for, request
from app.database import read_json_file  # ดึงฟังค์ชันอ่านไฟล์ JSON
from app.blueprints.auth import auth_bp
from app.blueprints.products import products_bp
from app.blueprints.stock import stock_bp
from app.blueprints.suppliers import suppliers_bp
from app.blueprints.reports import reports_bp

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me')
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'

    # Register API Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(stock_bp)
    app.register_blueprint(suppliers_bp)
    app.register_blueprint(reports_bp)

    # 1. เพิ่ม Context Processor ส่ง current_user ให้ Template ทุกหน้าอัตโนมัติ
    @app.context_processor
    def inject_user():
        user = session.get('user') or {}
        username = session.get('username') or user.get('username')
        role = session.get('user_role') or user.get('role', 'user')

        if username:
            current_user = {
                'is_authenticated': True,
                'username': username,
                'role': role
            }
        else:
            current_user = {
                'is_authenticated': False,
                'username': '',
                'role': ''
            }
        return dict(current_user=current_user)

    # Authentication Gatekeeper
    @app.before_request
    def check_login():
        allowed_paths = ['/login', '/static']

        if request.path.startswith('/api/'):
            return None

        stored_user = session.get('user') or {}
        stored_username = session.get('username') or stored_user.get('username')
        if stored_username:
            session['username'] = stored_username

        if not stored_username and not any(request.path.startswith(p) for p in allowed_paths):
            return redirect(url_for('login_page'))

    # HTML Routes
    # HTML Routes
    @app.route('/login')
    def login_page():
        return render_template('login.html')

    # 2. ปรับปรุง Route หน้าแรก (/) ให้โหลดข้อมูลสินค้าและซัพพลายเออร์มาแสดงในแดชบอร์ด
    @app.route('/')
    def index_page():
        products = read_json_file('products.json')
        suppliers = read_json_file('suppliers.json')
        return render_template('index.html', products=products, suppliers=suppliers)

    @app.route('/products')
    @app.route('/products-page')
    def products_page():
        return render_template('products.html')

    @app.route('/suppliers')
    @app.route('/suppliers-page')
    def suppliers_page():
        return render_template('suppliers.html')

    @app.route('/advanced-page')
    def advanced_page():
        return render_template('advanced_inventory.html')

    @app.route('/admin')
    def admin_page():
        user = session.get('user') or {}
        user_role = session.get('user_role') or user.get('role')
        username = session.get('username') or user.get('username')
        if not username or user_role != 'admin':
            return redirect('/')
        return render_template('admin.html')

    @app.route('/logout')
    def logout_shortcut():
        return redirect('/api/auth/logout')

    return app