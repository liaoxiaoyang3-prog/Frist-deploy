from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.security import generate_password_hash
from app.db import get_db_connection
from app.decorators import admin_required

admin = Blueprint('admin', __name__)

@admin.route('/Admin_Dashboard')
@admin_required
def Admin_Dashboard():
    admin_name = request.cookies.get('user_name', default="Administrator")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    search_query = request.args.get('search', default='').strip()
    params = []
    where_clause = ""
    if search_query:
        where_clause = "WHERE LOWER(u.user_name) LIKE LOWER(%s)"
        params.append(f"%{search_query}%")

    # Linked INNER JOIN to fetch the human-readable agency name along with data structure
    cursor.execute(f"""
        SELECT u.user_id, u.user_name, u.email, u.user_password, u.user_role,
               u.ranking, u.credits, u.is_approved, u.agency_id, a.agency_name,
               GROUP_CONCAT(p.position_name SEPARATOR ', ') AS positions_list,
               GROUP_CONCAT(p.position_id SEPARATOR ',') AS position_ids_list
        FROM users u
        INNER JOIN agencies a ON u.agency_id = a.agency_id
        LEFT JOIN user_positions up ON u.user_id = up.user_id
        LEFT JOIN positions p ON up.position_id = p.position_id
        {where_clause}
        GROUP BY u.user_id;
    """, params)
    all_employees = cursor.fetchall()

    cursor.execute("SELECT * FROM positions;")
    all_positions = cursor.fetchall()

    # Fetch all registered operational agency structures
    cursor.execute("SELECT * FROM agencies;")
    all_agencies = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('Admin_Dashboard.html',
                           employees=all_employees,
                           positions=all_positions,
                           agencies=all_agencies,
                           search_query=search_query,
                           admin_name=admin_name)

@admin.route('/add_user', methods=['POST'])
@admin_required
def add_user():
    name = request.form.get('user_name')
    email = request.form.get('email')
    password = request.form.get('user_password')
    role = request.form.get('user_role')
    ranking = request.form.get('ranking')
    credits_val = request.form.get('credits', default=0, type=int)
    agency_id = request.form.get('agency_id', default=1, type=int)
    is_approved = 1 if request.form.get('is_approved') else 0
    selected_position_ids = request.form.getlist('positions')

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO users (user_name, email, user_password, is_approved, user_role, ranking, credits, agency_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (name, email, generate_password_hash(password, method='scrypt'),
              is_approved, role, ranking, credits_val, agency_id))
        new_user_id = cursor.lastrowid

        if selected_position_ids:
            cursor.executemany(
                "INSERT INTO user_positions (user_id, position_id) VALUES (%s, %s)",
                [(new_user_id, int(p)) for p in selected_position_ids]
            )
        conn.commit()
        flash('Employee account created successfully!', 'success')
    except Exception as err:
        conn.rollback()
        flash('Failed to create account. A database error occurred.', 'error')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin.Admin_Dashboard'))

@admin.route('/edit_user/<int:user_id>', methods=['POST'])
@admin_required
def edit_user(user_id):
    name = request.form.get('user_name')
    email = request.form.get('email')
    new_password = request.form.get('user_password', '').strip()
    role = request.form.get('user_role')
    ranking = request.form.get('ranking')
    credits_val = request.form.get('credits', default=0, type=int)
    agency_id = request.form.get('agency_id', default=1, type=int)
    is_approved = 1 if request.form.get('is_approved') else 0
    selected_position_ids = request.form.getlist('positions')

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if new_password:
            cursor.execute("""
                UPDATE users 
                SET user_name=%s, email=%s, user_password=%s,
                    is_approved=%s, user_role=%s, ranking=%s, credits=%s, agency_id=%s
                WHERE user_id=%s
            """, (name, email, generate_password_hash(new_password, method='scrypt'),
                  is_approved, role, ranking, credits_val, agency_id, user_id))
        else:
            cursor.execute("""
                UPDATE users 
                SET user_name=%s, email=%s,
                    is_approved=%s, user_role=%s, ranking=%s, credits=%s, agency_id=%s
                WHERE user_id=%s
            """, (name, email, is_approved, role, ranking, credits_val, agency_id, user_id))

        cursor.execute("DELETE FROM user_positions WHERE user_id = %s", (user_id,))
        if selected_position_ids:
            cursor.executemany(
                "INSERT INTO user_positions (user_id, position_id) VALUES (%s, %s)",
                [(user_id, int(p)) for p in selected_position_ids]
            )
        conn.commit()
        flash('Account modifications saved successfully!', 'success')
    except Exception as err:
        conn.rollback()
        flash('Failed to save modifications due to a database error.', 'error')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin.Admin_Dashboard'))

@admin.route('/toggle_status/<int:user_id>', methods=['POST'])
@admin_required
def toggle_status(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT is_approved FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        new_status = 0 if user['is_approved'] else 1
        cursor.execute("UPDATE users SET is_approved = %s WHERE user_id = %s", (new_status, user_id))
        conn.commit()
        return jsonify({'success': True, 'new_status': new_status})
    except Exception as err:
        return jsonify({'success': False, 'error': str(err)}), 500
    finally:
        cursor.close()
        conn.close()

@admin.route('/delete_user/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        conn.commit()
        flash('Employee permanently deleted.', 'success')
    except Exception as err:
        conn.rollback()
        flash('Failed to delete employee record. A database restriction occurred.', 'error')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin.Admin_Dashboard'))