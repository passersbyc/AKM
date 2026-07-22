"""startui 命令 — 启动 FastAPI Web UI 服务器并自动打开浏览器。"""
import argparse
import threading
import webbrowser

from src.cli.base import BaseCommand


class StartUICommand(BaseCommand):
    verb = "startui"
    nouns: list[str] = []
    description = "启动 Web UI 界面（自动打开浏览器）"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--host", default="127.0.0.1", help="绑定地址（默认 127.0.0.1）")
        parser.add_argument("--port", type=int, default=8000, help="端口（默认 8000）")
        parser.add_argument("--reload", action="store_true", help="热重载（开发模式）")
        parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        import uvicorn
        from src.web import create_app

        app = create_app()
        url = f"http://{args.host}:{args.port}"
        self.output.info(f"AKM WebUI 启动中... {url}")

        # 延迟 1.5s 打开浏览器，等 uvicorn 起来
        if not args.no_browser:
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()

        uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
        return 0
