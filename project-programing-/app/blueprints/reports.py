import csv
import io
from datetime import datetime

from flask import Blueprint, jsonify, request, Response

from app.database import read_json_file
from app.utils import compute_weighted_average_cost

reports_bp = Blueprint('reports', __name__, url_prefix='/api/reports')
PRODUCTS_FILE = 'products.json'
STOCK_CARDS_FILE = 'stock_cards.json'


@reports_bp.route('/inventory-summary', methods=['GET'])
def get_inventory_summary():
    """Generate a comprehensive inventory report including valuation and warehouse view."""
    try:
        products = read_json_file(PRODUCTS_FILE)
        total_items_count = len(products)
        total_units = 0
        total_cost_value = 0.0
        total_sell_value = 0.0
        warehouse_breakdown = {}

        for p in products:
            stock = int(p.get('stock', 0) or 0)
            cost = float(p.get('cost_price', 0.0) or 0.0)
            sell = float(p.get('sell_price', 0.0) or 0.0)
            total_units += stock
            total_cost_value += stock * cost
            total_sell_value += stock * sell

            warehouse_stock = p.get('warehouse_stock', {})
            if warehouse_stock:
                for warehouse_name, qty in warehouse_stock.items():
                    warehouse_breakdown.setdefault(warehouse_name, 0)
                    warehouse_breakdown[warehouse_name] += int(qty or 0)
            else:
                warehouse_breakdown.setdefault('Main Warehouse', 0)
                warehouse_breakdown['Main Warehouse'] += stock

        forecast = []
        stock_cards = read_json_file(STOCK_CARDS_FILE)
        for p in products:
            sku = p.get('sku')
            history = [card for card in stock_cards if str(card.get('sku', '')).upper() == str(sku).upper()]
            if not history:
                avg_daily_demand = 0
            else:
                changes = []
                for card in history:
                    change = int(card.get('change', 0) or 0)
                    if change < 0:
                        changes.append(abs(change))
                    elif change > 0 and card.get('type') in ('in', 'reconcile'):
                        changes.append(change)
                avg_daily_demand = sum(changes) / max(len(changes), 1)

            reorder_point = int(p.get('reorder_point', 0) or 0)
            forecast.append({
                'sku': sku,
                'name': p.get('name'),
                'average_daily_demand': round(avg_daily_demand, 2),
                'projected_7_day_need': int(max(0, avg_daily_demand * 7)),
                'recommended_reorder': max(reorder_point, int(max(0, avg_daily_demand * 7))),
            })

        expected_profit = total_sell_value - total_cost_value
        summary = {
            'total_product_skus': total_items_count,
            'total_units_in_stock': total_units,
            'total_cost_value': round(total_cost_value, 2),
            'total_potential_sell_value': round(total_sell_value, 2),
            'expected_profit': round(expected_profit, 2),
            'warehouse_breakdown': warehouse_breakdown,
            'weighted_average_cost': round(total_cost_value / total_units, 2) if total_units else 0,
        }

        return jsonify({'status': 'success', 'summary': summary, 'forecast': forecast}), 200

    except Exception as e:
        return jsonify({'status': 'error', 'message': f'เกิดข้อผิดพลาดในการสร้างรายงาน: {str(e)}'}), 500


@reports_bp.route('/forecast', methods=['GET'])
def get_forecast():
    try:
        products = read_json_file(PRODUCTS_FILE)
        stock_cards = read_json_file(STOCK_CARDS_FILE)
        forecast = []
        for p in products:
            sku = p.get('sku')
            history = [card for card in stock_cards if str(card.get('sku', '')).upper() == str(sku).upper()]
            daily_out = [abs(int(card.get('change', 0) or 0)) for card in history if int(card.get('change', 0) or 0) < 0]
            avg_out = sum(daily_out) / len(daily_out) if daily_out else 0
            projected = max(int(p.get('reorder_point', 0) or 0), int(avg_out * 7))
            forecast.append({
                'sku': sku,
                'name': p.get('name'),
                'avg_daily_issue': round(avg_out, 2),
                'projected_7_day_need': projected,
                'recommended_reorder_qty': projected,
            })
        return jsonify({'status': 'success', 'forecast': forecast}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'เกิดข้อผิดพลาดในการคาดการณ์ความต้องการ: {str(e)}'}), 500


@reports_bp.route('/export-stock', methods=['GET'])
def export_stock_report():
    try:
        products = read_json_file(PRODUCTS_FILE)
        export_format = request.args.get('format', 'csv').lower()
        rows = []
        for p in products:
            rows.append({
                'sku': p.get('sku', ''),
                'name': p.get('name', ''),
                'category': p.get('category', ''),
                'unit': p.get('unit', ''),
                'warehouse': p.get('warehouse', 'Main Warehouse'),
                'stock': p.get('stock', 0),
                'reorder_point': p.get('reorder_point', 0),
                'cost_price': p.get('cost_price', 0),
                'sell_price': p.get('sell_price', 0),
                'weighted_average_cost': p.get('weighted_average_cost', p.get('cost_price', 0)),
            })

        if export_format == 'xlsx':
            try:
                import pandas as pd
            except ModuleNotFoundError:
                return jsonify({'status': 'error', 'message': 'ต้องติดตั้ง pandas สำหรับ export ไฟล์ Excel'}), 500
            df = pd.DataFrame(rows)
            buffer = io.BytesIO()
            df.to_excel(buffer, index=False)
            buffer.seek(0)
            return Response(
                buffer.getvalue(),
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                headers={'Content-Disposition': 'attachment; filename=inventory_stock_report.xlsx'},
            )

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=['sku', 'name', 'category', 'unit', 'warehouse', 'stock', 'reorder_point', 'cost_price', 'sell_price', 'weighted_average_cost'])
        writer.writeheader()
        writer.writerows(rows)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=inventory_stock_report.csv'},
        )

    except Exception as e:
        return jsonify({'status': 'error', 'message': f'เกิดข้อผิดพลาดในการ export: {str(e)}'}), 500
