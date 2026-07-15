import json
from pathlib import Path

from src.core.config import get_config_path


def determine_file_type(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    if not ext:
        return "unknown"
    ext_key = ext[1:]
    filetype_mapping = {}
    config_path = get_config_path()
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            filetype_mapping = config.get("filetype", {})
        except Exception:
            pass
    return filetype_mapping.get(ext_key, "unknown")
