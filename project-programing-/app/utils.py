from functools import wraps
from flask import session, jsonify
from typing import Tuple, Dict, Any


DEFAULT_WAREHOUSES = [
    "Main Warehouse",
    "Branch A",
]


def normalize_warehouse_name(value: str) -> str:
    warehouse = (value or "").strip()
    if not warehouse:
        return "Main Warehouse"
    return warehouse


def ensure_warehouse_stock(product: Dict[str, Any], warehouse: str = "Main Warehouse") -> Dict[str, int]:
    product.setdefault("warehouse_stock", {})
    warehouse = normalize_warehouse_name(warehouse)
    current_stock = int(product.get("stock", 0) or 0)
    if not product["warehouse_stock"]:
        product["warehouse_stock"] = {warehouse: current_stock}
    product["warehouse_stock"].setdefault(warehouse, current_stock)
    product["stock"] = sum(int(v) for v in product["warehouse_stock"].values())
    return product["warehouse_stock"]


def get_stock_for_warehouse(product: Dict[str, Any], warehouse: str = "Main Warehouse") -> int:
    ensure_warehouse_stock(product, warehouse)
    warehouse = normalize_warehouse_name(warehouse)
    return int(product.get("warehouse_stock", {}).get(warehouse, product.get("stock", 0) or 0))


def compute_weighted_average_cost(current_stock: float, current_average_cost: float, incoming_qty: float, incoming_unit_cost: float) -> float:
    if incoming_qty <= 0:
        return float(current_average_cost or 0)
    total_cost = (float(current_stock) * float(current_average_cost or 0)) + (float(incoming_qty) * float(incoming_unit_cost or 0))
    total_qty = float(current_stock) + float(incoming_qty)
    if total_qty <= 0:
        return 0.0
    return round(total_cost / total_qty, 2)


def validate_product_data(
    sku: str,
    name: str,
    cost_price_str: str,
    sell_price_str: str,
    reorder_point_str: str,
    category_str: str,
    unit_str: str,
    warehouse_str: str = "Main Warehouse",
) -> Tuple[bool, str, dict]:
    if not isinstance(sku, str) or not sku.strip():
        return False, "กรุณากรอกรหัส SKU สินค้า", {}
    if not isinstance(name, str) or not name.strip():
        return False, "กรุณากรอกชื่อสินค้า", {}
    if not isinstance(category_str, str) or not category_str.strip():
        return False, "กรุณากรอกหมวดหมู่สินค้า", {}
    if not isinstance(unit_str, str) or not unit_str.strip():
        return False, "กรุณากรอกหน่วยสินค้า (เช่น Pcs, Box, Pack)", {}

    try:
        cost_price = float(cost_price_str)
        sell_price = float(sell_price_str)
    except (ValueError, TypeError):
        return False, "ราคาทุนและราคาขายต้องเป็นตัวเลขเท่านั้น", {}

    try:
        reorder_point = int(reorder_point_str)
    except (ValueError, TypeError):
        return False, "จุดสั่งซื้อต้องเป็นจำนวนเต็มเท่านั้น", {}

    if cost_price < 0 or sell_price < 0:
        return False, "ราคาต้องไม่เป็นค่าติดลบ", {}
    if reorder_point < 0:
        return False, "จุดสั่งซื้อต้องไม่เป็นค่าติดลบ", {}
    if cost_price > sell_price and not (cost_price == 0 and sell_price == 0):
        return False, "ราคาทุนไม่ควรสูงกว่าราคาขาย", {}

    unit_map = {
        'pcs': 'Pcs',
        'box': 'Box',
        'pack': 'Pack',
        'set': 'Set',
        'bottle': 'Bottle',
        'kg': 'Kg',
        'liter': 'Liter',
    }
    normalized_unit = unit_map.get(unit_str.strip().lower(), unit_str.strip())

    cleaned_data = {
        "sku": sku.strip().upper(),
        "name": name.strip(),
        "category": category_str.strip(),
        "unit": normalized_unit,
        "cost_price": cost_price,
        "sell_price": sell_price,
        "reorder_point": reorder_point,
        "warehouse": normalize_warehouse_name(warehouse_str),
    }
    return True, "ข้อมูลถูกต้อง", cleaned_data


def role_required(allowed_roles: list):
    """Decorator to enforce role-based access control."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                user_role = session.get('user_role') or (session.get('user') or {}).get('role')
                if not user_role:
                    return jsonify({"status": "error", "message": "Unauthorized: กรุณาเข้าสู่ระบบก่อนทำรายการ"}), 401
                if allowed_roles and 'all' not in allowed_roles and user_role not in allowed_roles:
                    return jsonify({"status": "error", "message": "Forbidden: คุณไม่มีสิทธิ์เข้าถึงหน้านี้"}), 403
            except Exception:
                return jsonify({"status": "error", "message": "Unauthorized"}), 401
            return f(*args, **kwargs)
        return decorated_function
    return decorator