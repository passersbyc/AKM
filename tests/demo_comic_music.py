"""补充漫画和音乐类型的演示数据。"""
import os
import sys
import tempfile
import struct
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from src.core.database import init_db
from src.core.importer import import_one

# ── 漫画数据 (使用 .pdf 扩展名) ──
COMIC_DATA = [
    ("尾田荣一郎", "海贼王", "海贼王 卷1", "漫画,少年,日本", "路飞开启了他的海盗冒险之旅。", True, 9.6),
    ("尾田荣一郎", "海贼王", "海贼王 卷2", "漫画,少年,日本", "草帽海贼团继续伟大航路的冒险。", True, 9.5),
    ("井上雄彦", "灌篮高手", "灌篮高手 卷1", "漫画,运动,日本", "樱木花道的高中篮球之路。", True, 9.4),
    ("井上雄彦", "灌篮高手", "灌篮高手 卷2", "漫画,运动,日本", "湘北高中篮球部的全国大赛之路。", True, 9.3),
    ("谏山创", "进击的巨人", "进击的巨人 卷1", "漫画,奇幻,日本", "巨人突然来袭，人类面临灭绝危机。", True, 9.2),
    ("谏山创", "进击的巨人", "进击的巨人 卷2", "漫画,奇幻,日本", "艾伦觉醒巨人力量的真相。", True, 9.1),
    ("米二", "一人之下", "一人之下 卷1", "漫画,玄幻,国漫", "张楚岚的异人世界冒险。", True, 8.8),
    ("米二", "一人之下", "一人之下 卷2", "漫画,玄幻,国漫", "冯宝宝的真正身份逐渐揭露。", True, 8.7),
    ("蔡志忠", "", "庄子说", "漫画,哲学,国漫", "用漫画诠释庄子哲学。", False, 8.5),
    ("蔡志忠", "", "禅说", "漫画,哲学,国漫", "用漫画图解禅宗思想。", False, 8.4),
]

# ── 音乐数据 (使用 .mp3 扩展名) ──
MUSIC_DATA = [
    ("周杰伦", "范特西", "爱在西元前", "音乐,流行,周杰伦", "方文山作词，周杰伦作曲的经典之作。", True, 9.5),
    ("周杰伦", "范特西", "简单爱", "音乐,流行,周杰伦", "简单却打动人心的爱情歌曲。", True, 9.3),
    ("周杰伦", "范特西", "威廉古堡", "音乐,流行,周杰伦", "哥特风格的奇幻歌曲。", True, 9.0),
    ("周杰伦", "七里香", "七里香", "音乐,流行,周杰伦", "夏天的感觉，青春的回忆。", True, 9.4),
    ("周杰伦", "七里香", "晴天", "音乐,流行,周杰伦", "毕业季必听的伤感歌曲。", True, 9.6),
    ("林俊杰", "第二天堂", "江南", "音乐,流行,林俊杰", "一曲江南风靡大江南北。", True, 9.2),
    ("林俊杰", "第二天堂", "一千年以后", "音乐,流行,林俊杰", "跨越千年的爱情故事。", True, 9.1),
    ("林俊杰", "", "修炼爱情", "音乐,流行,林俊杰", "学会坚强面对失去的爱情。", True, 9.0),
    ("陈奕迅", "", "十年", "音乐,流行,陈奕迅", "时间是治愈一切的良药。", True, 9.7),
    ("陈奕迅", "", "富士山下", "音乐,流行,陈奕迅", "林夕作词的经典。", True, 9.5),
    ("邓丽君", "", "月亮代表我的心", "音乐,经典,邓丽君", "永恒的经典情歌。", True, 9.9),
    ("邓丽君", "", "甜蜜蜜", "音乐,经典,邓丽君", "甜蜜的爱情歌曲。", True, 9.8),
]


def create_minimal_pdf(filepath: Path, unique_data: str = ""):
    """创建最小有效 PDF 文件，附加唯一数据避免 MD5 重复。"""
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    # 通过 metadata 或临时方案注入唯一数据：直接追加到文件末尾
    # PDF 解析器会忽略 %%EOF 后的内容，但 md5 不同
    writer.write(filepath)
    with open(filepath, 'ab') as f:
        f.write(unique_data.encode('utf-8'))


def create_minimal_mp3(filepath: Path, unique_data: str = ""):
    """创建最小有效 MP3 文件，附加唯一数据避免 MD5 重复。"""
    # MPEG Audio Layer III 帧头 (128kbps, 44100Hz, stereo, no padding)
    frame_header = struct.pack(">I", 0xFFFB9004)
    frame_size = 144 * 128000 // 44100  # = 417
    frame_data = b'\x00' * (frame_size - 4)
    with open(filepath, 'wb') as f:
        f.write(frame_header + frame_data)
        # 在 MP3 数据后追加唯一数据 (ID3v1 标签区域)
        tag = b'TAG' + unique_data.encode('utf-8')[:30].ljust(30, b'\x00') + b'\x00' * 93
        f.write(tag)


def main():
    print("=" * 60)
    print("  补充漫画(c)和音乐(m)类型演示数据")
    print("=" * 60)

    init_db()
    tmpdir = Path(tempfile.mkdtemp(prefix="bkm_demo2_"))

    total_success = 0
    total_failed = 0

    # ── 导入漫画 ──
    print(f"\n[漫画] 导入 {len(COMIC_DATA)} 部漫画...")
    for author, series, title, tags, desc, fav, rating in COMIC_DATA:
        safe_name = title.replace("/", "_").replace(":", "-")
        filepath = tmpdir / f"{safe_name}.pdf"
        try:
            create_minimal_pdf(filepath, unique_data=title)
        except Exception as e:
            print(f"  ⚠ 创建PDF失败 {title}: {e}")
            continue
        result = import_one(
            file_path=str(filepath), author=author, series=series,
            tags=tags, source="demo", favorited=fav, rating=rating,
            description=desc, title=title, convert_doc=False, target_format="pdf",
        )
        if result.success:
            print(f"  ✓ [{result.book_id}] {title} — {author}")
            total_success += 1
        else:
            print(f"  ✗ {title}: {result.error}")
            total_failed += 1

    # ── 导入音乐 ──
    print(f"\n[音乐] 导入 {len(MUSIC_DATA)} 首音乐...")
    for author, series, title, tags, desc, fav, rating in MUSIC_DATA:
        safe_name = title.replace("/", "_").replace(":", "-")
        filepath = tmpdir / f"{safe_name}.mp3"
        try:
            create_minimal_mp3(filepath, unique_data=title)
        except Exception as e:
            print(f"  ⚠ 创建MP3失败 {title}: {e}")
            continue
        result = import_one(
            file_path=str(filepath), author=author, series=series,
            tags=tags, source="demo", favorited=fav, rating=rating,
            description=desc, title=title, convert_doc=False, target_format="mp3",
        )
        if result.success:
            print(f"  ✓ [{result.book_id}] {title} — {author}")
            total_success += 1
        else:
            print(f"  ✗ {title}: {result.error}")
            total_failed += 1

    # 清理
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    print(f"\n{'=' * 60}")
    print(f"  补充完成: 成功 {total_success}, 失败 {total_failed}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
