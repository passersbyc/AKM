"""下载调度核心 —— 按 site 分组、并发处理、收集结果。

纯业务逻辑，不含任何 CLI 表现层（键盘监听 / 信号处理 / 图表 / stderr 提示）。
CLI 调用方负责包装这些表现层；WebUI 调用方负责包装 WebSocket/SSE 推送。

进度回调契约（参照 operations/verify_op.check_integrity 的 progress_callback 模式）：
    progress_callback(event, **kw)
      - "start":      groups=dict(site->urls), unsupported=list[str]
      - "site_start": site=str, url_count=int（展开后的作品数）
      - "site_done":  site=str, stats=dict(success/failed/skipped/_timeline)
      - "done":       results=dict
"""
from __future__ import annotations

import time
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from src.core.logging import logger


def run_download_groups(
    urls: list[str],
    *,
    mode: str = "both",
    site: Optional[str] = None,
    pull_base_mapping: Optional[dict] = None,
    ctrl: Optional[DownloadControl] = None,
    progress_callback: Optional[Callable] = None,
    executor_hook: Optional[Callable[[ThreadPoolExecutor], None]] = None,
) -> dict:
    """下载调度核心：按 site 分组、并发处理、收集结果。

    不含键盘监听 / 信号处理 / 图表，由调用方包装。
    返回 {success, failed, skipped, total, elapsed, timeline, cancelled}。
    KeyboardInterrupt → results["cancelled"]=True；AuthError 直接向上抛。
    延迟导入 registry/AuthError/DownloadControl 以避免与 src.downloader.__init__
    的 _auto_discover 循环导入（runner 被当作插件模块 import 时不触发顶层 downloader import）。
    """
    from src.downloader import registry
    from src.downloader.base import AuthError
    from src.downloader.context import DownloadControl

    if ctrl is None:
        ctrl = DownloadControl()
    pull_base_mapping = pull_base_mapping or {}
    results: dict = {
        "success": 0, "failed": 0, "skipped": 0,
        "total": 0, "elapsed": 0.0, "timeline": [],
        "cancelled": False,
    }

    # ── 分组 ──────────────────────────────────────────────
    groups: dict[str, list[str]] = defaultdict(list)
    unsupported: list[str] = []
    for u in urls:
        cls = registry.resolve(u, site=site)
        if not cls:
            unsupported.append(u)
            continue
        groups[cls.name].append(u)

    for u in unsupported:
        logger.warning(f"不支持的链接: {u}")
        results["failed"] += 1

    if progress_callback:
        progress_callback("start", groups=dict(groups), unsupported=unsupported)

    if not groups:
        return results

    start_time = time.monotonic()
    lock = threading.Lock()

    def _process_group(site_name: str, site_urls: list[str]) -> dict:
        cls = registry.resolve(site_urls[0], site=site)
        if not cls:
            return {"success": 0, "failed": len(site_urls),
                    "skipped": 0, "_timeline": None}
        downloader = cls()
        downloader.set_download_control(ctrl)
        if pull_base_mapping:
            downloader.set_pull_base_mapping(pull_base_mapping)
        group_stats = {"success": 0, "failed": 0, "skipped": 0,
                       "_timeline": None}

        if downloader.supports_expand:
            work_urls = downloader.expand_urls(site_urls)
            logger.info(f"[{site_name}] {len(site_urls)} 个链接 → "
                        f"展开为 {len(work_urls)} 个作品")
        else:
            work_urls = site_urls

        if progress_callback:
            progress_callback("site_start", site=site_name,
                              url_count=len(work_urls))

        try:
            stats = downloader.process_url(work_urls, mode=mode)
        except AuthError:
            raise
        except Exception as e:
            logger.error(f"[{site_name}] 处理失败: {e}")
            group_stats["failed"] += len(work_urls)
            return group_stats

        group_stats["success"] = stats.get("success", 0)
        group_stats["failed"] = stats.get("failed", 0)
        group_stats["skipped"] = stats.get("skipped", 0)
        if stats.get("_timeline"):
            group_stats["_timeline"] = stats["_timeline"]
        return group_stats

    # ── 并发调度 ──────────────────────────────────────────
    try:
        with ThreadPoolExecutor(max_workers=max(len(groups), 1)) as executor:
            # 让调用方持有 executor 引用（CLI 用于 SIGINT 强制 shutdown）
            if executor_hook:
                executor_hook(executor)

            futures = {
                executor.submit(_process_group, name, s_urls): name
                for name, s_urls in groups.items()
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    stats = future.result()
                except AuthError:
                    raise
                except Exception as e:
                    logger.error(f"[{name}] 站点处理异常: {e}")
                    continue
                with lock:
                    results["success"] += stats.get("success", 0)
                    results["failed"] += stats.get("failed", 0)
                    results["skipped"] += stats.get("skipped", 0)
                    tl = stats.get("_timeline")
                    if tl:
                        timeline = results["timeline"]
                        base = (sum(t for t, _ in timeline[-1:])
                                if timeline else 0)
                        base_count = timeline[-1][1] if timeline else 0
                        for elapsed, count in tl:
                            timeline.append(
                                (base + elapsed, base_count + count))
                if progress_callback:
                    progress_callback("site_done", site=name, stats=stats)
    except AuthError:
        raise
    except KeyboardInterrupt:
        results["cancelled"] = True

    results["total"] = (results["success"] + results["failed"] +
                        results["skipped"])
    results["elapsed"] = round(time.monotonic() - start_time, 1)

    if progress_callback:
        progress_callback("done", results=results)

    return results
