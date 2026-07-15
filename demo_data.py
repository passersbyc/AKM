"""生成演示数据脚本 — 创建虚拟书籍文件并导入库中。"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from src.core.database import init_db, get_db
from src.core.importer import import_one
from src.core.work_manager import WorkManager
from src.core.author_manager import register
from src.core.logging import get_logger

_log = get_logger("akm.demo")

# ── 演示书籍数据 ──
# (作者, 系列, 标题, 标签, 简介, 收藏, 评分, 内容片段)
DEMO_BOOKS = [
    # === 金庸 ===
    ("金庸", "射雕英雄传", "射雕英雄传", "武侠,经典,金庸", "南宋年间，郭靖与黄蓉的传奇故事。", True, 9.5,
     "钱塘江浩浩江水，日日夜夜无穷无休的从临安牛家村边绕过，东流入海。江畔一排数十株乌桕树，叶子似火烧般红。"),
    ("金庸", "射雕英雄传", "神雕侠侣", "武侠,经典,金庸", "杨过与小龙女的爱情传奇。", True, 9.3,
     "「问世间，情为何物，直教生死相许？」这曲《摸鱼儿》，是金人元好问的名篇。"),
    ("金庸", "射雕英雄传", "倚天屠龙记", "武侠,经典,金庸", "张无忌的江湖恩怨与儿女情长。", True, 9.0,
     "春游浩荡，是年年寒食，梨花时节。白锦无纹香烂漫，玉树琼苞堆雪。"),
    ("金庸", "天龙八部", "天龙八部", "武侠,经典,金庸", "段誉、乔峰、虚竹三人的命运交织。", True, 9.7,
     "青光闪动，一柄青钢剑倏地刺出，指向中年汉子左肩，使剑少年不等剑招用老，腕抖剑斜。"),
    ("金庸", "天龙八部", "笑傲江湖", "武侠,经典,金庸", "令狐冲与任盈盈的江湖故事。", True, 9.4,
     "和风熏柳，花香醉人，正是南国春光烂漫季节。福建省福州府西门大街，青石板路笔直的伸展出去。"),
    ("金庸", "", "鹿鼎记", "武侠,经典,金庸", "韦小宝的传奇人生。", True, 9.2,
     "北风如刀，满地冰霜。江南近海滨的一条大路上，一队清兵手执刀枪，押着七辆囚车，冲风冒寒向北而行。"),

    # === 刘慈欣 ===
    ("刘慈欣", "三体", "三体", "科幻,经典,雨果奖", "文化大革命如火如荼进行的同时，军方探寻外星文明的绝秘计划「红岸工程」取得了突破性进展。", True, 9.8,
     "汪淼觉得，来找他的这四个人是一个奇怪的组合：两名警察和两名军人。"),
    ("刘慈欣", "三体", "三体II：黑暗森林", "科幻,经典,雨果奖", "三体人在利用魔法般的科技锁死了地球人的科学之后，庞大的宇宙舰队开始向地球进发。", True, 9.6,
     "褐蚁已经忘记这里曾是它的家园。这段时光对于暮色中的大地和刚刚出现的星星来说短得可以忽略不计。"),
    ("刘慈欣", "三体", "三体III：死神永生", "科幻,经典,雨果奖", "与三体文明的战争使人类第一次看到了宇宙黑暗的真相。", True, 9.5,
     "「万有引力」号上的心理医生韦斯特，正坐在办公室里的沙发上翻看着一本旧杂志。"),
    ("刘慈欣", "", "流浪地球", "科幻,电影原著", "太阳即将毁灭，人类在地球表面建造出巨大的推进器，寻找新的家园。", False, 8.8,
     "我没见过黑夜，我没见过星星，我没见过春天、秋天和冬天。我出生在刹车时代结束的时候。"),

    # === 余华 ===
    ("余华", "", "活着", "文学,经典,苦难", "地主少爷富贵嗜赌成性，终于赌光了家业一贫如洗。", True, 9.9,
     "我比现在年轻十岁的时候，获得了一个游手好闲的职业，去乡间收集民间歌谣。"),
    ("余华", "", "许三观卖血记", "文学,经典", "许三观靠着卖血渡过了人生的一个个难关。", True, 9.3,
     "许三观坐在他家的门槛上，吃着许玉兰给他做的午饭。饭是白米饭，菜是新鲜的青菜。"),
    ("余华", "", "兄弟", "文学,现实", "讲述了江南小镇两兄弟李光头和宋钢的一生。", True, 9.0,
     "我们刘镇的超级巨富李光头异想天开，打算花两千万美元买一个俄罗斯太空船。"),

    # === 东野圭吾 ===
    ("东野圭吾", "伽利略系列", "嫌疑人X的献身", "推理,悬疑,日本", "数学天才石神为保护邻居花冈靖子，设下了一个匪夷所思的局。", True, 9.4,
     "上午七点三十五分，石神像往常一样走出家门。虽已进入三月，风还是相当冷。"),
    ("东野圭吾", "伽利略系列", "圣女的救济", "推理,悬疑,日本", "周日晚上七点，真柴义孝在自己家中被毒杀。", True, 8.7,
     "真柴义孝的死，让汤川学感到一种难以言喻的不协调感。"),
    ("东野圭吾", "", "白夜行", "推理,悬疑,日本,经典", "一宗离奇命案牵出跨度近20年的步步惊心的故事。", True, 9.5,
     "出了近铁布施站，沿着铁路径直向西。已经十月了，天气仍闷热难当。"),
    ("东野圭吾", "", "解忧杂货店", "文学,奇幻,日本", "僻静的街道旁有一家杂货店，只要写下烦恼投进卷帘门的投信口，第二天就会在店后的牛奶箱里得到回答。", True, 9.1,
     "「贵之，你要好好想想。这可是你自己的事。」父亲雄治的声音从电话另一头传来。"),

    # === 其他 ===
    ("马伯庸", "", "长安十二时辰", "历史,悬疑,唐朝", "唐天宝三年，元月十四日，长安。上元节辉煌灯火亮起之时，等待他们的，将是场吞噬一切的劫难。", True, 8.9,
     "天宝三载，元月十四日，巳正。长安城，一百零八坊，如棋盘般严整。"),
    ("马伯庸", "", "古董局中局", "悬疑,鉴宝,系列", "古董造假、字画仿冒，古玩市场的种种阴谋。", False, 8.5,
     "我爷爷死的时候，留下了一个天大的秘密。"),
]


def create_demo_files():
    tmpdir = Path(tempfile.mkdtemp(prefix="bkm_demo_"))
    files = []
    for author, series, title, tags, desc, fav, rating, content in DEMO_BOOKS:
        safe_name = title.replace("/", "_").replace("：", "-").replace(":", "-")
        filepath = tmpdir / f"{safe_name}.txt"
        filepath.write_text(content, encoding="utf-8")
        files.append((str(filepath), author, series, title, tags, desc, fav, rating))
    return tmpdir, files


def main():
    print("=" * 60)
    print("  作品管理系统 (akm) — 演示数据导入")
    print("=" * 60)

    # 初始化数据库
    init_db()
    print("\n[1/3] 初始化数据库... 完成")

    # 创建临时文件
    tmpdir, files = create_demo_files()
    print(f"[2/3] 创建 {len(files)} 个演示文件到临时目录... 完成")

    # 导入
    print(f"\n[3/3] 开始导入 {len(files)} 本书籍...\n")
    success = 0
    failed = 0
    for filepath, author, series, title, tags, desc, fav, rating in files:
        try:
            result = import_one(
                file_path=filepath,
                author=author,
                series=series,
                tags=tags,
                source="demo",
                favorited=fav,
                rating=rating,
                description=desc,
                title=title,
                convert_doc=False,
                target_format="txt",
            )
            if result.success:
                print(f"  ✓ [{result.book_id}] {title} — {author}")
                success += 1
            else:
                print(f"  ✗ {title}: {result.error}")
                failed += 1
        except Exception as e:
            print(f"  ✗ {title}: {e}")
            failed += 1

    # 统计
    print(f"\n{'=' * 60}")
    stats = WorkManager.get_stats()
    print(f"  导入完成: 成功 {success}, 失败 {failed}")
    print(f"  库内作品总数: {stats.get('作品数', '?')}")
    print(f"  库内作者数:   {stats.get('作者数', '?')}")
    print(f"  库内系列数:   {stats.get('系列数', '?')}")
    print(f"{'=' * 60}")

    # 清理临时文件
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
