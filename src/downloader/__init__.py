import re
import importlib
from pathlib import Path
from typing import Optional

from src.downloader.base import BaseDownloader


class DownloaderRegistry:
    """
    下载器注册中心，自动发现 src/cli/downplugin/ 下的下载器类，
    支持按 URL 模式匹配或按 name 显式调用。
    """

    _entries: dict[str, type[BaseDownloader]] = {}
    _patterns: list[tuple[re.Pattern, str]] = []

    @classmethod
    def register(cls, downloader_cls: type[BaseDownloader]) -> None:
        name = downloader_cls.name
        if not name:
            return
        cls._entries[name] = downloader_cls
        for p in downloader_cls.url_patterns:
            cls._patterns.append((re.compile(p), name))

    @classmethod
    def resolve(cls, url: str, site: Optional[str] = None) -> Optional[type[BaseDownloader]]:
        if site:
            return cls._entries.get(site)
        for pattern, name in cls._patterns:
            if pattern.search(url):
                return cls._entries.get(name)
        return None

    @classmethod
    def list_sites(cls) -> list[str]:
        return list(cls._entries.keys())


def _auto_discover() -> DownloaderRegistry:
    package_dir = Path(__file__).parent

    for module_path in sorted(package_dir.glob("*.py")):
        stem = module_path.stem
        if stem.startswith("_") or stem == "base":
            continue
        _register_module(stem)

    for pkg_path in sorted(package_dir.glob("*/")):
        name = pkg_path.name
        if name.startswith("_") or name == "__pycache__":
            continue
        if not (pkg_path / "__init__.py").exists():
            continue
        _register_module(name)

    return DownloaderRegistry


def _register_module(module_name: str) -> None:
    module = importlib.import_module(f".{module_name}", __package__)
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, BaseDownloader)
            and attr is not BaseDownloader
            and getattr(attr, "name", "")
        ):
            DownloaderRegistry.register(attr)


registry = _auto_discover()
