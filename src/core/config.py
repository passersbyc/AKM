import json
from pathlib import Path

_project_root: Path | None = None
_config_cache: dict | None = None


def invalidate_config() -> None:
    global _config_cache
    _config_cache = None


def get_project_root() -> Path:
    global _project_root
    if _project_root is not None:
        return _project_root
    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / "pyproject.toml").exists() or (current / "config.json").exists():
            _project_root = current
            return current
        current = current.parent
    fallback = Path(__file__).resolve().parent.parent.parent
    _project_root = fallback
    return fallback


def get_data_dir() -> Path:
    return get_project_root() / "data"


def get_config_path() -> Path:
    return get_project_root() / "config.json"


def load_config() -> dict:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    p = get_config_path()
    if p.exists():
        try:
            _config_cache = json.loads(p.read_text(encoding="utf-8"))
            return _config_cache
        except Exception:
            from src.core.logging import get_logger
            get_logger("akm.config").debug("配置文件解析失败", exc_info=True)
    _config_cache = {}
    return _config_cache


def get_library_path() -> Path:
    root = get_project_root()
    cfg = load_config()
    path_str = cfg.get("project_settings", {}).get("library_path")
    if path_str:
        p = Path(path_str)
        return p if p.is_absolute() else (root / p).absolute()
    default_path = root / "library"
    default_path.mkdir(exist_ok=True)
    return default_path





def get_convert_setting() -> bool:
    try:
        cfg = load_config()
        return cfg.get("project_settings", {}).get("convert_traditional", True)
    except Exception:
        return True


def translate_error(message: str) -> str:
    cfg = load_config()
    translations = cfg.get("translations", {})
    translated = message
    for eng, chn in translations.items():
        translated = translated.replace(eng, chn)
    return translated


MANIFEST_FIELDS = [
    "ID", "标题", "作者", "系列", "标签", "来源", "源状态",
    "后缀", "分类", "导入时间", "文件大小(KB)", "MD5", "文件路径",
    "收藏", "评分", "简介", "点赞",
]
