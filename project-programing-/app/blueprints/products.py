import io
from datetime import datetime

from flask import Blueprint, request, jsonify

from app.database import read_json_file, write_json_file
from app.utils import validate_product_data, role_required, normalize_warehouse_name, ensure_warehouse_stock

products_bp = Blueprint('products', __name__, url_prefix='/api/products')
PRODUCTS_FILE = 'products.json'
STOCK_LOTS_FILE = 'stock_lots.json'
WAREHOUSES_FILE = 'warehouses.json'


def _read_warehouses():
    warehouses = read_json_file(WAREHOUSES_FILE)
    if warehouses:
        return warehouses
    return [
        {'name': 'Main Warehouse', 'code': 'WH-001', 'type': 'main'},
        {'name': 'Branch A', 'code': 'WH-002', 'type': 'branch'},
    ]


def _save_lot_record(sku, warehouse, lot_number, expiration_date, quantity, cost_price=0.0):
    if not sku or not lot_number:
        return
    lot_records = read_json_file(STOCK_LOTS_FILE)
    lot_records.append({
        'sku': str(sku).strip().upper(),
        'warehouse': normalize_warehouse_name(warehouse),
        'lot_number': str(lot_number).strip(),
        'expiration_date': str(expiration_date).strip() if expiration_date else '',
        'quantity': int(quantity),
        'cost_price': float(cost_price or 0),
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })
    write_json_file(STOCK_LOTS_FILE, lot_records)


@products_bp.route('/', methods=['GET'])
def get_products():
    """Search, filter, sort, and paginate products."""
    try:
        search_query = request.args.get('search', '').strip().lower()
        sort_by = request.args.get('sort_by', 'sku')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))

        products = read_json_file(PRODUCTS_FILE)
        filtered_products = []
        for p in products:
            searchable = f"{p.get('name', '')} {p.get('sku', '')} {p.get('category', '')} {p.get('unit', '')}"
            if search_query in searchable.lower():
                filtered_products.append(p)

        if sort_by in ['sku', 'name', 'cost_price', 'sell_price', 'stock', 'category', 'unit']:
            filtered_products.sort(key=lambda x: str(x.get(sort_by, '')).lower())

        total_items = len(filtered_products)
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        paginated_products = filtered_products[start_index:end_index]

        return jsonify({
            'status': 'success',
            'total': total_items,
            'page': page,
            'per_page': per_page,
            'warehouses': _read_warehouses(),
            'data': paginated_products,
        }), 200

    except Exception as e:
        return jsonify({'status': 'error', 'message': f'เกิดข้อผิดพลาดในการดึงข้อมูล: {str(e)}'}), 500


@products_bp.route('/create', methods=['POST'])
@role_required(['admin', 'staff'])
def create_product():
    """Create a new product with validation for category, unit, and warehouse."""
    try:
        data = request.get_json(silent=True) or request.form or {}
        warehouse = normalize_warehouse_name(data.get('warehouse', 'Main Warehouse'))
        sku = str(data.get('sku', ''))
        name = str(data.get('name', ''))
        category = str(data.get('category', ''))
        unit = str(data.get('unit', ''))
        cost_price = data.get('cost_price', '')
        sell_price = data.get('sell_price', '')
        reorder_point = data.get('reorder_point', 0)

        is_valid, msg, cleaned_data = validate_product_data(
            sku,
            name,
            cost_price,
            sell_price,
            reorder_point,
            category,
            unit,
            warehouse,
        )
        if not is_valid:
            return jsonify({'status': 'error', 'message': msg}), 400

        products = read_json_file(PRODUCTS_FILE)
        for existing in products:
            if existing.get('sku') == cleaned_data['sku']:
                return jsonify({'status': 'error', 'message': 'รหัส SKU นี้มีในระบบแล้ว'}), 400

        warehouse_stock = data.get('warehouse_stock')
        if isinstance(warehouse_stock, dict):
            normalized_stock = {}
            for wh_name, value in warehouse_stock.items():
                normalized_stock[normalize_warehouse_name(str(wh_name))] = int(value or 0)
            if not normalized_stock:
                normalized_stock = {warehouse: 0}
        else:
            normalized_stock = {warehouse: int(data.get('stock', 0) or 0)}

        cleaned_data['warehouse'] = warehouse
        cleaned_data['warehouse_stock'] = normalized_stock
        cleaned_data['stock'] = sum(int(v) for v in normalized_stock.values())

        if cleaned_data['stock'] < 0:
            return jsonify({'status': 'error', 'message': 'จำนวนสต็อกเริ่มต้นต้องไม่ติดลบ'}), 400

        # Optional lot creation when receiving stock immediately.
        lot_number = data.get('lot_number')
        expiration_date = data.get('expiration_date')
        if lot_number and cleaned_data['stock'] > 0:
            _save_lot_record(cleaned_data['sku'], warehouse, lot_number, expiration_date, cleaned_data['stock'], cleaned_data['cost_price'])

        products.append(cleaned_data)
        if write_json_file(PRODUCTS_FILE, products):
            return jsonify({'status': 'success', 'message': 'บันทึกข้อมูลสินค้าเรียบร้อย', 'data': cleaned_data}), 201
        return jsonify({'status': 'error', 'message': 'ไม่สามารถบันทึกไฟล์ข้อมูลได้'}), 500

    except Exception as e:
        return jsonify({'status': 'error', 'message': f'เกิดข้อผิดพลาดที่ไม่คาดคิด: {str(e)}'}), 500


@products_bp.route('/update/<sku>', methods=['PUT'])
@role_required(['admin', 'staff'])
def update_product(sku):
    """Update product details including category, unit, and warehouse stock."""
    try:
        data = request.get_json(silent=True) or {}
        warehouse = normalize_warehouse_name(data.get('warehouse', 'Main Warehouse'))
        name = str(data.get('name', ''))
        category = str(data.get('category', ''))
        unit = str(data.get('unit', ''))
        cost_price = data.get('cost_price', '')
        sell_price = data.get('sell_price', '')
        reorder_point = data.get('reorder_point', 0)

        is_valid, msg, cleaned_data = validate_product_data(
            sku,
            name,
            cost_price,
            sell_price,
            reorder_point,
            category,
            unit,
            warehouse,
        )
        if not is_valid:
            return jsonify({'status': 'error', 'message': msg}), 400

        products = read_json_file(PRODUCTS_FILE)
        updated = False
        for p in products:
            if p['sku'] == sku.upper():
                p['name'] = cleaned_data['name']
                p['category'] = cleaned_data['category']
                p['unit'] = cleaned_data['unit']
                p['cost_price'] = cleaned_data['cost_price']
                p['sell_price'] = cleaned_data['sell_price']
                p['reorder_point'] = cleaned_data['reorder_point']
                p['warehouse'] = cleaned_data['warehouse']

                warehouse_stock = data.get('warehouse_stock')
                if isinstance(warehouse_stock, dict):
                    normalized_stock = {}
                    for wh_name, value in warehouse_stock.items():
                        normalized_stock[normalize_warehouse_name(str(wh_name))] = int(value or 0)
                    p['warehouse_stock'] = normalized_stock
                else:
                    p['warehouse_stock'] = ensure_warehouse_stock(p, warehouse)
                    p['warehouse_stock'][warehouse] = int(data.get('stock', p.get('stock', 0)) or 0)

                p['stock'] = sum(int(v) for v in p.get('warehouse_stock', {}).values())
                updated = True
                break

        if not updated:
            return jsonify({'status': 'error', 'message': 'ไม่พบสินค้ารหัสนี้ในระบบ'}), 404

        write_json_file(PRODUCTS_FILE, products)
        return jsonify({'status': 'success', 'message': 'อัปเดตข้อมูลสินค้าสำเร็จ'}), 200

    except Exception as e:
        return jsonify({'status': 'error', 'message': 'ไม่สามารถแก้ไขข้อมูลสินค้าได้'}), 500


@products_bp.route('/delete/<sku>', methods=['DELETE'])
@role_required(['admin'])
def delete_product(sku):
    """Delete a product by SKU."""
    try:
        products = read_json_file(PRODUCTS_FILE)
        new_products = [p for p in products if p['sku'] != sku.upper()]

        if len(new_products) == len(products):
            return jsonify({'status': 'error', 'message': 'ไม่พบรหัสสินค้าที่ต้องการลบ'}), 404

        write_json_file(PRODUCTS_FILE, new_products)
        return jsonify({'status': 'success', 'message': 'ลบสินค้าเรียบร้อยแล้ว'}), 200

    except Exception as e:
        return jsonify({'status': 'error', 'message': 'เกิดข้อผิดพลาดในการลบข้อมูล'}), 500


@products_bp.route('/import', methods=['POST'])
@role_required(['admin', 'staff'])
def import_products():
    """Bulk import products from CSV or Excel file."""
    try:
        uploaded = request.files.get('file')
        if not uploaded:
            return jsonify({'status': 'error', 'message': 'กรุณาแนบไฟล์ CSV หรือ Excel ก่อนอัปโหลด'}), 400

        filename = (uploaded.filename or '').lower()
        file_bytes = uploaded.read()
        if not file_bytes:
            return jsonify({'status': 'error', 'message': 'ไฟล์ที่อัปโหลดว่างเปล่า'}), 400

        try:
            import pandas as pd
        except ModuleNotFoundError:
            return jsonify({'status': 'error', 'message': 'กรุณาติดตั้ง pandas หรือ openpyxl ก่อนใช้งานฟีเจอร์ Import Excel'}), 500

        buffer = io.BytesIO(file_bytes)
        if filename.endswith('.csv'):
            df = pd.read_csv(buffer)
        elif filename.endswith('.xlsx') or filename.endswith('.xls'):
            df = pd.read_excel(buffer)
        else:
            return jsonify({'status': 'error', 'message': 'รองรับเฉพาะไฟล์ CSV หรือ Excel (.xlsx)'}), 400

        required_cols = {'sku', 'name', 'category', 'unit', 'cost_price', 'sell_price', 'reorder_point', 'stock'}
        missing = required_cols.difference(set(map(str, df.columns)))
        if missing:
            return jsonify({'status': 'error', 'message': f'คอลัมน์ที่ขาด: {sorted(missing)}'}), 400

        products = read_json_file(PRODUCTS_FILE)
        product_map = {p['sku'].upper(): p for p in products}

        imported_count = 0
        for _, row in df.iterrows():
            sku = str(row.get('sku', '')).strip().upper()
            if not sku:
                continue

            payload = {
                'sku': sku,
                'name': str(row.get('name', '')),
                'category': str(row.get('category', '')),
                'unit': str(row.get('unit', 'Pcs')),
                'cost_price': row.get('cost_price', 0),
                'sell_price': row.get('sell_price', 0),
                'reorder_point': int(row.get('reorder_point', 0) or 0),
                'stock': int(row.get('stock', 0) or 0),
                'warehouse': 'Main Warehouse',
                'warehouse_stock': {'Main Warehouse': int(row.get('stock', 0) or 0)},
            }
            is_valid, msg, cleaned_data = validate_product_data(
                payload['sku'],
                payload['name'],
                payload['cost_price'],
                payload['sell_price'],
                payload['reorder_point'],
                payload['category'],
                payload['unit'],
                payload['warehouse'],
            )
            if not is_valid:
                continue

            cleaned_data['stock'] = int(payload['stock'])
            cleaned_data['warehouse'] = payload['warehouse']
            cleaned_data['warehouse_stock'] = payload['warehouse_stock']
            if sku in product_map:
                existing = product_map[sku]
                existing.update(cleaned_data)
            else:
                product_map[sku] = cleaned_data
                imported_count += 1

        updated_products = list(product_map.values())
        write_json_file(PRODUCTS_FILE, updated_products)
        return jsonify({'status': 'success', 'message': f'อัปโหลดสินค้าเรียบร้อย {len(updated_products)} รายการ', 'count': len(updated_products)}), 200

    except Exception as e:
        return jsonify({'status': 'error', 'message': f'เกิดข้อผิดพลาดในการอัปโหลดไฟล์: {str(e)}'}), 500
