"""FastAPI 应用工厂：静态文件 + Jinja2 模板 + 路由注册。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# 项目根目录（src/web/ → 上两级 = 项目根）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_TEMPLATES_DIR = _PROJECT_ROOT / "templates"
_STATIC_DIR = _PROJECT_ROOT / "static"

# 全局模板实例（routers 共享）
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用。"""
    app = FastAPI(title="AKM WebUI", version="0.1.0")

    # 静态文件
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # 注册路由
    from src.web.routers import dashboard, works, authors, download
    app.include_router(dashboard.router)
    app.include_router(works.router)
    app.include_router(authors.router)
    app.include_router(download.router)

    return app
