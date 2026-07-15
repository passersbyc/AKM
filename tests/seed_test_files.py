#!/usr/bin/env python3
"""生成测试书籍文件 — 供 test_chain.py 和手动测试使用。

用法:
  python3 tests/seed_test_files.py                          # 默认输出到 tests/fixtures/
  python3 tests/seed_test_files.py /path/to/output_dir      # 自定义输出目录
  python3 tests/seed_test_files.py --clean                   # 清理生成的测试文件

生成内容:
  - 小说类: 3 个 .txt (含系列/无系列)
  - 小说类: 2 个 .epub (真实 EPUB 结构)
  - 漫画类: 2 个 .pdf (含封面页)
  - 音乐类: 1 个 .mp3 (最小有效 MP3)
  - 电影类: 1 个 .mp4 (最小 MP4 占位)
  - 美图集: 2 个 .jpg (含像素数据)
  - cdbook 目录: 含 3 个 .docx (Word 文档结构)

测试元数据通过文件名约定，配合 test_chain.py 的 --author/--series/--tags 参数使用。
"""
import argparse
import os
import shutil
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

# ── 测试书籍数据 ──────────────────────────────────────────
# (文件名, 分类, 内容/生成方式, 简介)
TEST_BOOKS = [
    # 小说 - txt
    ("novel_射雕英雄传.txt", "小说", "钱塘江浩浩江水，日日夜夜无穷无休的从临安牛家村边绕过，东流入海。\n" * 5, "南宋年间，郭靖与黄蓉的传奇故事。"),
    ("novel_神雕侠侣.txt", "小说", "问世间，情为何物，直教生死相许？\n" * 5, "杨过与小龙女的爱情传奇。"),
    ("novel_三体.txt", "小说", "汪淼觉得，来找他的这四个人是一个奇怪的组合。\n" * 5, "军方探寻外星文明的绝秘计划。"),
    # 小说 - epub
    ("novel_活着.epub", "小说", "EPUB", "地主少爷富贵嗜赌成性，终于赌光了家业。"),
    ("novel_白夜行.epub", "小说", "EPUB", "一宗离奇命案牵出跨度近20年的故事。"),
    # 漫画 - pdf
    ("comic_龙珠.pdf", "漫画", "PDF", "孙悟空寻找七龙珠的冒险。"),
    ("comic_海贼王.pdf", "漫画", "PDF", "路飞成为海贼王的旅程。"),
    # 美图集 - jpg
    ("images_风景1.jpg", "美图集", "JPG", "风景图集第一张。"),
    ("images_风景2.jpg", "美图集", "JPG", "风景图集第二张。"),
    # 音乐 - mp3
    ("music_月光曲.mp3", "音乐", "MP3", "贝多芬月光奏鸣曲。"),
    # 电影 - mp4
    ("movie_千与千寻.mp4", "电影", "MP4", "宫崎骏动画电影。"),
]

# cdbook 目录内容
CDBOOK_FILES = [
    ("cdbook_第一章_觉醒.docx", "小说", "DOCX", "主角在黑暗中睁开双眼。"),
    ("cdbook_第二章_启程.docx", "小说", "DOCX", "主角踏上未知的旅程。"),
    ("cdbook_第三章_归途.docx", "小说", "DOCX", "历经千辛万苦，主角终于回家。"),
]


def _make_minimal_epub(path: Path, title: str, content: str) -> None:
    """生成最小有效 EPUB（含 mimetype + container.xml + content.opf + chapter.xhtml）。"""
    mimetype = b"application/epub+zip"
    container_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''
    content_opf = f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="BookId">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:language>zh</dc:language>
    <dc:identifier id="BookId">test-{title}</dc:identifier>
  </metadata>
  <manifest>
    <item id="chapter1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter1"/>
  </spine>
</package>'''
    chapter = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{title}</title></head>
<body><h1>{title}</h1><p>{content}</p></body>
</html>'''
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", content_opf)
        zf.writestr("OEBPS/chapter1.xhtml", chapter)


def _make_minimal_pdf(path: Path, title: str) -> None:
    """生成最小有效 PDF（单页含标题文字）。"""
    content_stream = f"BT /F1 24 Tf 72 700 Td ({title}) Tj ET"
    pdf = f"""%PDF-1.4
1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj
2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj
3 0 obj <</Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>> endobj
4 0 obj <</Length {len(content_stream)}>> stream
{content_stream}
endstream endobj
5 0 obj <</Type /Font /Subtype /Type1 /BaseFont /Helvetica>> endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000232 00000 n
0000000300 00000 n
trailer <</Size 6 /Root 1 0 R>>
startxref
366
%%EOF"""
    path.write_text(pdf, encoding="utf-8")


def _make_minimal_jpg(path: Path, width: int = 100, height: int = 100) -> None:
    """生成最小有效 JPEG（纯色像素）。"""
    # SOI + APP0 + SOF0 + DQT + DHT + SOS + EOI (最小灰度 JPEG)
    SOI = b"\xff\xd8"
    APP0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    SOF0 = (b"\xff\xc0" + struct.pack(">H", 11) + b"\x08"
            + struct.pack(">HH", height, width) + b"\x03\x01\x11\x00")
    # 量化表 (简化)
    DQT = b"\xff\xdb" + struct.pack(">H", 67) + b"\x00" + bytes([8] * 64)
    # 哈夫曼表 (简化 DC)
    DHT = b"\xff\xc4" + struct.pack(">H", 31) + b"\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b"
    # 扫描头 + 数据 (最小)
    SOS = b"\xff\xda" + struct.pack(">H", 12) + b"\x03\x01\x00\x11\x00\x11\x00\x3f\x00"
    EOI = b"\xff\xd9"
    # 最小扫描数据：一个 8x8 块的 DC 系数 0 + EOB
    scan_data = b"\x00" * 8
    path.write_bytes(SOI + APP0 + SOF0 + DQT + DHT + SOS + scan_data + EOI)


def _make_minimal_mp3(path: Path, title: str) -> None:
    """生成最小有效 MP3（ID3v2 头 + 1 帧静音）。"""
    # ID3v2.3 头
    title_bytes = title.encode("utf-8")
    id3_header = b"ID3\x03\x00\x00"
    # 标题帧
    title_frame_data = title_bytes + b"\x00"
    title_frame = b"TIT2" + struct.pack(">I", len(title_frame_data)) + b"\x00\x00" + title_frame_data
    # ID3 总大小（同步安全整数）
    total_size = len(title_frame)
    size_bytes = struct.pack(">I", ((total_size & 0x7F) | ((total_size & 0x3F80) << 1) | ((total_size & 0x1FC000) << 2) | ((total_size & 0xFE00000) << 3)))
    # MP3 帧：MPEG1 Layer3 128kbps 44100Hz（帧头 0xFFFB9004）
    frame_header = b"\xff\xfb\x90\x04"
    frame_data = b"\x00" * 412  # 128kbps 帧大小约 417 字节
    path.write_bytes(id3_header + size_bytes + title_frame + frame_header + frame_data)


def _make_minimal_mp4(path: Path) -> None:
    """生成最小 MP4 占位（ftyp box）。"""
    ftyp = b"ftypisom\x00\x00\x02\x00isomiso2"
    box_size = struct.pack(">I", 8 + len(ftyp))
    path.write_bytes(box_size + ftyp)


def _make_minimal_docx(path: Path, title: str, content: str) -> None:
    """生成最小有效 DOCX（含 document.xml）。"""
    document_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{title}</w:t></w:r></w:p>
    <w:p><w:r><w:t>{content}</w:t></w:r></w:p>
  </w:body>
</w:document>'''
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>'''
    rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''
    word_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
</Relationships>'''
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/_rels/document.xml.rels", word_rels)


def _generate_book(path: Path, filename: str, category: str, fmt: str, desc: str) -> None:
    """根据格式生成单个测试文件。"""
    title = Path(filename).stem
    if fmt == "EPUB":
        _make_minimal_epub(path, title, desc)
    elif fmt == "PDF":
        _make_minimal_pdf(path, title)
    elif fmt == "JPG":
        _make_minimal_jpg(path)
    elif fmt == "MP3":
        _make_minimal_mp3(path, title)
    elif fmt == "MP4":
        _make_minimal_mp4(path)
    elif fmt == "DOCX":
        _make_minimal_docx(path, title, desc)
    else:  # txt
        path.write_text(f"{title}\n\n{desc}\n\n正文内容：这是测试文件 {filename}。\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成测试书籍文件")
    parser.add_argument("output_dir", nargs="?", default="tests/fixtures",
                        help="输出目录（默认 tests/fixtures）")
    parser.add_argument("--clean", action="store_true", help="清理输出目录后退出")
    args = parser.parse_args()

    out_dir = Path(args.output_dir).resolve()
    if args.clean:
        if out_dir.exists():
            shutil.rmtree(out_dir)
            print(f"已清理: {out_dir}")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    cdbook_dir = out_dir / "cdbook"
    cdbook_dir.mkdir(exist_ok=True)

    generated = 0
    print(f"生成测试文件到: {out_dir}\n")

    # 主测试文件
    for filename, category, fmt, desc in TEST_BOOKS:
        path = out_dir / filename
        _generate_book(path, filename, category, fmt, desc)
        size = path.stat().st_size
        print(f"  [+] {filename:<30} {category:<6} {size:>8} bytes")
        generated += 1

    # cdbook 目录
    print(f"\n  cdbook 目录: {cdbook_dir}")
    for filename, category, fmt, desc in CDBOOK_FILES:
        path = cdbook_dir / filename
        _generate_book(path, filename, category, fmt, desc)
        size = path.stat().st_size
        print(f"    [+] {filename:<32} {size:>8} bytes")
        generated += 1

    # 统计
    by_ext = {}
    for f in out_dir.rglob("*"):
        if f.is_file():
            ext = f.suffix.lower()
            by_ext[ext] = by_ext.get(ext, 0) + 1

    print(f"\n{'─' * 50}")
    print(f"生成完成: {generated} 个文件")
    print(f"分类统计: {', '.join(f'{k}={v}' for k, v in sorted(by_ext.items()))}")
    print(f"\n用法示例:")
    print(f"  # 运行测试链路")
    print(f"  python3 tests/test_chain.py {out_dir}")
    print(f"  # 手动导入测试")
    print(f"  python3 run.py import {out_dir}/novel_三体.txt --author 测试作者 --yes")
    print(f"  # cdbook 批量导入")
    print(f"  python3 run.py import {cdbook_dir} --author 测试作者 --yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
