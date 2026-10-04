import json
import os
import shutil
import tempfile
from typing import Any, Dict, List

BASE_DIR = os.path.dirname(__file__)
LOCAL_DATA_DIR = os.path.join(BASE_DIR, 'data')


def get_data_dir() -> str:
    """Return a writable directory for JSON data. On Vercel, use /tmp so the app can write files."""
    env_data_dir = os.environ.get('DATA_DIR')
    if env_data_dir:
        return env_data_dir

    if os.access(BASE_DIR, os.W_OK):
        return LOCAL_DATA_DIR

    return os.path.join(tempfile.gettempdir(), 'inventory_app_data')


def ensure_data_dir() -> str:
    """Guarantee the data directory exists and seed data is available when using a temp folder."""
    data_dir = get_data_dir()
    os.makedirs(data_dir, exist_ok=True)

    if data_dir != LOCAL_DATA_DIR and os.path.isdir(LOCAL_DATA_DIR):
        for filename in os.listdir(LOCAL_DATA_DIR):
            source_path = os.path.join(LOCAL_DATA_DIR, filename)
            target_path = os.path.join(data_dir, filename)
            if os.path.isfile(source_path) and not os.path.exists(target_path):
                shutil.copy2(source_path, target_path)

    return data_dir


def read_json_file(filename: str) -> List[Dict[str, Any]]:
    """Read JSON data from the writable app data directory."""
    data_dir = ensure_data_dir()
    filepath = os.path.join(data_dir, filename)
    try:
        if not os.path.exists(filepath):
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump([], f)
            return []
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def write_json_file(filename: str, data: List[Dict[str, Any]]) -> bool:
    """Write JSON data to the writable app data directory."""
    data_dir = ensure_data_dir()
    filepath = os.path.join(data_dir, filename)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return True
    except IOError:
        return False