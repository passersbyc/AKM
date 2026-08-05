"""pull 操作 — 下载队列拉取入库的业务编排层。

职责：
  - 读取下载队列、调度下载核心（runner）、下载完成后统一重索引。
  - 库级操作（重索引）从下载器中剥离：下载器只负责产出文件与结果，
    不再感知书库的 ID/文件管理；编排层在全部下载完成后统一执行，
    此时无并发写入，天然消除全表重写与其他写入的竞态窗口。
"""
from __future__ import annotations

from typing import Callable, Optional


def reindex_after_pull(urls: list[str]) -> None:
    """pull 完成后对已下载的 pixiv 作品重排 ID。

    保持作品序号与 pixiv 作品 ID 顺序一致（与原下载器内 finally 逻辑等价）。
    非 pixiv URL 不参与重索引。
    """
    from src.core.work_manager import WorkManager
    from src.downloader.pixiv.extractors import extract_pixiv_id

    pixiv_urls = {u for u in urls if "pixiv.net" in u}
    if not pixiv_urls:
        return
    WorkManager.reindex_by_sources(
        pixiv_urls,
        sort_key=lambda r: int(extract_pixiv_id(r.get("来源", "")) or 0),
    )


def pull_and_import(
    urls: Optional[list[str]] = None,
    *,
    mode: str = "both",
    site: Optional[str] = None,
    pull_base_mapping: Optional[dict] = None,
    ctrl=None,
    progress_callback: Optional[Callable] = None,
    executor_hook: Optional[Callable] = None,
) -> dict:
    """一站式拉取：读队列 → 调度下载 → 重索引。

    urls 为 None 时自动读取下载队列待下载项。
    返回 runner 的 results dict：
    {success, failed, skipped, total, elapsed, timeline, cancelled}。

    调用方：WebUI 后台线程直接使用；CLI 侧因需要键盘监听/SIGINT 包装
    （DownloadGroupRunner），保持 runner 调用并在完成后自行 reindex_after_pull。
    """
    from src.core.download import get_pending_urls
    from src.downloader.runner import run_download_groups

    if urls is None:
        urls = [p["url"] for p in get_pending_urls()]

    results = run_download_groups(
        urls,
        mode=mode,
        site=site,
        pull_base_mapping=pull_base_mapping,
        ctrl=ctrl,
        progress_callback=progress_callback,
        executor_hook=executor_hook,
    )
    reindex_after_pull(urls)
    return results
