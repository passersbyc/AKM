import json
from pathlib import Path

from src.core.config import get_config_path

# 内置默认文件类型映射（config.json 缺 filetype 节时的兜底，
# 避免配置不完整导致「无法识别的文件类型」）。
DEFAULT_FILETYPE_MAP = {
    "txt": "小说", "epub": "小说", "mobi": "小说", "azw3": "小说",
    "docx": "小说", "doc": "小说",
    "jpg": "图片", "jpeg": "图片", "png": "图片", "gif": "图片",
    "webp": "图片", "bmp": "图片",
    "pdf": "漫画", "cbz": "漫画",
    "mp4": "电影", "avi": "电影", "mkv": "电影",
    "mp3": "音乐", "flac": "音乐", "wav": "音乐", "m4a": "音乐",
    "aac": "音乐", "ogg": "音乐", "wma": "音乐", "opus": "音乐",
}


def determine_file_type(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    if not ext:
        return "unknown"
    ext_key = ext[1:]
    filetype_mapping = dict(DEFAULT_FILETYPE_MAP)
    config_path = get_config_path()
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            # config.json 的 filetype 节覆盖默认映射（支持自定义）
            filetype_mapping.update(config.get("filetype", {}))
        except Exception:
            pass
    return filetype_mapping.get(ext_key, "unknown")
