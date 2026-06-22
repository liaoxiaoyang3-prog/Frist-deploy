from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app.db import get_db_connection
from app.decorators import admin_required
import datetime
import re

shifts = Blueprint('shifts', __name__)

def parse_required_roles(role_string):
    if not role_string:
        return {}
    roles = {}
    segments = role_string.split(',')
    for segment in segments:
        match = re.search(r'(\d+)x\s+(.+)', segment.strip())
        if match:
            count = int(match.group(1))
            role_name = match.group(2).strip().lower().replace('baristar', 'barista')
            roles[role_name] = count
        else:
            role_name = segment.strip().lower().replace('baristar', 'barista')
            if role_name:
                roles[role_name] = 1
    return roles

def normalize_positions(pos_str):
    if not pos_str:
        return []
    return [p.strip().lower().replace('baristar', 'barista') for p in pos_str.split(',')]


@shifts.route('/admin_shift_dashboard', methods=['GET'])
@admin_required
def admin_shift_dashboard():
    admin_name = request.cookies.get('user_name', default="Administrator")
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    days  = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    slots = ['7-12', '8-1', '9-2', '6-12', 'Other']

    today                 = datetime.date.today()
    days_until_next_monday = 7 - today.weekday()
    next_monday           = today + datetime.timedelta(days=days_until_next_monday)

    day_dates = {}
    for i, day_name in enumerate(days):
        day_dates[day_name] = (next_monday + datetime.timedelta(days=i)).strftime('%b %d')

    cursor.execute("SELECT key_value FROM system_settings WHERE key_name = 'applications_open'")
    apps_open_setting  = cursor.fetchone()
    applications_open  = apps_open_setting['key_value'] if apps_open_setting else 'true'

    # ── Capacities ────────────────────────────────────────────────────────────
    cursor.execute("SELECT day_of_week, shift_time, capacity, required_role FROM shift_capacities")
    raw_capacities = cursor.fetchall()
    capacities = {day: {slot: {'capacity': 0, 'required_role': ''} for slot in slots} for day in days}
    for cap in raw_capacities:
        if cap['day_of_week'] in capacities and cap['shift_time'] in slots:
            capacities[cap['day_of_week']][cap['shift_time']] = {
                'capacity':      cap['capacity'],
                'required_role': cap['required_role']
            }

    # ── Fetch all applications ────────────────────────────────────────────────
    cursor.execute("""
        SELECT sa.app_id, sa.user_id, sa.day_of_week, sa.shift_time, sa.status,
               u.credits, u.ranking, a.agency_name,
               GROUP_CONCAT(LOWER(p.position_name) SEPARATOR ',') AS user_positions
        FROM shift_applications sa
        JOIN users u ON sa.user_id = u.user_id
        JOIN agencies a ON u.agency_id = a.agency_id
        LEFT JOIN user_positions up ON u.user_id = up.user_id
        LEFT JOIN positions p ON up.position_id = p.position_id
        GROUP BY sa.app_id
    """)
    initial_apps = cursor.fetchall()

    global_counts = {day: {slot: 0 for slot in slots} for day in days}
    approved_ids = []
    pending_ids = []

    # ── Dynamic 4-Pass Pool Sorting Engine ────────────────────────────────────
    for day in days:
        for slot in slots:
            config    = capacities[day][slot]
            max_cap   = config['capacity']
            req_roles = parse_required_roles(config['required_role'])

            role_quotas = {role: count for role, count in req_roles.items()}
            current_slot_count = 0

            # Pool approved and pending applications together to find the absolute best candidates
            pool = [
                a for a in initial_apps
                if a['day_of_week'] == day
                and a['shift_time']  == slot
                and a['status'] in ('approved', 'pending')
            ]

            inhouse_pool = [a for a in pool if a['ranking'] in ('in_house', 'permanent_casual')]
            inhouse_pool.sort(key=lambda x: x['credits'], reverse=True)

            external_pool = [a for a in pool if a['ranking'] not in ('in_house', 'permanent_casual')]
            external_pool.sort(key=lambda x: x['credits'], reverse=True)

            slot_approved = []

            # PASS 1: Fill required roles using qualified In-House candidates
            for cand in list(inhouse_pool):
                if current_slot_count < max_cap:
                    user_roles = normalize_positions(cand['user_positions'])
                    for r in role_quotas:
                        if r in user_roles and role_quotas[r] > 0:
                            slot_approved.append(cand['app_id'])
                            current_slot_count += 1
                            role_quotas[r] -= 1
                            inhouse_pool.remove(cand)
                            break

            # PASS 2: Fill required roles using qualified Part-Timers / External candidates
            for cand in list(external_pool):
                if current_slot_count < max_cap:
                    user_roles = normalize_positions(cand['user_positions'])
                    for r in role_quotas:
                        if r in user_roles and role_quotas[r] > 0:
                            slot_approved.append(cand['app_id'])
                            current_slot_count += 1
                            role_quotas[r] -= 1
                            external_pool.remove(cand)
                            break

            # PASS 3: Fill left-over open slots with remaining In-House candidates
            for cand in list(inhouse_pool):
                if current_slot_count < max_cap:
                    slot_approved.append(cand['app_id'])
                    current_slot_count += 1
                    inhouse_pool.remove(cand)

            # PASS 4: Fill left-over open slots with remaining Part-Timers
            for cand in list(external_pool):
                if current_slot_count < max_cap:
                    slot_approved.append(cand['app_id'])
                    current_slot_count += 1
                    external_pool.remove(cand)

            # Map the evaluated results back to database tracking arrays
            for cand in pool:
                if cand['app_id'] in slot_approved:
                    approved_ids.append(cand['app_id'])
                else:
                    pending_ids.append(cand['app_id'])

    # Update changes to the database
    if approved_ids:
        fmt = ','.join(['%s'] * len(approved_ids))
        cursor.execute(f"UPDATE shift_applications SET status = 'approved' WHERE app_id IN ({fmt})", tuple(approved_ids))
    if pending_ids:
        fmt = ','.join(['%s'] * len(pending_ids))
        cursor.execute(f"UPDATE shift_applications SET status = 'pending' WHERE app_id IN ({fmt})", tuple(pending_ids))
    
    if approved_ids or pending_ids:
        conn.commit()

    # ── Fetch Agencies (Starecruitz Forced to Top) ───────────────────────────
    cursor.execute("SELECT * FROM agencies;")
    agencies          = cursor.fetchall()
    external_agencies = [a for a in agencies if a['agency_name'] != 'Hotel']
    external_agencies.sort(key=lambda x: 0 if x['agency_name'].strip().lower() == 'starecruitz' else 1)

    cursor.execute("""
        SELECT u.user_id, u.user_name, u.email, u.user_role
        FROM users u
        JOIN agencies a ON u.agency_id = a.agency_id
        WHERE a.agency_name = 'Hotel'
        AND u.ranking IN ('in_house', 'permanent_casual')
    """)
    hotel_employees = cursor.fetchall()

    hotel_roster = {}
    for emp in hotel_employees:
        hotel_roster[emp['user_id']] = {
            'user_name': emp['user_name'],
            'email':     emp['email'],
            'user_role': emp['user_role'],
            'schedule':  {day: None for day in days}
        }

    cursor.execute("""
        SELECT sa.app_id, sa.user_id, sa.day_of_week, sa.shift_time,
               sa.custom_time, sa.status,
               u.user_name, u.credits, u.user_role, a.agency_name,
               GROUP_CONCAT(p.position_name SEPARATOR ', ') AS user_positions
        FROM shift_applications sa
        JOIN users u ON sa.user_id = u.user_id
        JOIN agencies a ON u.agency_id = a.agency_id
        LEFT JOIN user_positions up ON u.user_id = up.user_id
        LEFT JOIN positions p ON up.position_id = p.position_id
        GROUP BY sa.app_id
    """)
    all_applications = cursor.fetchall()
    cursor.close()
    conn.close()

    grid_data = {
        day: {
            agency['agency_name']: {slot: {'green': [], 'red': [], 'yellow': []} for slot in slots}
            for agency in external_agencies
        }
        for day in days
    }

    for cand in all_applications:
        day         = cand['day_of_week']
        slot        = cand['shift_time']
        agency_name = cand['agency_name']

        if agency_name == 'Hotel':
            if cand['user_id'] in hotel_roster:
                hotel_roster[cand['user_id']]['schedule'][day] = {
                    'app_id':     cand['app_id'],
                    'shift_time': slot if slot != 'Other' else cand['custom_time'],
                    'status':     cand['status'],
                    'is_morning': slot == 'Morning'
                }
        else:
            target_slots = ['7-12', '8-1', '9-2'] if (slot == 'Morning' and cand['status'] == 'pending') else [slot]
            for t_slot in target_slots:
                if agency_name in grid_data[day] and t_slot in slots:
                    block = {
                        'app_id':      cand['app_id'],
                        'user_id':     cand['user_id'],
                        'name':        cand['user_name'],
                        'credit':      cand['credits'],
                        'role':        cand['user_role'],
                        'orig_slot':   slot,
                        'positions':   cand['user_positions'] or '',
                        'agency_name': agency_name
                    }
                    if cand['status'] == 'approved':
                        grid_data[day][agency_name][t_slot]['green'].append(block)
                    elif cand['status'] == 'rejected':
                        grid_data[day][agency_name][t_slot]['red'].append(block)
                    else:
                        grid_data[day][agency_name][t_slot]['yellow'].append(block)

    return render_template('admin_shift_dashboard.html',
                           applications_open=applications_open,
                           capacities=capacities,
                           grid_data=grid_data,
                           hotel_roster=hotel_roster.values(),
                           days=days,
                           slots=slots,
                           external_agencies=external_agencies,
                           admin_name=admin_name,
                           day_dates=day_dates)


@shifts.route('/api/assign_morning_slot', methods=['POST'])
@admin_required
def api_assign_morning_slot():
    data        = request.get_json()
    app_id      = data.get('app_id')
    day         = data.get('day_of_week')
    target_slot = data.get('target_slot')

    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT sa.app_id, sa.user_id, u.credits, sa.shift_time as orig_applied_slot,
                   GROUP_CONCAT(LOWER(p.position_name) SEPARATOR ',') AS user_positions
            FROM shift_applications sa
            JOIN users u ON sa.user_id = u.user_id
            LEFT JOIN user_positions up ON u.user_id = up.user_id
            LEFT JOIN positions p ON up.position_id = p.position_id
            WHERE sa.app_id = %s
            GROUP BY sa.app_id
        """, (app_id,))
        morning_app = cursor.fetchone()
        if not morning_app:
            return jsonify({'success': False, 'message': 'Application record not found'}), 404

        cursor.execute("""
            SELECT capacity, required_role FROM shift_capacities
            WHERE day_of_week = %s AND shift_time = %s
        """, (day, target_slot))
        cap_row   = cursor.fetchone()
        max_cap   = cap_row['capacity']      if cap_row else 0
        req_roles = parse_required_roles(cap_row['required_role'] if cap_row else '')

        cursor.execute("""
            SELECT sa.app_id, sa.user_id, u.credits, sa.shift_time as current_slot,
                   GROUP_CONCAT(LOWER(p.position_name) SEPARATOR ',') AS user_positions
            FROM shift_applications sa
            JOIN users u ON sa.user_id = u.user_id
            LEFT JOIN user_positions up ON u.user_id = up.user_id
            LEFT JOIN positions p ON up.position_id = p.position_id
            WHERE sa.day_of_week = %s AND sa.shift_time = %s AND sa.status = 'approved'
            GROUP BY sa.app_id
        """, (day, target_slot))
        current_occupants = cursor.fetchall()

        kicked_app_id = None

        if len(current_occupants) >= max_cap:
            def occ_has_role(occ):
                user_roles = normalize_positions(occ['user_positions'])
                return not req_roles or any(r in req_roles for r in user_roles)

            current_occupants.sort(key=lambda o: (1 if occ_has_role(o) else 0, o['credits']))
            victim = current_occupants[0]
            
            app_match = any(r in req_roles for r in normalize_positions(morning_app['user_positions'])) if req_roles else True
            vic_match = occ_has_role(victim)

            can_displace = False
            if app_match and not vic_match:
                can_displace = True
            elif not app_match and vic_match:
                can_displace = False
            else:
                if morning_app['credits'] > victim['credits']:
                    can_displace = True
                else:
                    can_displace = False

            if not can_displace:
                return jsonify({
                    'success': False, 
                    'message': f"Capacity allocation blocked. New applicant cannot displace current occupant based on role matching rules or credit ranking values."
                }), 400

            kicked_app_id = victim['app_id']
            
            cursor.execute("SELECT shift_time FROM shift_applications WHERE app_id = %s", (kicked_app_id,))
            kicked_meta = cursor.fetchone()
            orig_slot_backup = kicked_meta['shift_time'] if kicked_meta else target_slot

            cursor.execute("""
                UPDATE shift_applications 
                SET status = 'pending', shift_time = %s 
                WHERE app_id = %s
            """, (orig_slot_backup, kicked_app_id))

        cursor.execute("""
            UPDATE shift_applications
            SET shift_time = %s, status = 'approved'
            WHERE app_id = %s
        """, (target_slot, morning_app['app_id']))

        conn.commit()
        return jsonify({'success': True, 'kicked_app_id': kicked_app_id})

    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@shifts.route('/admin_shift_settings')
@admin_required
def admin_shift_settings():
    admin_name = request.cookies.get('user_name', default="Administrator")
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT key_value FROM system_settings WHERE key_name = 'applications_open'")
    apps_open_setting = cursor.fetchone()
    applications_open = apps_open_setting['key_value'] if apps_open_setting else 'true'

    cursor.execute("SELECT day_of_week, shift_time, capacity, required_role FROM shift_capacities")
    raw_capacities = cursor.fetchall()
    capacities = {}
    for cap in raw_capacities:
        day  = cap['day_of_week']
        slot = cap['shift_time']
        if day not in capacities:
            capacities[day] = {}
        capacities[day][slot] = {'capacity': cap['capacity'], 'required_role': cap['required_role']}

    cursor.close()
    conn.close()

    days  = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    slots = ['7-12', '8-1', '9-2', '6-12', 'Other']

    return render_template('admin_shift_settings.html',
                           applications_open=applications_open,
                           capacities=capacities,
                           days=days,
                           slots=slots,
                           admin_name=admin_name)


@shifts.route('/admin_update_settings', methods=['POST'])
@admin_required
def admin_update_settings():
    conn   = get_db_connection()
    cursor = conn.cursor()
    try:
        status_toggle = request.form.get('applications_open', 'false')
        cursor.execute("""
            INSERT INTO system_settings (key_name, key_value)
            VALUES ('applications_open', %s)
            ON DUPLICATE KEY UPDATE key_value = %s
        """, (status_toggle, status_toggle))

        days  = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        slots = ['7-12', '8-1', '9-2', '6-12', 'Other']

        for day in days:
            for slot in slots:
                cap_val  = request.form.get(f"cap_{day}_{slot}", "0")
                role_val = request.form.get(f"role_{day}_{slot}", "").strip()
                cursor.execute("""
                    INSERT INTO shift_capacities (day_of_week, shift_time, capacity, required_role)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE capacity = %s, required_role = %s
                """, (day, slot, cap_val, role_val, cap_val, role_val))

        conn.commit()
        flash('Shift configurations updated successfully!', 'success')
    except Exception as err:
        print(f"Error: {err}")
        conn.rollback()
        flash('Failed to update configurations.', 'error')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('shifts.admin_shift_settings'))


@shifts.route('/api/update_application_status', methods=['POST'])
@admin_required
def api_update_application_status():
    data          = request.get_json()
    user_id       = data.get('user_id')
    orig_slot     = data.get('orig_slot')
    target_slot   = data.get('target_slot')
    day_of_week   = data.get('day_of_week')
    target_status = data.get('status')

    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        is_morning_target = target_slot in ['7-12', '8-1', '9-2']
        is_morning_origin = orig_slot   in ['Morning', '7-12', '8-1', '9-2']

        if is_morning_target or is_morning_origin:
            cursor.execute("""
                SELECT app_id FROM shift_applications
                WHERE user_id = %s AND day_of_week = %s
                AND shift_time IN ('Morning', '7-12', '8-1', '9-2')
            """, (user_id, day_of_week))
            app = cursor.fetchone()

            if app:
                if target_status == 'approved':
                    cursor.execute("""
                        UPDATE shift_applications
                        SET shift_time = %s, status = 'approved'
                        WHERE app_id = %s
                    """, (target_slot, app['app_id']))
                else:
                    cursor.execute("""
                        UPDATE shift_applications
                        SET shift_time = %s, status = 'pending'
                        WHERE app_id = %s
                    """, (orig_slot, app['app_id']))
        else:
            db_status = 'approved' if target_status == 'approved' else 'pending'
            cursor.execute("""
                UPDATE shift_applications
                SET status = %s
                WHERE user_id = %s AND day_of_week = %s AND shift_time = %s
            """, (db_status, user_id, day_of_week, orig_slot))

        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()