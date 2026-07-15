"""补充电影(f)和美图集(i)类型的演示数据。"""
import os
import sys
import tempfile
import struct
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from src.core.database import init_db
from src.core.importer import import_one

# ── 电影数据 (使用 .mp4 扩展名) ──
MOVIE_DATA = [
    ("宫崎骏", "吉卜力", "千与千寻", "电影,动画,日本,宫崎骏", "少女千寻误入神灵世界，以勇气与善良找回自我与父母。", True, 9.8),
    ("宫崎骏", "吉卜力", "龙猫", "电影,动画,日本,宫崎骏", "姐妹俩在乡间遇到森林精灵龙猫的温馨故事。", True, 9.5),
    ("宫崎骏", "吉卜力", "天空之城", "电影,动画,日本,宫崎骏", "少年巴鲁与少女希达寻找传说中天空之城拉普达的冒险。", True, 9.3),
    ("诺兰", "", "盗梦空间", "电影,科幻,美国", "柯布是一名技术高超的盗梦者，接受了一项不可能的任务——植入思想。", True, 9.6),
    ("诺兰", "", "星际穿越", "电影,科幻,美国", "未来的地球面临粮食危机，一群探险家穿越虫洞寻找人类的新家园。", True, 9.7),
    ("诺兰", "", "蝙蝠侠：黑暗骑士", "电影,动作,美国,超级英雄", "蝙蝠侠与小丑之间的终极对决。", True, 9.4),
    ("饺子", "", "哪吒之魔童降世", "电影,动画,国漫", "我命由我不由天——哪吒对抗命运的故事。", True, 9.2),
    ("郭帆", "", "流浪地球", "电影,科幻,国产", "太阳即将毁灭，人类带着地球逃离太阳系。", True, 9.0),
    ("张艺谋", "", "活着", "电影,剧情,国产", "改编自余华同名小说，讲述福贵坎坷的一生。", True, 9.3),
    ("张艺谋", "", "大红灯笼高高挂", "电影,剧情,国产", "颂莲嫁入陈家大院，在妻妾争斗中迷失自我。", True, 9.1),
]

# ── 美图集数据 (使用 .jpg 扩展名) ──
IMAGE_DATA = [
    ("wlop", "鬼刀", "鬼刀 第1话", "美图,插画,奇幻", "冰公主与守护骑士的奇幻世界。", True, 9.5),
    ("wlop", "鬼刀", "鬼刀 第2话", "美图,插画,奇幻", "海琴烟的冒险继续。", True, 9.4),
    ("wlop", "鬼刀", "鬼刀 第3话", "美图,插画,奇幻", "风铃与北漠之战的序幕。", True, 9.4),
    ("黄光剑", "", "十二星座-白羊", "美图,CG,星座", "白羊座概念设计插画。", False, 8.8),
    ("黄光剑", "", "十二星座-金牛", "美图,CG,星座", "金牛座概念设计插画。", False, 8.7),
    ("黄光剑", "", "十二星座-双子", "美图,CG,星座", "双子座概念设计插画。", False, 8.9),
    ("杉泽", "", "观山海-九尾狐", "美图,水墨,山海经", "山海经异兽九尾狐水墨插画。", True, 9.3),
    ("杉泽", "", "观山海-凤凰", "美图,水墨,山海经", "山海经神兽凤凰水墨插画。", True, 9.6),
    ("新海诚", "你的名字", "你的名字 原画集1", "美图,动画,日本,原画", "三叶与泷的相遇——原画设定集。", True, 9.2),
    ("新海诚", "你的名字", "你的名字 原画集2", "美图,动画,日本,原画", "糸守湖的黄昏——原画设定集。", True, 9.1),
]


def create_minimal_mp4(filepath: Path, unique_data: str = ""):
    """创建最小有效 MP4 文件。"""
    # ftyp box + moov box (最小可用)
    ftyp = b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42mp41'
    # moov box with empty track
    moov = b'\x00\x00\x00\x08moov'
    data = ftyp + moov + unique_data.encode('utf-8')
    filepath.write_bytes(data)


def create_minimal_jpg(filepath: Path, unique_data: str = ""):
    """创建最小有效 JPG 文件 (1x1 像素)。"""
    # Minimal valid JPEG (1x1 black pixel)
    # SOI, APP0(JFIF), DQT, SOF0, DHT, SOS, image data, EOI
    jpg = bytes([
        0xFF, 0xD8,  # SOI
        0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00,  # APP0/JFIF
        0xFF, 0xDB, 0x00, 0x43, 0x00,  # DQT
        0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09, 0x09,
        0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12, 0x13,
        0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20, 0x24,
        0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29, 0x2C,
        0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32, 0x3C,
        0x2E, 0x33, 0x34, 0x32,
        0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01, 0x00, 0x01, 0x01, 0x01, 0x11, 0x00,  # SOF0
        0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00, 0x01, 0x05, 0x01, 0x01, 0x01, 0x01,  # DHT
        0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x02,
        0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B,
        0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F, 0x00, 0x7F, 0x00,  # SOS
        0xFF, 0xD9,  # EOI
    ])
    data = jpg + unique_data.encode('utf-8')
    filepath.write_bytes(data)


def main():
    print("=" * 60)
    print("  补充电影(f)和美图集(i)类型演示数据")
    print("=" * 60)

    init_db()
    tmpdir = Path(tempfile.mkdtemp(prefix="bkm_demo3_"))

    total_success = 0
    total_failed = 0

    # ── 导入电影 ──
    print(f"\n[电影] 导入 {len(MOVIE_DATA)} 部电影...")
    for author, series, title, tags, desc, fav, rating in MOVIE_DATA:
        safe_name = title.replace("/", "_").replace(":", "-")
        filepath = tmpdir / f"{safe_name}.mp4"
        try:
            create_minimal_mp4(filepath, unique_data=title)
        except Exception as e:
            print(f"  ⚠ 创建MP4失败 {title}: {e}")
            continue
        result = import_one(
            file_path=str(filepath), author=author, series=series,
            tags=tags, source="demo", favorited=fav, rating=rating,
            description=desc, title=title, convert_doc=False, target_format="mp4",
        )
        if result.success:
            print(f"  ✓ [{result.book_id}] {title} — {author}")
            total_success += 1
        else:
            print(f"  ✗ {title}: {result.error}")
            total_failed += 1

    # ── 导入美图集 ──
    print(f"\n[美图集] 导入 {len(IMAGE_DATA)} 张美图...")
    for author, series, title, tags, desc, fav, rating in IMAGE_DATA:
        safe_name = title.replace("/", "_").replace(":", "-")
        filepath = tmpdir / f"{safe_name}.jpg"
        try:
            create_minimal_jpg(filepath, unique_data=title)
        except Exception as e:
            print(f"  ⚠ 创建JPG失败 {title}: {e}")
            continue
        result = import_one(
            file_path=str(filepath), author=author, series=series,
            tags=tags, source="demo", favorited=fav, rating=rating,
            description=desc, title=title, convert_doc=False, target_format="jpg",
        )
        if result.success:
            print(f"  ✓ [{result.book_id}] {title} — {author}")
            total_success += 1
        else:
            print(f"  ✗ {title}: {result.error}")
            total_failed += 1

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    print(f"\n{'=' * 60}")
    print(f"  补充完成: 成功 {total_success}, 失败 {total_failed}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
