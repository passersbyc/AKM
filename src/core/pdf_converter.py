"""PDF 转换模块。"""

import io
import subprocess
from pathlib import Path


def convert_to_pdf(file_path: Path, output_path: Path = None, **kwargs) -> Path:
    suffix = file_path.suffix.lower()
    if output_path is None:
        output_path = file_path.with_suffix(".pdf")

    if suffix in (".docx", ".doc"):
        try:
            result = subprocess.run(
                ["pandoc", str(file_path), "-o", str(output_path), "--pdf-engine=xelatex"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                return output_path
        except Exception:
            pass

        try:
            import platform
            if platform.system() == "Darwin":
                subprocess.run(
                    ["textutil", "-convert", "html", str(file_path), "-output", "/tmp/bkm_convert.html"],
                    capture_output=True, timeout=30,
                )
                subprocess.run(
                    ["pandoc", "/tmp/bkm_convert.html", "-o", str(output_path), "--pdf-engine=xelatex"],
                    capture_output=True, timeout=60,
                )
                return output_path
        except Exception:
            pass
        raise RuntimeError("DOCX/DOC 转 PDF 需要 pandoc + xelatex")

    elif suffix == ".txt":
        try:
            result = subprocess.run(
                ["pandoc", str(file_path), "-o", str(output_path), "--pdf-engine=xelatex"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                return output_path
        except Exception:
            pass

        from pypdf import PdfWriter
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4

        writer = PdfWriter()
        text = file_path.read_text(encoding="utf-8")
        lines = text.split("\n")
        chunk = []
        for line in lines:
            chunk.append(line)
            if len(chunk) >= 60:
                buf = io.BytesIO()
                c = canvas.Canvas(buf, pagesize=A4)
                y = 800
                for ln in chunk:
                    c.drawString(50, y, ln[:80])
                    y -= 14
                    if y < 50:
                        c.showPage()
                        y = 800
                c.save()
                buf.seek(0)
                from pypdf import PdfReader
                temp_reader = PdfReader(buf)
                for page in temp_reader.pages:
                    writer.add_page(page)
                chunk = []
        if chunk:
            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=A4)
            y = 800
            for ln in chunk:
                c.drawString(50, y, ln[:80])
                y -= 14
            c.save()
            buf.seek(0)
            from pypdf import PdfReader
            temp_reader = PdfReader(buf)
            for page in temp_reader.pages:
                writer.add_page(page)
        with open(output_path, "wb") as f:
            writer.write(f)
        return output_path

    elif suffix in ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'):
        from PIL import Image
        from pypdf import PdfWriter
        img = Image.open(file_path)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        buf = io.BytesIO()
        img.save(buf, format='PDF')
        buf.seek(0)
        from pypdf import PdfReader
        reader = PdfReader(buf)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        with open(output_path, "wb") as f:
            writer.write(f)
        return output_path

    else:
        raise ValueError(f"不支持的源格式转 PDF: {suffix}")
