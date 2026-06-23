from flask import Flask
from app.extensions import mail
import os
from dotenv import load_dotenv

def create_app():
    # 1. Setup
    load_dotenv()
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.secret_key = os.getenv("SECRET_KEY")
    
    # 2. Mail Configuration
    app.config['MAIL_SERVER'] = 'smtp.gmail.com'
    app.config['MAIL_PORT'] = 587
    app.config['MAIL_USE_TLS'] = True
    app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')

    # Force the email sender to remain silent and bypass network calls:
    app.config['MAIL_SUPPRESS_SEND'] = False  # Set to True to suppress sending emails during development/testing
    
    # 3. Initialize Extensions
    mail.init_app(app)
    
    # 4. Import and Register Blueprints
    from app.routes.auth import auth
    from app.routes.admin import admin
    from app.routes.employee import employee
    from app.routes.shifts import shifts

    app.register_blueprint(auth)
    app.register_blueprint(admin)
    app.register_blueprint(employee)
    app.register_blueprint(shifts)
    
    return app