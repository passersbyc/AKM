import argparse
import json

from src.cli.core import BaseCommand
from src.core.config import get_project_root


class AuthCommand(BaseCommand):

    @property
    def name(self) -> str:
        return "auth"

    @property
    def description(self) -> str:
        return "管理 Pixiv Cookie 鉴权"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--test", action="store_true",
                            help="测试连接，输出 Cookie 池中所有账号信息")
        subs = parser.add_subparsers(dest="subcommand", help="子命令")

        p_cookie = subs.add_parser("cookie", help="添加 Cookie 到池")
        p_cookie.add_argument("cookie", nargs="?", default=None,
                              help="Cookie 值（浏览器复制后粘贴，也支持管道输入）")

        p_cookie_pool = subs.add_parser("cookie-pool", help="管理 Cookie 池")
        p_cookie_pool.add_argument("action", type=str, choices=["list", "remove", "use"],
                                   help="list / remove N / use N")
        p_cookie_pool.add_argument("index", type=int, nargs="?", default=None,
                                   help="索引（remove/use 时需要）")

        p_status = subs.add_parser("status", help="查看鉴权状态")

    def execute(self, args: argparse.Namespace) -> int:
        if args.test:
            return self._cmd_test()
        if args.subcommand == "cookie":
            return self._cmd_cookie(args)
        elif args.subcommand == "cookie-pool":
            return self._cmd_cookie_pool(args)
        elif args.subcommand == "status":
            return self._cmd_status()
        else:
            self._print("请指定子命令: cookie / cookie-pool / status\n使用 --test 测试连接")
            return 1

    def _cmd_status(self) -> int:
        config = self._load_config()
        pixiv = config.get("pixiv", {})
        has_cookie = bool((pixiv or {}).get("cookie", ""))
        pool = pixiv.get("cookie_pool", [])
        if has_cookie:
            cookie = pixiv.get("cookie", "")
            sessid = self._extract_sessid(cookie)
            masked = sessid[:8] + "..." if len(sessid) > 8 else sessid
            self._print(f"[green]Cookie: PHPSESSID={masked}[/green]")
            if len(pool) > 1:
                self._print(f"[dim]Cookie 池: {len(pool)} 个[/dim]")
        else:
            self._print("[yellow]Cookie 未配置。运行 'akm auth cookie <值>' 设置[/yellow]")
        return 0

    def _cmd_cookie(self, args: argparse.Namespace) -> int:
        cookie = args.cookie
        if not cookie:
            import sys
            cookie = sys.stdin.read().strip()

        cookie = (cookie or "").strip()
        if not cookie:
            self._print_error("用法: akm auth cookie <值>  或  pbpaste | akm auth cookie")
            return 1

        config = self._load_config()
        pixiv = config.setdefault("pixiv", {})

        if "PHPSESSID=" not in cookie and ";" not in cookie:
            cookie = f"PHPSESSID={cookie}"

        pool = pixiv.setdefault("cookie_pool", [])
        if not pool:
            pool.append(cookie)

        new_sessid = self._extract_sessid(cookie)
        is_new = not any(self._extract_sessid(c) == new_sessid for c in pool)
        if is_new:
            pool.append(cookie)

        pixiv["cookie"] = cookie
        self._save_config(config)

        if is_new:
            self._print(f"[green]Cookie 已添加（池共 {len(pool)} 个）[/green]")
        else:
            self._print(f"[green]已切换到该 Cookie（池共 {len(pool)} 个）[/green]")
        self._print("[dim]运行 'akm auth --test' 验证[/dim]")
        return 0

    def _cmd_cookie_pool(self, args: argparse.Namespace) -> int:
        config = self._load_config()
        pixiv = config.get("pixiv", {})
        pool = pixiv.get("cookie_pool", [])
        current = pixiv.get("cookie", "")

        if args.action == "list":
            if not pool:
                self._print("[dim]Cookie 池为空[/dim]")
                return 0
            self._print(f"[bold]Cookie 池 ({len(pool)} 个)[/bold]")
            curr_sessid = self._extract_sessid(current) if current else ""
            for i, c in enumerate(pool):
                sessid = self._extract_sessid(c)
                marker = " ← 当前" if sessid == curr_sessid else ""
                masked = (sessid[:8] + "..." + sessid[-4:]) if len(sessid) > 16 else sessid
                self._print(f"  [{i}] PHPSESSID={masked}{marker}")
            return 0

        if args.action == "remove":
            idx = args.index
            if idx is None or idx < 0 or idx >= len(pool):
                self._print_error(f"索引无效 (0-{len(pool)-1})")
                return 1
            removed = pool.pop(idx)
            if removed == current and pool:
                pixiv["cookie"] = pool[0]
            elif removed == current:
                pixiv["cookie"] = ""
            self._save_config(config)
            self._print(f"[green]已移除 Cookie [{idx}]（池剩余 {len(pool)} 个）[/green]")
            return 0

        if args.action == "use":
            idx = args.index
            if idx is None or idx < 0 or idx >= len(pool):
                self._print_error(f"索引无效 (0-{len(pool)-1})")
                return 1
            pixiv["cookie"] = pool[idx]
            self._save_config(config)
            self._print(f"[green]已切换到 Cookie [{idx}][/green]")
            return 0

        return 1

    def _test_one_cookie(self, cookie: str) -> dict | None:
        import requests as _requests
        try:
            r = _requests.get("https://www.pixiv.net/ajax/user/self", headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Cookie": cookie,
                "Referer": "https://www.pixiv.net/",
            }, timeout=15)
            if r.ok:
                body = r.json().get("userData", {})
                return {
                    "uid": body.get("id", ""),
                    "name": body.get("name", ""),
                    "account": body.get("pixivId", ""),
                    "premium": body.get("premium", None),
                    "image": body.get("profileImgBig", "") or body.get("profileImg", ""),
                }
        except _requests.exceptions.Timeout:
            self._print("[dim]  请求超时[/dim]")
        except _requests.exceptions.ConnectionError as e:
            self._print(f"[dim]  连接失败: {e}[/dim]")
        except Exception as e:
            self._print(f"[dim]  请求异常: {type(e).__name__}: {e}[/dim]")
        return None

    def _print_account(self, info: dict):
        self._print(f"  UID:        {info['uid']}")
        self._print(f"  用户名:     {info['name']}")
        self._print(f"  账号 ID:    {info['account']}")
        if info['premium'] is True:
            self._print(f"  会员状态:   [yellow]Pixiv Premium[/yellow]")
        elif info['premium'] is False:
            self._print(f"  会员状态:   普通账号")
        if info['image']:
            self._print(f"  头像:       {info['image']}")

    def _cmd_test(self) -> int:
        config = self._load_config()
        pixiv = config.get("pixiv", {})
        pool = pixiv.get("cookie_pool", [])

        if not pool:
            self._print_error("Cookie 池为空，请先运行 'akm auth cookie <值>'")
            return 1

        self._print(f"[dim]正在测试 {len(pool)} 个 Cookie...[/dim]\n")

        for i, cookie in enumerate(pool):
            info = self._test_one_cookie(cookie)
            if info:
                masked = cookie[cookie.index("PHPSESSID=") + 10:][:8] if "PHPSESSID=" in cookie else cookie[:8]
                self._print(f"[bold]Cookie [{i}] PHPSESSID={masked}...[/bold]")
                self._print("─" * 40)
                self._print_account(info)
                self._print()
            else:
                self._print(f"[dim]Cookie [{i}] 已失效[/dim]\n")

        return 0

    def _load_config(self) -> dict:
        config_path = get_project_root() / "config.json"
        if not config_path.exists():
            return {}
        config = json.loads(config_path.read_text(encoding="utf-8"))
        pixiv = config.get("pixiv", {})
        if pixiv.get("cookie") and not pixiv.get("cookie_pool"):
            pixiv["cookie_pool"] = [pixiv["cookie"]]
            self._save_config(config)
        return config

    @staticmethod
    def _extract_sessid(c: str) -> str:
        idx = c.find("PHPSESSID=")
        if idx == -1:
            return c
        start = idx + len("PHPSESSID=")
        end = c.index(";", start) if ";" in c[start:] else len(c)
        return c[start:end]

    def _save_config(self, config: dict) -> None:
        config_path = get_project_root() / "config.json"
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=4), encoding="utf-8")
