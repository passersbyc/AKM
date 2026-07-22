"""startui 命令 — 启动 FastAPI Web UI 服务器并自动打开浏览器。"""
import argparse
import socket
import threading
import webbrowser

from src.cli.base import BaseCommand


def _find_free_port(host: str, preferred: int, max_tries: int = 10) -> int:
    """从 preferred 开始找可用端口，最多尝试 max_tries 次。"""
    for offset in range(max_tries):
        port = preferred + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    return -1


class StartUICommand(BaseCommand):
    verb = "startui"
    nouns: list[str] = []
    description = "启动 Web UI 界面（自动打开浏览器）"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--host", default="127.0.0.1", help="绑定地址（默认 127.0.0.1）")
        parser.add_argument("--port", type=int, default=8000, help="端口（默认 8000，被占用时自动递增）")
        parser.add_argument("--reload", action="store_true", help="热重载（开发模式）")
        parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        import uvicorn
        from src.web import create_app

        port = _find_free_port(args.host, args.port)
        if port == -1:
            self.output.error(f"端口 {args.port}~{args.port + 9} 均被占用，请手动指定: --port <port>")
            return 1
        if port != args.port:
            self.output.warn(f"端口 {args.port} 被占用，自动切换到 {port}")

        app = create_app()
        url = f"http://{args.host}:{port}"
        self.output.info(f"AKM WebUI 启动中... {url}")

        # 延迟 1.5s 打开浏览器，等 uvicorn 起来
        if not args.no_browser:
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()

        uvicorn.run(app, host=args.host, port=port, reload=args.reload)
        return 0
