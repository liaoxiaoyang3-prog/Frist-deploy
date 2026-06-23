# main.py
import os
from app import create_app

app = create_app()

# 2. Mail Configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')

# ADD THIS LINE HERE to prevent the 30-second freeze:
app.config['MAIL_SUPPRESS_SEND'] = True

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)