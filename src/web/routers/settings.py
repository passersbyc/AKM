"""设置路由 — GET /settings 查看配置, POST /settings 保存 project_settings。"""
from __future__ import annotations

import json
from urllib.parse import quote

from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import RedirectResponse, JSONResponse

from src.core.config import load_config, invalidate_config, get_config_path
from src.operations import get_stats
from src.web.app import templates

router = APIRouter()

_EXPORT_FORMATS = ["folder", "zip", "epub"]


@router.get("/settings")
def settings_page(
    request: Request,
    message: str = Query(""),
    message_type: str = Query(""),
):
    """设置页：展示并编辑项目配置。"""
    cfg = load_config()
    return templates.TemplateResponse(request, "settings.html", {
        "request": request,
        "active_page": "settings",
        "settings": cfg.get("project_settings", {}),
        "export_formats": _EXPORT_FORMATS,
        "config_path": str(get_config_path()),
        "message": message,
        "message_type": message_type,
        "stats": get_stats(),
    })


@router.post("/settings")
def settings_save(
    request: Request,
    library_path: str = Form(""),
    db_path: str = Form(""),
    export_path: str = Form(""),
    export_format: str = Form(""),
    convert_traditional: str = Form(""),
    kid_mode: str = Form(""),
    open_app_book: str = Form(""),
    open_app_other: str = Form(""),
):
    """保存设置到 config.json。"""
    cfg = load_config()
    ps = cfg.setdefault("project_settings", {})
    ps["library_path"] = library_path.strip()
    ps["db_path"] = db_path.strip()
    ps["export_path"] = export_path.strip()
    if export_format in _EXPORT_FORMATS:
        ps["export_format"] = export_format
    ps["convert_traditional"] = convert_traditional == "on"
    ps["kid_mode"] = kid_mode == "on"
    ps["open_app_book"] = open_app_book.strip()
    ps["open_app_other"] = open_app_other.strip()
    cfg["project_settings"] = ps

    try:
        with open(get_config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
    except Exception as e:
        return RedirectResponse(
            f"/settings?message={quote(f'(｡•́︿•̀｡) 保存失败呀～ {e}')}&message_type=warning",
            status_code=303,
        )

    invalidate_config()
    return RedirectResponse(
        f"/settings?message={quote('(◕‿◕) 设置已保存～')}&message_type=success",
        status_code=303,
    )


@router.get("/settings/kid-mode")
def kid_mode_status():
    """查询当前儿童模式状态。"""
    cfg = load_config()
    ps = cfg.get("project_settings", {}) or {}
    return {"kid_mode": bool(ps.get("kid_mode", False))}


@router.post("/settings/kid-mode/toggle")
def kid_mode_toggle():
    """切换儿童模式开关（顶栏快捷切换用），立即生效。"""
    cfg = load_config()
    ps = cfg.setdefault("project_settings", {})
    new_val = not bool(ps.get("kid_mode", False))
    ps["kid_mode"] = new_val
    try:
        with open(get_config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
    except Exception as e:
        return JSONResponse({"success": False, "kid_mode": new_val, "error": str(e)}, status_code=500)
    invalidate_config()
    return {"success": True, "kid_mode": new_val}
