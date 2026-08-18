"""cookie 命令 — 检查各站点的 cookie / token，并清理过期的 Pixiv cookie。

逐个站点检查凭据状态，区分三种：
- valid（有效）  expired（失效）  offline（网络不可达，不清理）
断网时不会误删 cookie。

用法：
  akm cookie                # 检查全部站点 + 清理过期 pixiv cookie
  akm cookie --dry-run      # 只检查报告，不清理
"""
import argparse

from src.cli.base import BaseCommand


class CookieCommand(BaseCommand):
    verb = "cookie"
    nouns: list[str] = []
    description = "检查各站点 cookie/token 并清理过期项"
    group = "系统"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--dry-run", action="store_true",
                            help="只检查报告，不清理")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        self._check_pixiv(args)
        self.output.info("")
        self._check_asmrmoon()
        return 0

    # ── pixiv ─────────────────────────────────────────────

    def _check_pixiv(self, args: argparse.Namespace) -> None:
        from src.downloader.pixiv.client import PixivClient
        from src.downloader.pixiv.config import PixivConfig

        config = PixivConfig.from_file()
        pool = list(config.cookie_pool)

        self.output.info("[bold]Pixiv[/bold]")
        if not pool:
            self.output.info("  [dim]cookie 池为空[/dim]")
            return

        self.output.info(f"  正在检查 {len(pool)} 个 cookie ...")

        valid = []
        expired = []
        offline = 0
        for i, cookie in enumerate(pool):
            status, uid, name = PixivClient.check_cookie_validity(cookie)
            sid = self._sessid_of(cookie)
            if status == "valid":
                valid.append((cookie, uid, name, sid))
                self.output.info(
                    f"    [green]✓[/green] [{i}] {sid}  账号 {name}"
                    + (f" ({uid})" if uid else ""))
            elif status == "expired":
                expired.append((cookie, sid))
                self.output.info(f"    [red]✗[/red] [{i}] {sid}  已过期")
            else:
                offline += 1
                self.output.info(
                    f"    [yellow]△[/yellow] [{i}] {sid}  网络不可达，未判定")

        parts = [f"[green]{len(valid)} 有效[/green]"]
        if expired:
            parts.append(f"[red]{len(expired)} 过期[/red]")
        if offline:
            parts.append(f"[yellow]{offline} 无法判定[/yellow]")
        self.output.info(f"  结果: {'，'.join(parts)}")

        # 主账号（favorite 专用 + 下载最后 fallback）
        primary = config.primary_cookie
        if primary:
            status, uid, name = PixivClient.check_cookie_validity(primary)
            sid = self._sessid_of(primary)
            if status == "valid":
                self.output.info(
                    f"  主账号 [green]✓[/green] {sid}  账号 {name}"
                    + (f" ({uid})" if uid else ""))
            elif status == "expired":
                self.output.info(f"  主账号 [red]✗[/red] {sid}  已过期")
            else:
                self.output.info(
                    f"  主账号 [yellow]△[/yellow] {sid}  网络不可达，未判定")
        else:
            self.output.info("  主账号 [dim]未配置[/dim]")

        if not expired:
            self.output.info("  [green]无过期 cookie～[/green]")
            if offline:
                self.output.info(
                    "  [dim]部分 cookie 因网络不可达未判定，未做清理[/dim]")
            return

        if args.dry_run:
            self.output.info("  [dim]--dry-run 模式，未删除[/dim]")
            return

        removed = 0
        for cookie, sid in expired:
            if config.remove_cookie_from_pool(cookie):
                removed += 1
                self.output.info(f"  [yellow]已清理[/yellow] {sid}")
        self.output.info(f"  [green]清理完成: 移除 {removed} 个，"
                         f"剩余 {len(valid) + offline} 个[/green]")

    # ── asmrmoon ──────────────────────────────────────────

    def _check_asmrmoon(self) -> None:
        from src.downloader.asmrmoon import AsmrMoonDownloader

        self.output.info("[bold]asmrmoon[/bold]")
        try:
            d = AsmrMoonDownloader()
            result = d.check_credentials()
        except Exception as e:
            self.output.info(f"  [red]检查失败: {e}[/red]")
            return

        token = result.get("token", {})
        cookie = result.get("cookie", {})

        self._print_cred("token", token)
        self._print_cred("cookie", cookie)

    def _print_cred(self, label: str, item: dict) -> None:
        status = item.get("status", "offline")
        detail = item.get("detail", "")
        if status == "valid":
            self.output.info(f"  [green]✓[/green] {label}   {detail}")
        elif status == "expired":
            self.output.info(f"  [red]✗[/red] {label}   {detail}")
        else:
            self.output.info(f"  [yellow]△[/yellow] {label}   {detail}")

    @staticmethod
    def _sessid_of(cookie: str) -> str:
        import re
        m = re.search(r"PHPSESSID=([^;]+)", cookie)
        return m.group(1)[:20] if m else "(无 PHPSESSID)"
