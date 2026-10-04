from flask import Blueprint, request, jsonify, session
from app.database import read_json_file, write_json_file
from app.utils import role_required
from datetime import datetime

suppliers_bp = Blueprint('suppliers', __name__, url_prefix='/api/suppliers')
SUPPLIERS_FILE = 'suppliers.json'
PO_FILE = 'purchase_orders.json'
PRODUCTS_FILE = 'products.json'

# --- Supplier Management ---
@suppliers_bp.route('/', methods=['GET'])
def get_suppliers():
    """ดึงรายชื่อผู้ขายทั้งหมด"""
    try:
        suppliers = read_json_file(SUPPLIERS_FILE)
        return jsonify({"status": "success", "data": suppliers}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": "เกิดข้อผิดพลาดในการอ่านข้อมูลผู้ขาย"}), 500

@suppliers_bp.route('/add', methods=['POST'])
@role_required(['admin', 'staff'])
def add_supplier():
    """เพิ่มข้อมูลผู้ขาย (Supplier)"""
    try:
        data = request.get_json() or {}
        code = str(data.get('code', '')).strip().upper()
        name = str(data.get('name', '')).strip()
        contact = str(data.get('contact', '')).strip()

        if not code or not name:
            return jsonify({"status": "error", "message": "กรุณาระบุรหัสผู้ขายและชื่อผู้ขาย"}), 400

        suppliers = read_json_file(SUPPLIERS_FILE)
        for s in suppliers:
            if s['code'] == code:
                return jsonify({"status": "error", "message": "รหัสผู้ขายนี้มีในระบบแล้ว"}), 400

        new_supplier = {"code": code, "name": name, "contact": contact}
        suppliers.append(new_supplier)
        write_json_file(SUPPLIERS_FILE, suppliers)

        return jsonify({"status": "success", "message": "เพิ่มข้อมูลผู้ขายเรียบร้อย", "data": new_supplier}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": "ไม่สามารถเพิ่มข้อมูลผู้ขายได้"}), 500

# --- Purchase Order (PO) Management ---
@suppliers_bp.route('/po/create', methods=['POST'])
@role_required(['admin', 'staff'])
def create_po():
    """สร้างใบสั่งซื้อ (Purchase Order)"""
    try:
        data = request.get_json() or {}
        po_number = f"PO-{int(datetime.now().timestamp())}"
        supplier_code = str(data.get('supplier_code', '')).strip()
        items = data.get('items', []) # List of dicts: [{"sku": "SKU01", "qty": 10, "unit_price": 50}]

        if not supplier_code or not isinstance(items, list) or len(items) == 0:
            return jsonify({"status": "error", "message": "ข้อมูลใบสั่งซื้อไม่ถูกต้อง"}), 400

        total_amount = 0.0
        for item in items:
            total_amount += float(item.get('qty', 0)) * float(item.get('unit_price', 0))

        po_data = {
            "po_number": po_number,
            "supplier_code": supplier_code,
            "items": items,
            "total_amount": total_amount,
            "status": "PENDING", # PENDING, RECEIVED, CANCELLED
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        pos = read_json_file(PO_FILE)
        pos.append(po_data)
        write_json_file(PO_FILE, pos)

        return jsonify({"status": "success", "message": "สร้างใบสั่งซื้อสำเร็จ", "po_number": po_number}), 201

    except Exception as e:
        return jsonify({"status": "error", "message": f"เกิดข้อผิดพลาดในการสร้าง PO: {str(e)}"}), 500

@suppliers_bp.route('/po/receive/<po_number>', methods=['POST'])
@role_required(['admin', 'staff'])
def receive_po(po_number):
    """อัปเดตสถานะ PO และรับสินค้าเข้าสต็อกอัตโนมัติ"""
    try:
        pos = read_json_file(PO_FILE)
        target_po = None

        for po in pos:
            if po['po_number'] == po_number:
                target_po = po
                break

        if not target_po:
            return jsonify({"status": "error", "message": "ไม่พบใบสั่งซื้อนี้"}), 404

        if target_po['status'] == "RECEIVED":
            return jsonify({"status": "error", "message": "ใบสั่งซื้อนี้รับสินค้าเข้าสต็อกไปแล้ว"}), 400

        # อัปเดตสต็อกสินค้า
        products = read_json_file(PRODUCTS_FILE)
        for item in target_po['items']:
            sku = item['sku']
            qty = int(item['qty'])
            for p in products:
                if p['sku'] == sku:
                    p['stock'] = p.get('stock', 0) + qty
                    break

        target_po['status'] = "RECEIVED"
        target_po['received_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        write_json_file(PRODUCTS_FILE, products)
        write_json_file(PO_FILE, pos)

        return jsonify({"status": "success", "message": f"รับสินค้าตามใบสั่งซื้อ {po_number} เข้าสต็อกเรียบร้อยแล้ว"}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": "เกิดข้อผิดพลาดในการรับสินค้าเข้าสต็อก"}), 500