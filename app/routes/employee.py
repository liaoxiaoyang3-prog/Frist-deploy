from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.db import get_db_connection
from app.decorators import login_required

employee = Blueprint('employee', __name__)  # <-- this line must exist

MORNING_SLOTS = ['7-12', '8-1', '9-2', 'Morning']

@employee.route('/Employee_Dashboard')
@login_required
def Employee_Dashboard():
    user_id = request.cookies.get('user_id')
    user_name = request.cookies.get('user_name', default="Employee")
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Query 1: Fetch all user shift applications
        cursor.execute("""
            SELECT day_of_week, shift_time, custom_time, status, applied_at 
            FROM shift_applications 
            WHERE user_id = %s
        """, (user_id,))
        raw_applications = cursor.fetchall()

        # Query 2: Fetch all confirmed shifts from the pool
        cursor.execute("""
            SELECT day_of_week, shift_time, assigned_at 
            FROM hotel_shifts 
            WHERE assigned_user_id = %s 
            ORDER BY FIELD(day_of_week, 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
        """, (user_id,))
        confirmed_shifts = cursor.fetchall()
        
    except Exception as err:
        raw_applications = []
        confirmed_shifts = []
        flash(f"Error loading dashboard data: {err}")
    finally:
        cursor.close()
        conn.close()

    user_apps = {}
    morning_blocked_days = set()

    for app_rec in raw_applications:
        day = app_rec['day_of_week']
        slot = app_rec['shift_time']
        status = app_rec['status']
        if day not in user_apps:
            user_apps[day] = {}
        user_apps[day][slot] = app_rec
        if slot in MORNING_SLOTS and status != 'rejected':
            morning_blocked_days.add(day)

    error = request.args.get('error')
    success = request.args.get('success')
    days_list = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

    return render_template('Employee_Dashboard.html',
                           user_name=user_name,
                           user_apps=user_apps,
                           morning_blocked_days=morning_blocked_days,
                           days_list=days_list,
                           confirmed_shifts=confirmed_shifts,
                           error=error,
                           success=success)


@employee.route('/apply_shift', methods=['POST'])
@login_required
def apply_shift():
    user_id = request.cookies.get('user_id')
    day_of_week = request.form.get('day_of_week')
    shift_time = request.form.get('shift_time')
    custom_time = request.form.get('custom_time', '').strip()

    if shift_time != 'Other':
        custom_time = None
    elif not custom_time:
        return redirect(url_for('employee.Employee_Dashboard', error="Please specify your custom time layout."))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Check 1: System settings verification
        cursor.execute("SELECT key_value FROM system_settings WHERE key_name = 'applications_open'")
        setting = cursor.fetchone()
        if not setting or setting['key_value'] != 'true':
            return redirect(url_for('employee.Employee_Dashboard', error="Applications are currently closed by the administrator."))

        # Check 2: Check for morning conflicts
        if shift_time in ['7-12', '8-1', '9-2', 'Morning']:
            cursor.execute("""
                SELECT shift_time FROM shift_applications 
                WHERE user_id = %s AND day_of_week = %s 
                AND shift_time IN ('7-12', '8-1', '9-2', 'Morning') AND status != 'rejected'
            """, (user_id, day_of_week))
            if cursor.fetchone():
                return redirect(url_for('employee.Employee_Dashboard', error=f"You already have a morning shift locked in for {day_of_week}."))

        # Step 3: Insert the approved application
        cursor.execute("""
            INSERT INTO shift_applications (user_id, day_of_week, shift_time, custom_time, status)
            VALUES (%s, %s, %s, %s, 'pending')
        """, (user_id, day_of_week, shift_time, custom_time))
        
        conn.commit()
        return redirect(url_for('employee.Employee_Dashboard', success="Shift applied successfully!"))
        
    except Exception as err:
        return redirect(url_for('employee.Employee_Dashboard', error=f"Database Error: {err}"))
    finally:
        cursor.close()
        conn.close()


@employee.route('/delete_shift/<day_of_week>/<shift_time>', methods=['POST'])
@login_required
def delete_shift(day_of_week, shift_time):
    user_id = request.cookies.get('user_id')
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            DELETE FROM shift_applications 
            WHERE user_id = %s AND day_of_week = %s
        """, (user_id, day_of_week))
        
        conn.commit()
        return redirect(url_for('employee.Employee_Dashboard', success="Shift withdrawn successfully."))
        
    except Exception as err:
        conn.rollback()
        return redirect(url_for('employee.Employee_Dashboard', error=f"Database Error: {err}"))
    finally:
        cursor.close()
        conn.close()