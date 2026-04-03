import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from models import db, User, Product, Order, OrderItem
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-key-123'
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'ecommerce.db').replace('\\', '/')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
UPLOAD_FOLDER = os.path.join(basedir, 'static', 'images')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

with app.app_context():
    db.create_all()

    # Create dummy admin if not exists
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', email='admin@example.com', password=generate_password_hash('admin123'), is_admin=True)
        db.session.add(admin)
        
    # Sample products
    if not Product.query.first():
        sample_prods = [
            Product(name='Wireless Headphones', description='High quality noise-cancelling headphones.', price=199.99, image='headphones.png', category='Electronics'),
            Product(name='Running Shoes', description='Comfortable and lightweight shoes for running.', price=89.50, image='running_shoes.png', category='Sports'),
            Product(name='Smartwatch', description='Feature-rich smartwatch with health tracking.', price=149.00, image='smartwatch.png', category='Electronics'),
            Product(name='Coffee Maker', description='Brews delicious coffee in minutes.', price=49.99, image='coffee_maker.png', category='Home'),
        ]
        db.session.bulk_save_objects(sample_prods)
    db.session.commit()

# --- Auth Routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('Logged in successfully.', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash('Login failed. Check your email and password.', 'danger')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        user_exists = User.query.filter_by(email=email).first()
        if user_exists:
            flash('Email address already exists', 'danger')
            return redirect(url_for('signup'))
            
        new_user = User(username=username, email=email, password=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        flash('Account created successfully. Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# --- Main Routes ---
@app.route('/')
def index():
    query = request.args.get('query')
    category = request.args.get('category')
    
    if query:
        products = Product.query.filter(Product.name.ilike(f'%{query}%')).all()
    elif category:
        products = Product.query.filter_by(category=category).all()
    else:
        products = Product.query.all()
        
    categories = [cat[0] for cat in db.session.query(Product.category).distinct() if cat[0]]
    
    return render_template('index.html', products=products, categories=categories, current_category=category)

@app.route('/product/<int:id>')
def product_detail(id):
    product = db.get_or_404(Product, id)
    return render_template('product_detail.html', product=product)

# --- Cart System ---
@app.route('/add_to_cart/<int:id>', methods=['POST'])
def add_to_cart(id):
    if 'cart' not in session:
        session['cart'] = {}
    
    cart = session['cart']
    product_str_id = str(id)
    
    if product_str_id in cart:
        cart[product_str_id] += 1
    else:
        cart[product_str_id] = 1
        
    session.modified = True
    flash('Item added to cart.', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/cart')
def view_cart():
    cart = session.get('cart', {})
    cart_items = []
    total_price = 0.0
    
    for product_id, quantity in cart.items():
        product = db.session.get(Product, int(product_id))
        if product:
            item_total = float(product.price) * quantity
            total_price = total_price + item_total # type: ignore
            cart_items.append({'product': product, 'quantity': quantity, 'item_total': item_total})
            
    return render_template('cart.html', cart_items=cart_items, total_price=total_price)

@app.route('/update_cart/<int:id>', methods=['POST'])
def update_cart(id):
    cart = session.get('cart', {})
    product_str_id = str(id)
    
    action = request.form.get('action')
    
    if product_str_id in cart:
        if action == 'increase':
            cart[product_str_id] += 1
        elif action == 'decrease':
            cart[product_str_id] -= 1
            if cart[product_str_id] <= 0:
                cart.pop(product_str_id)
        elif action == 'remove':
            cart.pop(product_str_id)
            
    session.modified = True
    return redirect(url_for('view_cart'))

# --- Order System ---
@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    cart = session.get('cart', {})
    if not cart:
        flash('Your cart is empty.', 'warning')
        return redirect(url_for('index'))
        
    cart_items = []
    total_price = 0.0
    for product_id, quantity in cart.items():
        product = db.session.get(Product, int(product_id))
        if product:
            total_price = total_price + float(product.price) * quantity # type: ignore
            cart_items.append({'product': product, 'quantity': quantity})
            
    if request.method == 'POST':
        address = request.form.get('address')
        
        # Create Order
        new_order = Order(user_id=current_user.id, address=address, total_price=total_price)
        db.session.add(new_order)
        db.session.commit() # To get order ID
        
        # Create Order Items
        for item in cart_items:
            order_item = OrderItem(order_id=new_order.id, product_id=item['product'].id, quantity=item['quantity'], price=item['product'].price)
            db.session.add(order_item)
            
        db.session.commit()
        
        # Clear cart
        session.pop('cart', None)
        flash('Order placed successfully!', 'success')
        return redirect(url_for('order_confirmation', order_id=new_order.id))
        
    return render_template('checkout.html', total_price=total_price)

@app.route('/order_confirmation/<int:order_id>')
@login_required
def order_confirmation(order_id):
    order = db.get_or_404(Order, order_id)
    if order.user_id != current_user.id:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('index'))
    return render_template('order_confirmation.html', order=order)

@app.route('/orders')
@login_required
def orders():
    user_orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.date_ordered.desc()).all()
    return render_template('orders.html', orders=user_orders)

# --- Admin Routes ---
@app.route('/admin/products')
@login_required
def admin_products():
    if not current_user.is_admin:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('index'))
    products = Product.query.all()
    return render_template('admin_products.html', products=products)

@app.route('/admin/add_product', methods=['POST'])
@login_required
def add_product():
    if not current_user.is_admin:
        return redirect(url_for('index'))
    name = request.form.get('name')
    description = request.form.get('description')
    price = request.form.get('price')
    category = request.form.get('category')
    
    # Simple file upload handling
    image = request.files.get('image')
    image_filename = 'default.jpg'
    if image and image.filename != '':
        filename = secure_filename(image.filename)
        image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        image_filename = filename
        
    new_product = Product(name=name, description=description, price=float(price), category=category, image=image_filename)
    db.session.add(new_product)
    db.session.commit()
    flash('Product added successfully.', 'success')
    return redirect(url_for('admin_products'))

@app.route('/admin/delete_product/<int:id>', methods=['POST'])
@login_required
def delete_product(id):
    if not current_user.is_admin:
        return redirect(url_for('index'))
    product = db.get_or_404(Product, id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted.', 'success')
    return redirect(url_for('admin_products'))

@app.route('/admin/update_product/<int:id>', methods=['POST'])
@login_required
def update_product(id):
    if not current_user.is_admin:
        return redirect(url_for('index'))
    product = db.get_or_404(Product, id)
    
    product.name = request.form.get('name')
    product.description = request.form.get('description')
    product.price = float(request.form.get('price'))
    product.category = request.form.get('category')
    
    image = request.files.get('image')
    if image and image.filename != '':
        filename = secure_filename(image.filename)
        image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        product.image = filename
        
    db.session.commit()
    flash('Product updated.', 'success')
    return redirect(url_for('admin_products'))


if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.run(debug=True, port=5000)
