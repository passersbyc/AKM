"""DOCX / DOC → TXT 转换模块。"""

import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from src.core.logging import logger


def _extract_visible_text_from_docx(docx_path: Path) -> str:
    import xml.etree.ElementTree as ET

    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

    with zipfile.ZipFile(str(docx_path)) as z:
        with z.open('word/document.xml') as f:
            tree = ET.parse(f)

    paragraphs = []

    for wp in tree.findall('.//w:p', ns):
        current_text = []

        for child in wp:
            tag = child.tag.split('}')[-1]
            if tag != 'r':
                continue

            is_hidden = False
            rpr = child.find('w:rPr', ns)
            if rpr is not None:
                vanish = rpr.find('w:vanish', ns)
                if vanish is not None:
                    is_hidden = True
                color = rpr.find('w:color', ns)
                if color is not None:
                    val = color.get('{%s}val' % ns['w'], '')
                    if len(val) == 6:
                        r_val = int(val[0:2], 16)
                        g_val = int(val[2:4], 16)
                        b_val = int(val[4:6], 16)
                        if r_val > 240 and g_val > 240 and b_val > 240:
                            is_hidden = True

            if is_hidden:
                continue

            for sub in child:
                subtag = sub.tag.split('}')[-1]
                if subtag == 'br':
                    current_text.append(' ')
                elif subtag == 't':
                    if sub.text:
                        current_text.append(sub.text)

        text = ''.join(current_text).strip()
        if text:
            paragraphs.append(text)

    return '\n\n'.join(paragraphs)


def convert_docx_to_txt(docx_path: Path, output_path: Path = None) -> str:
    try:
        from markitdown import MarkItDown
        md = MarkItDown()
        result = md.convert(str(docx_path))
        text = result.text_content.strip()
        if text:
            if output_path:
                output_path.write_text(text, encoding="utf-8")
            return text
    except Exception:
        pass

    text = _extract_visible_text_from_docx(docx_path)
    if not text:
        try:
            from docx import Document
            doc = Document(str(docx_path))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            text = "\n\n".join(paragraphs)
        except Exception as e:
            raise RuntimeError(f"DOCX 转 TXT 失败: {e}")
    if output_path:
        output_path.write_text(text, encoding="utf-8")
    return text


def _reflow_cdbook_text(text: str) -> str:
    text = re.sub(r'\n{2,}', '\n\n', text)
    if '\n\n' in text:
        return text
    text = re.sub(r'\s{2,}', ' ', text)
    text = re.sub(r'\s*(-{3,}|\*{3,}|[\u00d7\u2715\u2716\u2717]{3,}|\u203b{2,}|\u2500{3,})\s*', r'\n\n\1\n\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def convert_doc_to_txt(doc_path: Path, output_path: Path = None) -> str:
    text = ""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp_docx = Path(tmp.name)

    try:
        result = subprocess.run(
            ["textutil", "-convert", "docx", str(doc_path), "-output", str(tmp_docx)],
            capture_output=True, timeout=30
        )
        if result.returncode == 0 and tmp_docx.exists():
            text = _extract_visible_text_from_docx(tmp_docx)
    except Exception:
        pass
    finally:
        try:
            tmp_docx.unlink()
        except Exception:
            pass

    if not text:
        result = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(doc_path)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            text = result.stdout.strip()
            text = text.replace("\u2028", "\n")
            text = _reflow_cdbook_text(text)

    if not text:
        raise RuntimeError(f"DOC 转 TXT 失败: 无法提取文本")

    text = _reflow_cdbook_text(text)

    if output_path:
        output_path.write_text(text, encoding="utf-8")
    return text


def convert_to_txt(file_path: Path, output_path: Path = None) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".docx":
        return convert_docx_to_txt(file_path, output_path)
    elif suffix == ".doc":
        return convert_doc_to_txt(file_path, output_path)
    elif suffix in (".txt", ".md", ".markdown"):
        text = file_path.read_text(encoding="utf-8")
        if output_path and output_path != file_path:
            output_path.write_text(text, encoding="utf-8")
        return text
    elif suffix == ".pdf":
        raise ValueError(f"不支持的格式: {suffix}")
    else:
        raise ValueError(f"不支持的格式: {suffix}，支持 .docx/.doc/.txt/.md")
