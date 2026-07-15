import argparse
from pathlib import Path
from src.cli.core import BaseCommand
from src.core.converter import convert_to_txt, convert_to_epub, convert_to_pdf
from src.core.logging import logger


class ConvertCommand(BaseCommand):
    def __init__(self) -> None:
        super().__init__()

    @property
    def name(self) -> str:
        return "convert"

    @property
    def description(self) -> str:
        return "文件格式转换（docx/doc→txt/epub，txt→epub，pdf→txt）"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("file", type=str, help="要转换的文件路径")
        parser.add_argument("-t", "--to", type=str, default="txt", help="目标格式: txt, epub (默认: txt)")
        parser.add_argument("-o", "--output", type=str, default="", help="输出文件路径（可选）")
        parser.add_argument("--title", type=str, default="", help="输出 EPUB 时的标题")
        parser.add_argument("--author", type=str, default="", help="输出 EPUB 时的作者")

    def execute(self, args: argparse.Namespace) -> int:
        fp = Path(args.file)
        if not fp.exists():
            msg = f"文件不存在: {args.file}"
            if self._json_mode:
                return self._respond(False, error=msg)
            logger.error(msg)
            return 1

        target = args.to.strip().lower().strip(".")
        if target not in ("txt", "epub", "pdf"):
            msg = f"不支持的目标格式: {target}，支持 txt/epub/pdf"
            if self._json_mode:
                return self._respond(False, error=msg)
            logger.error(msg)
            return 1

        output = Path(args.output) if args.output else None
        kwargs = {}
        if args.title:
            kwargs["title"] = args.title
        if args.author:
            kwargs["author"] = args.author

        try:
            if target == "txt":
                result_text = convert_to_txt(fp, output)
                if output is None:
                    output = fp.with_suffix(".txt")
                    output.write_text(result_text, encoding="utf-8")
                result_path = output
            elif target == "epub":
                result_path = convert_to_epub(fp, output, **kwargs)
            elif target == "pdf":
                result_path = convert_to_pdf(fp, output, **kwargs)
            else:
                result_path = fp
            if self._json_mode:
                return self._respond(True, data={
                    "source": str(fp),
                    "target": str(result_path),
                    "format": target,
                    "size_kb": round(result_path.stat().st_size / 1024, 2) if result_path.exists() else 0
                })
            logger.info(f"转换成功: {fp.name} → {result_path.name} ({target})")
            return 0
        except Exception as e:
            msg = str(e)
            if self._json_mode:
                return self._respond(False, error=msg)
            logger.error(f"转换失败: {msg}")
            return 1
