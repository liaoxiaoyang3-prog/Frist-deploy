# app/decorators.py
from functools import wraps
from flask import request, redirect, url_for
from app.db import get_db_connection

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        passport = request.cookies.get('visitor_passport')
        if passport != 'approved':
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        passport = request.cookies.get('visitor_passport')
        if passport != 'approved':
            return redirect(url_for('auth.login'))
        user_id = request.cookies.get('user_id')
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT user_role FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        if not user or user['user_role'] not in ['admin', 'manager']:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated