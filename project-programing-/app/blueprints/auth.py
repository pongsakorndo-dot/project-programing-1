from flask import Blueprint, request, jsonify, session, render_template, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from app.database import read_json_file, write_json_file
from app.utils import role_required
from datetime import datetime

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')
USERS_FILE = 'users.json'
LOGS_FILE = 'logs.json'

def log_activity(username: str, action: str, details: str):
    """ฟังก์ชันบันทึก Activity Logs"""
    try:
        logs = read_json_file(LOGS_FILE)
        logs.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "username": username,
            "action": action,
            "details": details
        })
        write_json_file(LOGS_FILE, logs)
    except Exception as e:
        print(f"Failed to log activity: {e}")

@auth_bp.route('/register', methods=['POST'])
def register():
    """สมัครสมาชิก / เพิ่มผู้ใช้งานใหม่"""
    try:
        data = request.get_json(silent=True) or request.form or {}
        username = str(data.get('username', '')).strip()
        password = str(data.get('password', '')).strip()
        role = str(data.get('role', 'customer')).strip().lower()

        if not username or not password:
            return jsonify({"status": "error", "message": "กรุณากรอกชื่อผู้ใช้และรหัสผ่าน"}), 400
        
        valid_roles = ['admin', 'staff', 'customer']
        if role not in valid_roles:
            return jsonify({"status": "error", "message": "สิทธิ์ผู้ใช้งานไม่ถูกต้อง"}), 400

        users = read_json_file(USERS_FILE)
        
        for user in users:
            if user['username'] == username:
                return jsonify({"status": "error", "message": "ชื่อผู้ใช้นี้มีในระบบแล้ว"}), 400

        new_user = {
            "username": username,
            "password_hash": generate_password_hash(password),
            "role": role
        }
        users.append(new_user)
        
        if write_json_file(USERS_FILE, users):
            current_admin = session.get('username', username)
            log_activity(current_admin, "CREATE_USER", f"สร้างบัญชีใหม่: {username} สิทธิ์: {role}")
            return jsonify({"status": "success", "message": "เพิ่มผู้ใช้งานสำเร็จ"}), 201
        return jsonify({"status": "error", "message": "ไม่สามารถบันทึกข้อมูลได้"}), 500

    except Exception as e:
        return jsonify({"status": "error", "message": f"เกิดข้อผิดพลาด: {str(e)}"}), 500

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """เข้าสู่ระบบ"""
    if request.method == 'POST':
        try:
            data = request.get_json(silent=True) or request.form
            username = str(data.get('username', '')).strip()
            password = str(data.get('password', '')).strip()

            users = read_json_file(USERS_FILE)
            user = None
            for u in users:
                if u['username'] == username:
                    user = u
                    break

            if user and check_password_hash(user['password_hash'], password):
                session['user'] = user
                session['username'] = user['username']
                session['user_role'] = user['role']
                log_activity(username, "LOGIN", "เข้าสู่ระบบสำเร็จ")

                if request.form:
                    return redirect('/')
                
                return jsonify({
                    "status": "success",
                    "message": "เข้าสู่ระบบสำเร็จ",
                    "role": user['role']
                }), 200

            if request.form:
                return render_template('login.html', error="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
            return jsonify({"status": "error", "message": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"}), 401

        except Exception as e:
            if request.form:
                return render_template('login.html', error="เกิดข้อผิดพลาดในการเข้าสู่ระบบ")
            return jsonify({"status": "error", "message": "เกิดข้อผิดพลาดในการเข้าสู่ระบบ"}), 500

    return render_template('login.html')

@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    """ออกจากระบบ"""
    try:
        username = session.get('username', 'Unknown')
        log_activity(username, "LOGOUT", "ออกจากระบบ")
        session.clear()
        if request.method == 'GET' or request.form:
            return redirect('/login')
        return jsonify({"status": "success", "message": "ออกจากระบบสำเร็จ"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": "เกิดข้อผิดพลาดในการออกจากระบบ"}), 500

@auth_bp.route('/logs', methods=['GET'])
@role_required(['admin'])
def get_logs():
    """ดูประวัติการใช้งาน (Activity Logs)"""
    try:
        logs = read_json_file(LOGS_FILE)
        return jsonify({"status": "success", "data": logs}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": "ไม่สามารถดึงข้อมูล Logs ได้"}), 500

@auth_bp.route('/users', methods=['GET'])
@role_required(['admin'])
def get_users():
    """ดึงรายชื่อผู้ใช้ทั้งหมด"""
    try:
        users = read_json_file(USERS_FILE)
        safe_users = [{"username": u["username"], "role": u["role"]} for u in users]
        return jsonify({"status": "success", "data": safe_users}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": "ไม่สามารถดึงข้อมูลผู้ใช้ได้"}), 500

@auth_bp.route('/users/update-role', methods=['PUT'])
@role_required(['admin'])
def update_user_role():
    """แก้ไขสิทธิ์ผู้ใช้งาน"""
    try:
        data = request.get_json(silent=True) or {}
        username = str(data.get('username', '')).strip()
        new_role = str(data.get('role', '')).strip().lower()

        valid_roles = ['admin', 'staff', 'customer']
        if new_role not in valid_roles:
            return jsonify({"status": "error", "message": "สิทธิ์ผู้ใช้งานไม่ถูกต้อง"}), 400

        users = read_json_file(USERS_FILE)
        updated = False
        for u in users:
            if u['username'] == username:
                u['role'] = new_role
                updated = True
                break

        if updated:
            write_json_file(USERS_FILE, users)
            log_activity(session.get('username'), "UPDATE_ROLE", f"เปลี่ยนสิทธิ์ของ {username} เป็น {new_role}")
            return jsonify({"status": "success", "message": "อัปเดตสิทธิ์ผู้ใช้สำเร็จ"}), 200
        return jsonify({"status": "error", "message": "ไม่พบผู้ใช้นี้ในระบบ"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": f"เกิดข้อผิดพลาด: {str(e)}"}), 500

@auth_bp.route('/users/delete/<username>', methods=['DELETE'])
@role_required(['admin'])
def delete_user(username):
    """ลบบัญชีผู้ใช้งาน"""
    try:
        if username == session.get('username'):
            return jsonify({"status": "error", "message": "ไม่สามารถลบบัญชีตัวเองได้"}), 400

        users = read_json_file(USERS_FILE)
        new_users = [u for u in users if u['username'] != username]

        if len(new_users) == len(users):
            return jsonify({"status": "error", "message": "ไม่พบผู้ใช้ที่ต้องการลบ"}), 404

        write_json_file(USERS_FILE, new_users)
        log_activity(session.get('username'), "DELETE_USER", f"ลบบัญชีผู้ใช้: {username}")
        return jsonify({"status": "success", "message": "ลบผู้ใช้เรียบร้อยแล้ว"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": f"เกิดข้อผิดพลาด: {str(e)}"}), 500