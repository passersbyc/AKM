"""favorite 命令 — 查看 / 下载账号收藏的作品。

支持站点：
- asmrmoon（默认）：需配置登录 token（localStorage["token"] 的值）
  config.json 的 asmrmoon.token，或环境变量 AKM_ASMRMOON_TOKEN。
- pixiv：需配置有效 Cookie（config.json 的 pixiv.cookie）。

用法：
  akm favorite               # 检查全部站点的收藏
  akm favorite pixiv         # 只列 pixiv 收藏
  akm favorite asmrmoon --download   # 只下载 asmrmoon 收藏
  akm favorite --download    # 下载全部站点的收藏
"""
import argparse

from src.cli.base import BaseCommand
from src.cli.commands._download_utils import DownloadGroupRunner
from src.core.logging import logger


class FavoriteCommand(BaseCommand):
    verb = "favorite"
    nouns: list[str] = []
    description = "查看或下载账号收藏的作品（asmrmoon / pixiv）"
    group = "订阅下载"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("site", type=str, nargs="?", default=None,
                            choices=["asmrmoon", "pixiv"],
                            help="站点（默认检查全部）")
        parser.add_argument("--download", "-d", action="store_true",
                            help="下载全部收藏（默认仅列出）")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        if args.site == "pixiv":
            rc = self._pixiv(args)
            self._hint(args)
            return rc
        if args.site == "asmrmoon":
            rc = self._asmrmoon(args)
            self._hint(args)
            return rc
        # 未指定站点：依次检查全部
        rc = 0
        rc |= self._asmrmoon(args)
        self.output.info("")
        rc |= self._pixiv(args)
        self._hint(args)
        return rc

    def _hint(self, args: argparse.Namespace) -> None:
        """未指定 --download 时，末尾统一提示一次。"""
        if not args.download:
            self.output.info("[dim]加 --download 可下载全部收藏[/dim]")

    # ── asmrmoon ──────────────────────────────────────────

    def _asmrmoon(self, args: argparse.Namespace) -> int:
        from src.downloader.asmrmoon import AsmrMoonDownloader

        self.output.info("[bold cyan]asmrmoon[/bold cyan]")
        downloader = AsmrMoonDownloader()
        if not downloader.session.headers.get("Authorization"):
            self.output.error(
                "未配置登录 token，无法访问收藏（接口会返回 You are a guest）。\n"
                "请配置 config.json 的 asmrmoon.token 或环境变量 "
                "AKM_ASMRMOON_TOKEN。")
            return 1

        try:
            favs = downloader.list_favorites()
        except Exception as e:
            self.output.error(f"获取收藏失败: {e}")
            return 1

        if not favs:
            self.output.info("[yellow]当前账号没有收藏任何音声～[/yellow]")
            return 0

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
            return 0

        works = downloader.get_favorite_works()
        if not works:
            self.output.info("[yellow]收藏里没有可下载的音频[/yellow]")
            return 0

        logger.info(f"开始下载收藏: {len(works)} 个")
        runner = DownloadGroupRunner(works, site="asmrmoon", favorited=True)
        results = runner.run()

        from src.operations.pull_op import reindex_after_pull
        reindex_after_pull(works)

        return self._finish("收藏下载完成", results)

    # ── pixiv ─────────────────────────────────────────────

    def _pixiv(self, args: argparse.Namespace) -> int:
        from src.downloader.pixiv.downloader import PixivDownloader

        self.output.info("[bold cyan]pixiv[/bold cyan]")
        downloader = PixivDownloader()

        try:
            favs = downloader.list_bookmarks()
        except Exception as e:
            self.output.error(f"获取收藏失败: {e}")
            return 1

        if not favs:
            # 区分「收藏为空」和「cookie 失效」
            from src.downloader.pixiv.client import PixivClient
            cookie = downloader.config.primary_cookie or downloader.config.cookie
            status, uid, name = PixivClient.check_cookie_validity(cookie)
            if status == "valid":
                self.output.info(
                    f"[yellow]账号 {name or uid} 当前没有收藏任何作品～[/yellow]")
                return 0
            self.output.error(
                "未获取到收藏作品（Cookie 可能已失效）。\n"
                "请重新在浏览器登录 pixiv 后复制 Cookie，配置到 "
                "config.json 的 pixiv.cookie。")
            return 1

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
                frows.append([u.get("name", ""), uid,
                              f"https://www.pixiv.net/users/{uid}",
                              "是" if already else "否"])
            self.output.table(
                "关注的作者",
                [{"header": "作者", "key": "name", "max_width": 30},
                 {"header": "UID", "key": "uid", "justify": "right"},
                 {"header": "网址", "key": "url", "max_width": 46},
                 {"header": "已关注", "key": "tracked", "justify": "center"}],
                frows,
                footer=f"共 {len(following)} 位",
            )
        else:
            self.output.info("[dim]未获取到关注的作者[/dim]")

        if not args.download:
            return 0

        works = downloader.get_favorite_works()
        if not works:
            self.output.info("[yellow]收藏里没有可下载的作品[/yellow]")
            return 0

        logger.info(f"开始下载收藏: {len(works)} 个")
        runner = DownloadGroupRunner(works, site="pixiv", favorited=True)
        results = runner.run()

        from src.operations.pull_op import reindex_after_pull
        reindex_after_pull(works)

        return self._finish("收藏下载完成", results)

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
