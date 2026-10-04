from datetime import datetime

from flask import Blueprint, request, jsonify, session

from app.database import read_json_file, write_json_file
from app.utils import role_required, normalize_warehouse_name, ensure_warehouse_stock, get_stock_for_warehouse

stock_bp = Blueprint('stock', __name__, url_prefix='/api/stock')
PRODUCTS_FILE = 'products.json'
STOCK_CARDS_FILE = 'stock_cards.json'
WAREHOUSES_FILE = 'warehouses.json'
STOCK_LOTS_FILE = 'stock_lots.json'
STOCK_COUNTS_FILE = 'stock_counts.json'


def _read_warehouses():
    warehouses = read_json_file(WAREHOUSES_FILE)
    if warehouses:
        return warehouses
    return [
        {'name': 'Main Warehouse', 'code': 'WH-001', 'type': 'main'},
        {'name': 'Branch A', 'code': 'WH-002', 'type': 'branch'},
    ]


def _consume_lots_by_fefo(sku, warehouse, quantity):
    lots = read_json_file(STOCK_LOTS_FILE)
    matching = [
        lot for lot in lots
        if str(lot.get('sku', '')).upper() == str(sku).upper() and normalize_warehouse_name(lot.get('warehouse')) == normalize_warehouse_name(warehouse)
    ]
    matching.sort(key=lambda lot: (lot.get('expiration_date') or '9999-12-31', lot.get('created_at') or ''))
    remaining = int(quantity)
    consumed = 0
    for lot in matching:
        if remaining <= 0:
            break
        current_qty = int(lot.get('quantity', 0) or 0)
        if current_qty <= 0:
            continue
        take = min(remaining, current_qty)
        lot['quantity'] = current_qty - take
        consumed += take
        remaining -= take
    for lot in matching:
        if int(lot.get('quantity', 0) or 0) <= 0:
            lot['quantity'] = 0
    write_json_file(STOCK_LOTS_FILE, lots)
    return consumed


@stock_bp.route('/warehouses', methods=['GET'])
def get_warehouses():
    return jsonify({'status': 'success', 'data': _read_warehouses()}), 200


@stock_bp.route('/adjust', methods=['POST'])
@role_required(['admin', 'staff'])
def adjust_stock():
    """Receive, issue, or adjust stock with FEFO lot allocation support."""
    try:
        data = request.get_json(silent=True) or request.form or {}
        sku = str(data.get('sku', '')).strip().upper()
        action_type = str(data.get('type', '')).lower()
        quantity = int(data.get('quantity', 0) or 0)
        reason = str(data.get('reason', '')).strip()
        warehouse = normalize_warehouse_name(data.get('warehouse', 'Main Warehouse'))
        lot_number = str(data.get('lot_number', '')).strip()
        expiration_date = str(data.get('expiration_date', '')).strip()
        user_name = str(data.get('user', '')).strip() or session.get('username', 'system')

        if action_type not in ['in', 'out', 'adjust']:
            return jsonify({'status': 'error', 'message': 'ประเภทรายการไม่ถูกต้อง (in/out/adjust)'}), 400
        if quantity <= 0 and action_type in ['in', 'out']:
            return jsonify({'status': 'error', 'message': 'จำนวนต้องมากกว่า 0'}), 400
        if not reason:
            return jsonify({'status': 'error', 'message': 'กรุณาระบุเหตุผลการทำรายการ'}), 400

        products = read_json_file(PRODUCTS_FILE)
        product = None
        for p in products:
            if p['sku'] == sku:
                product = p
                break

        if not product:
            return jsonify({'status': 'error', 'message': 'ไม่พบสินค้ารหัสนี้'}), 404

        ensure_warehouse_stock(product, warehouse)
        old_stock = get_stock_for_warehouse(product, warehouse)
        warehouse_stock = product.setdefault('warehouse_stock', {})
        new_stock = old_stock

        if action_type == 'in':
            new_stock = old_stock + quantity
            warehouse_stock[warehouse] = new_stock
            if lot_number:
                lots = read_json_file(STOCK_LOTS_FILE)
                lot_exists = False
                for lot in lots:
                    if str(lot.get('sku', '')).upper() == sku and normalize_warehouse_name(lot.get('warehouse')) == warehouse and str(lot.get('lot_number', '')).strip() == lot_number:
                        lot['quantity'] = int(lot.get('quantity', 0) or 0) + quantity
                        lot['expiration_date'] = expiration_date or lot.get('expiration_date', '')
                        lot['cost_price'] = float(lot.get('cost_price', product.get('cost_price', 0)) or product.get('cost_price', 0))
                        lot_exists = True
                        break
                if not lot_exists:
                    lots.append({
                        'sku': sku,
                        'warehouse': warehouse,
                        'lot_number': lot_number,
                        'expiration_date': expiration_date,
                        'quantity': quantity,
                        'cost_price': float(product.get('cost_price', 0) or 0),
                        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    })
                write_json_file(STOCK_LOTS_FILE, lots)

        elif action_type == 'out':
            lots = read_json_file(STOCK_LOTS_FILE)
            lot_match = False
            if any(str(item.get('sku', '')).upper() == sku and normalize_warehouse_name(item.get('warehouse')) == warehouse for item in lots):
                lot_match = True
                lot_consumed = _consume_lots_by_fefo(sku, warehouse, quantity)
                remaining = quantity - lot_consumed
                if remaining > 0:
                    if old_stock < remaining:
                        return jsonify({'status': 'error', 'message': 'สินค้าในสต็อกมีไม่พอสำหรับเบิกออก'}), 400
                    new_stock = old_stock - remaining
                else:
                    new_stock = old_stock
            else:
                if old_stock < quantity:
                    return jsonify({'status': 'error', 'message': 'สินค้าในสต็อกมีไม่พอสำหรับเบิกออก'}), 400
                new_stock = old_stock - quantity
            warehouse_stock[warehouse] = new_stock

        elif action_type == 'adjust':
            if quantity < 0:
                return jsonify({'status': 'error', 'message': 'จำนวนปรับยอดต้องไม่ติดลบ'}), 400
            new_stock = quantity
            warehouse_stock[warehouse] = new_stock

        product['stock'] = sum(int(v) for v in product.get('warehouse_stock', {}).values())
        write_json_file(PRODUCTS_FILE, products)

        cards = read_json_file(STOCK_CARDS_FILE)
        cards.append({
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'sku': sku,
            'warehouse': warehouse,
            'type': action_type,
            'change': new_stock - old_stock,
            'before': old_stock,
            'after': new_stock,
            'reason': reason,
            'user': user_name,
            'lot_number': lot_number,
            'expiration_date': expiration_date,
        })
        write_json_file(STOCK_CARDS_FILE, cards)

        return jsonify({
            'status': 'success',
            'message': 'ปรับยอดสต็อกสำเร็จ',
            'sku': sku,
            'warehouse': warehouse,
            'old_stock': old_stock,
            'new_stock': new_stock,
        }), 200

    except ValueError:
        return jsonify({'status': 'error', 'message': 'จำนวนสินค้าต้องเป็นตัวเลขจำนวนเต็ม'}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'เกิดข้อผิดพลาด: {str(e)}'}), 500


@stock_bp.route('/transfer', methods=['POST'])
@role_required(['admin', 'staff'])
def transfer_stock():
    """Transfer stock between warehouses."""
    try:
        data = request.get_json(silent=True) or request.form or {}
        sku = str(data.get('sku', '')).strip().upper()
        source = normalize_warehouse_name(data.get('source_warehouse', 'Main Warehouse'))
        destination = normalize_warehouse_name(data.get('destination_warehouse', 'Branch A'))
        quantity = int(data.get('quantity', 0) or 0)
        reason = str(data.get('reason', '')).strip() or 'Inter-warehouse transfer'
        user_name = str(data.get('user', '')).strip() or session.get('username', 'system')

        if not sku:
            return jsonify({'status': 'error', 'message': 'กรุณาระบุ SKU'}), 400
        if source == destination:
            return jsonify({'status': 'error', 'message': 'คลังต้นทางและปลายทางต้องไม่เท่ากัน'}), 400
        if quantity <= 0:
            return jsonify({'status': 'error', 'message': 'จำนวนการโอนต้องมากกว่า 0'}), 400

        products = read_json_file(PRODUCTS_FILE)
        product = None
        for p in products:
            if p['sku'] == sku:
                product = p
                break
        if not product:
            return jsonify({'status': 'error', 'message': 'ไม่พบสินค้ารหัสนี้'}), 404

        warehouse_stock = ensure_warehouse_stock(product, source)
        source_qty = int(warehouse_stock.get(source, 0) or 0)
        if source_qty < quantity:
            return jsonify({'status': 'error', 'message': f'สินค้าใน {source} ไม่พอสำหรับโอน {quantity} ชิ้น'}), 400

        warehouse_stock[source] = source_qty - quantity
        warehouse_stock[destination] = int(warehouse_stock.get(destination, 0) or 0) + quantity
        product['stock'] = sum(int(v) for v in warehouse_stock.values())
        write_json_file(PRODUCTS_FILE, products)

        cards = read_json_file(STOCK_CARDS_FILE)
        cards.append({
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'sku': sku,
            'warehouse': source,
            'type': 'transfer',
            'source': source,
            'destination': destination,
            'change': -quantity,
            'before': source_qty,
            'after': source_qty - quantity,
            'reason': reason,
            'user': user_name,
        })
        cards.append({
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'sku': sku,
            'warehouse': destination,
            'type': 'transfer',
            'source': source,
            'destination': destination,
            'change': quantity,
            'before': int(warehouse_stock.get(destination, 0) or 0) - quantity,
            'after': int(warehouse_stock.get(destination, 0) or 0),
            'reason': reason,
            'user': user_name,
        })
        write_json_file(STOCK_CARDS_FILE, cards)

        return jsonify({
            'status': 'success',
            'message': 'โอนย้ายสินค้าระหว่างคลังสำเร็จ',
            'sku': sku,
            'source_warehouse': source,
            'destination_warehouse': destination,
            'quantity': quantity,
            'remaining_source': source_qty - quantity,
            'destination_stock': int(warehouse_stock.get(destination, 0) or 0),
        }), 200

    except ValueError:
        return jsonify({'status': 'error', 'message': 'จำนวนต้องเป็นตัวเลขจำนวนเต็ม'}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'เกิดข้อผิดพลาดในการโอนย้ายคลัง: {str(e)}'}), 500


@stock_bp.route('/reconcile', methods=['POST'])
@role_required(['admin', 'staff'])
def reconcile_stock():
    """Stock count reconciliation and variance adjustment."""
    try:
        data = request.get_json(silent=True) or request.form or {}
        sku = str(data.get('sku', '')).strip().upper()
        warehouse = normalize_warehouse_name(data.get('warehouse', 'Main Warehouse'))
        physical_quantity = int(data.get('physical_quantity', 0) or 0)
        system_quantity = int(data.get('system_quantity', 0) or 0)
        variance = physical_quantity - system_quantity
        reason = str(data.get('reason', 'Stock count reconciliation')).strip() or 'Stock count reconciliation'
        user_name = str(data.get('user', '')).strip() or session.get('username', 'system')

        if not sku:
            return jsonify({'status': 'error', 'message': 'กรุณาระบุ SKU'}), 400

        products = read_json_file(PRODUCTS_FILE)
        product = None
        for p in products:
            if p['sku'] == sku:
                product = p
                break
        if not product:
            return jsonify({'status': 'error', 'message': 'ไม่พบสินค้ารหัสนี้'}), 404

        warehouse_stock = ensure_warehouse_stock(product, warehouse)
        warehouse_stock[warehouse] = physical_quantity
        product['stock'] = sum(int(v) for v in warehouse_stock.values())
        write_json_file(PRODUCTS_FILE, products)

        reconciliations = read_json_file(STOCK_COUNTS_FILE)
        reconciliations.append({
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'sku': sku,
            'warehouse': warehouse,
            'system_quantity': system_quantity,
            'physical_quantity': physical_quantity,
            'variance': variance,
            'reason': reason,
            'user': user_name,
        })
        write_json_file(STOCK_COUNTS_FILE, reconciliations)

        cards = read_json_file(STOCK_CARDS_FILE)
        cards.append({
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'sku': sku,
            'warehouse': warehouse,
            'type': 'reconcile',
            'change': variance,
            'before': system_quantity,
            'after': physical_quantity,
            'reason': reason,
            'user': user_name,
        })
        write_json_file(STOCK_CARDS_FILE, cards)

        return jsonify({
            'status': 'success',
            'message': 'ปรับยอดตามการนับสต็อกเรียบร้อย',
            'sku': sku,
            'warehouse': warehouse,
            'system_quantity': system_quantity,
            'physical_quantity': physical_quantity,
            'variance': variance,
        }), 200

    except ValueError:
        return jsonify({'status': 'error', 'message': 'จำนวนต้องเป็นตัวเลขจำนวนเต็ม'}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'เกิดข้อผิดพลาดในการ reconcile: {str(e)}'}), 500


@stock_bp.route('/lots/<sku>', methods=['GET'])
def get_lot_history(sku):
    try:
        lots = read_json_file(STOCK_LOTS_FILE)
        filtered = [lot for lot in lots if str(lot.get('sku', '')).upper() == str(sku).upper()]
        return jsonify({'status': 'success', 'sku': str(sku).upper(), 'data': filtered}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'ไม่สามารถดึงข้อมูล lot ได้: {str(e)}'}), 500


@stock_bp.route('/card/<sku>', methods=['GET'])
def get_stock_card(sku):
    """ดึงประวัติความเคลื่อนไหว (Stock Card) ของสินค้า"""
    try:
        cards = read_json_file(STOCK_CARDS_FILE)
        product_cards = [c for c in cards if c['sku'] == sku.upper()]
        return jsonify({'status': 'success', 'sku': sku.upper(), 'data': product_cards}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': 'ไม่สามารถดึงประวัติสต็อกได้'}), 500


@stock_bp.route('/alerts', methods=['GET'])
def get_low_stock_alerts():
    """ระบบแจ้งเตือนเมื่อสินค้าต่ำกว่าจุดสั่งซื้อ (Reorder Point)"""
    try:
        products = read_json_file(PRODUCTS_FILE)
        low_stock_items = []

        for p in products:
            if int(p.get('stock', 0) or 0) <= int(p.get('reorder_point', 0) or 0):
                low_stock_items.append({
                    'sku': p['sku'],
                    'name': p['name'],
                    'current_stock': int(p.get('stock', 0) or 0),
                    'reorder_point': int(p.get('reorder_point', 0) or 0),
                    'status': 'CRITICAL' if int(p.get('stock', 0) or 0) == 0 else 'WARNING',
                })

        return jsonify({
            'status': 'success',
            'count': len(low_stock_items),
            'alerts': low_stock_items,
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': 'เกิดข้อผิดพลาดในการตรวจสอบแจ้งเตือน'}), 500
