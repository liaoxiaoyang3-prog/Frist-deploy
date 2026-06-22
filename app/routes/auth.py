# app/routes/auth.py
from flask import Blueprint, render_template, request, redirect, session, url_for, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from app.db import get_db_connection
from itsdangerous import URLSafeTimedSerializer as Serializer
from flask import current_app
from flask_mail import Message, Mail
import random

mail = Mail()

# Add this inside your auth route file
def get_reset_token(email):
    s = Serializer(current_app.config['SECRET_KEY'])
    return s.dumps({'email': email})

def verify_reset_token(token, expires_sec=1800):
    s = Serializer(current_app.config['SECRET_KEY'])
    try:
        email = s.loads(token, max_age=expires_sec)['email']
    except:
        return None
    return email



auth = Blueprint('auth', __name__)

def hash_password(p):
    return generate_password_hash(p, method='scrypt')

def verify_password(stored, plain):
    return check_password_hash(stored, plain)

@auth.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        email = request.form.get('email').strip()
        password = request.form.get('password')

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and verify_password(user['user_password'], password):
            if not user['is_approved']:
                error = "Your account is pending administrator approval."
            else:
                if user['user_role'] in ['admin', 'manager']:
                    response = make_response(redirect(url_for('admin.Admin_Dashboard')))
                elif user['user_role'] == 'user':
                    response = make_response(redirect(url_for('employee.Employee_Dashboard')))
                else:
                    error = "Access Denied: Unrecognized account role."
                    return render_template('login.html', error=error)

                response.set_cookie('visitor_passport', 'approved', max_age=60*60*24, httponly=True)
                response.set_cookie('user_name', user['user_name'], max_age=60*60*24)
                response.set_cookie('user_id', str(user['user_id']), max_age=60*60*24, httponly=True)
                return response
        else:
            error = "Invalid email address or password."

    return render_template('login.html', error=error)

@auth.route('/signup', methods=['GET', 'POST'])
def signup():
    error = None
    if request.method == 'POST':
        name = request.form.get('user_name').strip()
        email = request.form.get('email').strip().lower()
        
        # 1. Grab the agency_id from the dropdown selection
        agency_id = request.form.get('agency_id')
        
        password = request.form.get('user_password')
        confirm_password = request.form.get('confirm_password')

        if password != confirm_password:
            error = "Passwords do not match."
        else:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            existing_user = cursor.fetchone()
            cursor.close()
            conn.close()

            if existing_user:
                error = "This email address is already registered."
            else:
                # Generate a secure 6-digit random code
                otp_code = str(random.randint(100000, 999999))
                
                # 2. Store the agency_id alongside other temporary user data in the session
                session['pending_user'] = {
                    'user_name': name,
                    'email': email,
                    'user_password': hash_password(password),
                    'agency_id': agency_id,  # <-- Added
                    'otp': otp_code
                }
                
                # Email the code to the user
                try:
                    msg = Message('EMBU Hotel Portal - Verify Your Email',
                                  sender='noreply@embu.com',
                                  recipients=[email])
                    msg.body = f"Hello {name},\n\nYour security verification code is: {otp_code}\n\nPlease enter this code on the portal to continue registration."
                    mail.send(msg)
                    
                    # Redirect them to the OTP input view
                    return redirect(url_for('auth.verify_otp'))
                except Exception as err:
                    error = f"Failed to send validation email: {err}"

    return render_template('signup.html', error=error)

@auth.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    error = None
    pending_user = session.get('pending_user')
    
    # Security Guard: If they try to view this page without filling signup form first
    if not pending_user:
        return redirect(url_for('auth.signup'))
        
    if request.method == 'POST':
        input_otp = request.form.get('otp').strip()
        
        # Compare user input to stored verification code
        if input_otp == pending_user['otp']:
            conn = get_db_connection()
            cursor = conn.cursor()
            try:
                # 4. OTP matches! Now we write an unactivated (is_approved=0) account to DB
                cursor.execute("""INSERT INTO users (user_name, email, user_password, is_approved, user_role, ranking, credits, agency_id)
                    VALUES (%s, %s, %s, 0, 'user', 'Part Time', 0, %s)""", (pending_user['user_name'], pending_user['email'], pending_user['user_password'], pending_user['agency_id']))
                conn.commit()
                
                # Clear the session cache so it can't be reused
                session.pop('pending_user', None)
                
                # Reuse your signup template to show the success view
                return render_template('signup.html', success="Email verified! Your account is now pending administrator/manager approval.")
            except Exception as err:
                error = f"Database registration failure: {err}"
            finally:
                cursor.close()
                conn.close()
        else:
            error = "Invalid verification code. Please check your email and try again."
            
    return render_template('verify_otp.html', error=error, email=pending_user['email'])

@auth.route('/reset_password_request', methods=['GET', 'POST'])
def reset_request():
    if request.method == 'POST':
        email = request.form.get('email')
        token = get_reset_token(email)
        
        # Construct the email
        msg = Message('Password Reset Request',
                      sender='noreply@embu.com',
                      recipients=[email])
        msg.body = f'''To reset your password, visit the following link:
{url_for('auth.reset_token', token=token, _external=True)}

If you did not make this request, simply ignore this email.
'''
        mail.send(msg)
        return "Check your email for the reset link."
    return render_template('reset_request.html')

@auth.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_token(token):
    email = verify_reset_token(token)
    if not email:
        return "Token is invalid or expired."
    
    # ADD THIS LOGIC TO HANDLE THE FORM SUBMISSION
    if request.method == 'POST':
        new_password = request.form.get('password')
        
        # 1. Hash the new password using your existing function
        hashed_pw = hash_password(new_password)
        
        # 2. Update the database
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE users SET user_password = %s WHERE email = %s", 
                (hashed_pw, email)
            )
            conn.commit()
            return "Your password has been successfully updated! You can now <a href='/login'>login</a>."
        except Exception as e:
            return f"Error updating password: {e}"
        finally:
            cursor.close()
            conn.close()

    # If it's a GET request, just show the form
    return render_template('reset_password.html')

@auth.route('/logout')
def logout():
    response = make_response(redirect(url_for('auth.login')))
    response.delete_cookie('visitor_passport')
    response.delete_cookie('user_name')
    response.delete_cookie('user_id')
    return response

