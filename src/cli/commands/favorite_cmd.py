"""favorite 命令 — 查看 / 下载账号收藏的作品。

支持站点：
- asmrmoon：需配置登录 token（localStorage["token"] 的值）
  config.json 的 asmrmoon.token，或环境变量 AKM_ASMRMOON_TOKEN。
- pixiv：需配置有效 Cookie（config.json 的 pixiv.cookie）。
- pawchive：需配置有效 Cookie（config.json 的 pawchive.cookie）。

用法：
  akm favorite               # 检查全部站点的收藏
  akm favorite pixiv         # 只列 pixiv 收藏
  akm favorite asmrmoon --download   # 只下载 asmrmoon 收藏
  akm favorite --download    # 下载全部站点的收藏（多站点并行）
"""
import argparse
from typing import List, Optional

from src.cli.base import BaseCommand
from src.cli.commands._download_utils import DownloadGroupRunner
from src.core.logging import logger


class FavoriteCommand(BaseCommand):
    verb = "favorite"
    nouns: list[str] = []
    description = "查看或下载账号收藏的作品（asmrmoon / pixiv / pawchive）"
    group = "订阅下载"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("site", type=str, nargs="?", default=None,
                            choices=["asmrmoon", "pixiv", "pawchive"],
                            help="站点（默认检查全部）")
        parser.add_argument("--download", "-d", action="store_true",
                            help="下载全部收藏（默认仅列出）")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        if args.site:
            return self._run_single(args.site, args)
        # 未指定站点：展示全部（串行）→ 下载全部（并行）
        return self._run_all(args)

    def _run_single(self, site: str, args: argparse.Namespace) -> int:
        """单站点：展示 + 下载（串行，含键盘监听/信号包装）。"""
        show = {"asmrmoon": self._asmrmoon,
                "pixiv": self._pixiv,
                "pawchive": self._pawchive}[site]
        works = show(args)
        self._hint(args)
        if works is None:
            return 1
        if not works:
            return 0
        results = self._download_site(site, works)
        return self._finish("收藏下载完成", results)

    def _run_all(self, args: argparse.Namespace) -> int:
        """全部站点：展示串行（表格顺序稳定）→ 下载并行（聚合进度条）。"""
        tasks: List[tuple[str, list]] = []
        rc = 0
        for site, show in (("asmrmoon", self._asmrmoon),
                           ("pixiv", self._pixiv),
                           ("pawchive", self._pawchive)):
            works = show(args)
            if works is None:
                rc = 1
            elif works:
                tasks.append((site, works))
            if not args.download:
                self.output.info("")
        self._hint(args)
        if not tasks:
            return rc
        results = self._download_parallel(tasks)
        return self._finish("收藏下载完成", results)

    def _hint(self, args: argparse.Namespace) -> None:
        """未指定 --download 时，末尾统一提示一次。"""
        if not args.download:
            self.output.info("[dim]加 --download 可下载全部收藏[/dim]")

    @staticmethod
    def _clip(s: str, n: int) -> str:
        """截断字符串到 n 个字符（含省略号），处理宽字符。"""
        s = s or ""
        if len(s) <= n:
            return s
        return s[: n - 1] + "…"

    # ── 下载调度 ─────────────────────────────────────────

    def _download_site(self, site: str, works: List[str]) -> dict:
        """单站点下载（CLI 表现层：键盘监听 + 信号包装）。"""
        logger.info(f"开始下载收藏: {len(works)} 个")
        runner = DownloadGroupRunner(works, site=site, favorited=True)
        results = runner.run()
        from src.operations.pull_op import reindex_after_pull
        reindex_after_pull(works)
        return results

    def _download_parallel(self, tasks: List[tuple[str, list]]) -> dict:
        """多站点并行下载，共享一个聚合进度条（每站点一行）。

        直接调调度核心 run_download_groups（绕过 DownloadGroupRunner 的
        信号/键盘包装，避免子线程调用 signal.signal 报错），SIGINT 在本
        方法主线程统一处理一次。
        """
        import signal
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from src.core.progress import (make_progress, add_progress_task,
                                       suppress_console_logging)
        from src.downloader.context import DownloadControl
        from src.downloader.runner import run_download_groups
        from src.operations.pull_op import reindex_after_pull

        ctrl = DownloadControl()

        # 共享进度条：每个站点一组 task（主行 + 计数行）
        progress = None
        setups: dict[str, tuple] = {}
        for site, works in tasks:
            counts = {"success": 0, "failed": 0, "skipped": 0}
            if progress is None:
                progress, main_id, counts_id = make_progress(
                    counts, site, total=len(works))
            else:
                main_id, counts_id = add_progress_task(
                    progress, counts, site, total=len(works))
            setups[site] = (progress, main_id, counts_id, counts)

        def _run_one(site, works):
            progress, main_id, counts_id, counts = setups[site]

            def _setup(downloader):
                downloader.set_progress(progress, main_id, counts_id, counts)

            logger.info(f"开始下载收藏 [{site}]: {len(works)} 个")
            return run_download_groups(
                works, site=site, favorited=True, ctrl=ctrl,
                progress_setup=_setup)

        def _sigint(signum, frame):
            ctrl.request_cancel()

        old_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, _sigint)

        agg = {"success": 0, "failed": 0, "skipped": 0, "total": 0}
        try:
            with suppress_console_logging():
                progress.start()
                try:
                    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
                        futures = {pool.submit(_run_one, site, works)
                                   for site, works in tasks}
                        for future in as_completed(futures):
                            try:
                                results = future.result()
                            except Exception as e:
                                logger.error(f"站点下载异常: {e}")
                                results = {"success": 0, "failed": 1,
                                           "skipped": 0}
                            agg["success"] += results.get("success", 0)
                            agg["failed"] += results.get("failed", 0)
                            agg["skipped"] += results.get("skipped", 0)
                finally:
                    progress.stop()
        finally:
            signal.signal(signal.SIGINT, old_handler)

        # 统一重索引（reindex 操作数据库，放回主线程避免锁竞争）
        all_works = [w for _, works in tasks for w in works]
        reindex_after_pull(all_works)

        agg["total"] = agg["success"] + agg["failed"] + agg["skipped"]
        return agg

    # ── asmrmoon ──────────────────────────────────────────

    def _asmrmoon(self, args: argparse.Namespace) -> Optional[List[str]]:
        from src.downloader.asmrmoon import AsmrMoonDownloader

        downloader = AsmrMoonDownloader()
        if not downloader.session.headers.get("Authorization"):
            self.output.error(
                "未配置登录 token，无法访问收藏（接口会返回 You are a guest）。\n"
                "请配置 config.json 的 asmrmoon.token 或环境变量 "
                "AKM_ASMRMOON_TOKEN。")
            return None

        # download 模式：只收集下载链接，不展示收藏列表/作者表格
        if args.download:
            try:
                return downloader.get_favorite_works()
            except Exception as e:
                self.output.error(f"获取收藏失败: {e}")
                return None

        self.output.info("[bold cyan]asmrmoon[/bold cyan]")
        try:
            favs = downloader.list_favorites()
        except Exception as e:
            self.output.error(f"获取收藏失败: {e}")
            return None

        if not favs:
            self.output.info("[yellow]当前账号没有收藏任何音声～[/yellow]")
            return []

        rows = []
        total_mb = 0.0
        host = downloader._host_of("https://asmrmoon.com/")
        for f in favs:
            size = f.get("size", 0)
            total_mb += size / 1024 / 1024
            source = f"{host}{f.get('path', '')}"
            in_db = downloader._is_source_in_manifest(source)
            rows.append([f.get("name", ""), f"{size / 1024 / 1024:.1f} MB",
                         f.get("path", ""), "是" if in_db else "否"])
        self.output.table(
            "收藏的音声",
            [{"header": "标题", "key": "name", "max_width": 55},
             {"header": "大小", "key": "size", "justify": "right"},
             {"header": "路径", "key": "path", "max_width": 32},
             {"header": "入库", "key": "in_db", "justify": "center"}],
            rows,
            footer=f"共 {len(favs)} 个 · 合计 {total_mb / 1024:.2f} GB",
        )

        # 收藏的作者表格
        try:
            authors = downloader.list_favorite_authors()
        except Exception:
            authors = []
        if authors:
            arows = [[a.get("author", ""), a.get("category", ""),
                      str(a.get("count", 0))] for a in authors]
            self.output.table(
                "收藏的作者",
                [{"header": "作者", "key": "author", "max_width": 40},
                 {"header": "分类", "key": "category", "max_width": 20},
                 {"header": "收藏数", "key": "count", "justify": "right"}],
                arows,
                footer=f"共 {len(authors)} 位",
            )

        if not args.download:
            return []

        works = downloader.get_favorite_works()
        if not works:
            self.output.info("[yellow]收藏里没有可下载的音频[/yellow]")
            return []
        return works

    # ── pixiv ─────────────────────────────────────────────

    def _pixiv(self, args: argparse.Namespace) -> Optional[List[str]]:
        from src.downloader.pixiv.downloader import PixivDownloader

        downloader = PixivDownloader()

        # download 模式：只收集下载链接，不展示收藏列表/关注作者表格
        if args.download:
            try:
                return downloader.get_favorite_works()
            except Exception as e:
                self.output.error(f"获取收藏失败: {e}")
                return None

        self.output.info("[bold cyan]pixiv[/bold cyan]")
        try:
            favs = downloader.list_bookmarks()
        except Exception as e:
            self.output.error(f"获取收藏失败: {e}")
            return None

        if not favs:
            # 区分「收藏为空」和「cookie 失效」
            from src.downloader.pixiv.client import PixivClient
            cookie = downloader.config.primary_cookie or downloader.config.cookie
            status, uid, name = PixivClient.check_cookie_validity(cookie)
            if status == "valid":
                self.output.info(
                    f"[yellow]账号 {name or uid} 当前没有收藏任何作品～[/yellow]")
                return []
            self.output.error(
                "未获取到收藏作品（Cookie 可能已失效）。\n"
                "请重新在浏览器登录 pixiv 后复制 Cookie，配置到 "
                "config.json 的 pixiv.cookie。")
            return None

        rows = []
        from src.downloader.pixiv.extractors import PixivBaseExtractor
        for f in favs:
            kind = "小说" if f.get("content_type") == "novel" else "插画"
            source = PixivBaseExtractor._build_work_url(
                f.get("id", ""), f.get("content_type", "illust"))
            in_db = downloader._is_source_in_manifest(source)
            rows.append([f.get("title", ""), f.get("author", ""), kind,
                         f.get("id", ""), "是" if in_db else "否"])
        self.output.table(
            "收藏的作品",
            [{"header": "标题", "key": "title", "max_width": 46},
             {"header": "作者", "key": "author", "max_width": 24},
             {"header": "类型", "key": "kind", "justify": "center"},
             {"header": "ID", "key": "id", "justify": "right"},
             {"header": "入库", "key": "in_db", "justify": "center"}],
            rows,
            footer=f"共 {len(favs)} 个收藏",
        )

        # 关注的作者表格
        try:
            following = downloader.list_following()
        except Exception:
            following = []
        if following:
            from src.core.author_manager import resolve as resolve_author
            frows = []
            for u in following:
                uid = u.get("uid", "")
                already = bool(resolve_author(uid))
                comment = (u.get("comment") or "").replace("\n", " ").strip()
                premium = "P" if u.get("premium") else ""
                frows.append([u.get("name", ""), uid,
                              f"https://www.pixiv.net/users/{uid}",
                              "是" if already else "否",
                              self._clip(comment, 16), premium])
            self.output.table(
                "关注的作者",
                [{"header": "作者", "key": "name", "max_width": 22},
                 {"header": "UID", "key": "uid", "justify": "right"},
                 {"header": "网址", "key": "url", "max_width": 44},
                 {"header": "已关注", "key": "tracked", "justify": "center"},
                 {"header": "简介", "key": "comment", "max_width": 34,
                  "no_wrap": True},
                 {"header": "会员", "key": "premium", "justify": "center"}],
                frows,
                footer=f"共 {len(following)} 位",
            )
        else:
            self.output.info("[dim]未获取到关注的作者[/dim]")

        if not args.download:
            return []

        works = downloader.get_favorite_works()
        if not works:
            self.output.info("[yellow]收藏里没有可下载的作品[/yellow]")
            return []
        return works

    # ── pawchive ─────────────────────────────────────────

    def _pawchive(self, args: argparse.Namespace) -> Optional[List[str]]:
        from src.downloader.pawchive import PawchiveDownloader

        downloader = PawchiveDownloader()

        # download 模式：只收集下载链接，不展示收藏列表/作者表格
        if args.download:
            try:
                return downloader.get_favorite_works()
            except Exception as e:
                self.output.error(f"获取收藏失败: {e}")
                return None

        self.output.info("[bold cyan]pawchive[/bold cyan]")
        try:
            favs = downloader.list_favorites()
        except Exception as e:
            self.output.error(f"获取收藏失败: {e}")
            return None

        # 收藏作品表格
        if favs:
            rows = []
            for f in favs:
                svc = f.get("service", "")
                svc = "Fanbox" if svc == "fanbox" else (
                    "Patreon" if svc == "patreon" else svc)
                post_url = f.get("url", "")
                in_db = any(
                    s.startswith(post_url) for s in downloader.existing_sources)
                rows.append([f.get("title", ""), svc,
                             str(f.get("attachments", 0)),
                             f.get("date", "")[:10],
                             "是" if in_db else "否"])
            self.output.table(
                "收藏的作品",
                [{"header": "标题", "key": "title", "max_width": 36},
                 {"header": "服务", "key": "service", "justify": "center"},
                 {"header": "附件", "key": "attachments", "justify": "right"},
                 {"header": "收藏日期", "key": "date", "max_width": 12},
                 {"header": "入库", "key": "in_db", "justify": "center"}],
                rows,
                footer=f"共 {len(favs)} 个收藏",
            )
        else:
            self.output.info("[yellow]当前账号没有收藏任何作品～[/yellow]")

        # 收藏作者表格
        try:
            creators = downloader.list_favorite_creators()
        except Exception:
            creators = []
        if creators:
            crows = [[c.get("service", ""), c.get("name", ""),
                      c.get("url", ""), c.get("date", "")[:10]]
                     for c in creators]
            self.output.table(
                "收藏的作者",
                [{"header": "服务", "key": "service", "max_width": 14},
                 {"header": "作者", "key": "name", "max_width": 22},
                 {"header": "网址", "key": "url", "max_width": 44},
                 {"header": "收藏日期", "key": "date", "max_width": 12}],
                crows,
                footer=f"共 {len(creators)} 位",
            )
        else:
            self.output.info("[dim]未获取到收藏的作者[/dim]")

        if not args.download:
            return []

        works = downloader.get_favorite_works()
        if not works:
            self.output.info("[yellow]收藏里没有可下载的作品[/yellow]")
            return []
        return works

    # ── 共用 ──────────────────────────────────────────────

    def _finish(self, label: str, results: dict) -> int:
        summary = (f"{label}: 成功 {results['success']}"
                   f" | 失败 {results['failed']}"
                   f" | 跳过 {results['skipped']}")
        logger.info(summary)
        return self.output.result(results["failed"] == 0,
                                  data={"total": results["total"],
                                        "success": results["success"],
                                        "failed": results["failed"],
                                        "skipped": results["skipped"]})
