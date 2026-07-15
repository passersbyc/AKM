"""cdbook.py 域逻辑纯函数测试。"""
import pytest
from src.domain.cdbook import normalize_series_name, parse_cdbook_filename, detect_cdbook_series


class TestNormalizeSeriesName:
    def test_empty(self):
        assert normalize_series_name("") == ""

    def test_strip_whitespace(self):
        assert normalize_series_name("  系列一  ") == "系列一"

    def test_fullwidth_conversion(self):
        result = normalize_series_name("hello:world")
        assert result == "hello：world"

    def test_multiple_fullwidth(self):
        result = normalize_series_name("a/b<c>d")
        assert "／" in result
        assert "＜" in result
        assert "＞" in result

    def test_whitespace_collapse(self):
        result = normalize_series_name("hello   world")
        assert result == "helloworld"


class TestParseCdbookFilename:
    def test_simple_title(self):
        r = parse_cdbook_filename("我的故事.epub")
        assert r["title"] == "我的故事"
        assert r["tag"] == ""

    def test_tag_extraction(self):
        r = parse_cdbook_filename("[Pixiv]我的故事.epub")
        assert r["tag"] == "Pixiv"
        assert "我的故事" in r["title"]

    def test_multiple_tags(self):
        r = parse_cdbook_filename("[Pixiv][漫画]我的故事.epub")
        assert r["tag"] == "Pixiv"
        assert "漫画" in r["extra_tags"]

    def test_chinese_brackets(self):
        r = parse_cdbook_filename("我的故事【番外】.epub")
        assert "番外" in r["extra_tags"]

    def test_chapter_number(self):
        r = parse_cdbook_filename("故事 第3章.epub")
        assert r["chapter"] == "3"
        assert r["order"] == "3"

    def test_chapter_chinese(self):
        r = parse_cdbook_filename("故事 第三章.epub")
        assert r["chapter"] == "三"
        assert r["order"] == "3"

    def test_chapter_range(self):
        r = parse_cdbook_filename("故事 (1-10)章.epub")
        assert r["chapter"] == "1-10"
        assert r["order"] == "1"

    def test_status_complete(self):
        r = parse_cdbook_filename("我的故事(完).epub")
        assert r["status"] == "完"

    def test_status_end(self):
        r = parse_cdbook_filename("我的故事(END).epub")
        assert r["status"] == "END"

    def test_fallback_tag(self):
        r = parse_cdbook_filename("我的故事.epub", fallback_tag="Pixiv")
        assert r["tag"] == "Pixiv"

    def test_hidden_file(self):
        r = parse_cdbook_filename(".hidden.epub")
        assert r["title"] == "hidden"

    def test_trailing_number(self):
        r = parse_cdbook_filename("故事 5.epub")
        assert r["order"] == "5"


class TestDetectCdbookSeries:
    def test_no_series(self):
        metas = [
            {"title": "完全不同的故事", "series": "", "order": ""},
            {"title": "毫无关联的冒险", "series": "", "order": ""},
        ]
        detect_cdbook_series(metas)
        assert metas[0]["series"] == ""
        assert metas[1]["series"] == ""

    def test_common_prefix_series(self):
        metas = [
            {"title": "魔法少女 第1章", "series": "", "order": "1", "chapter": "1"},
            {"title": "魔法少女 第2章", "series": "", "order": "2", "chapter": "2"},
            {"title": "魔法少女 第3章", "series": "", "order": "3", "chapter": "3"},
        ]
        detect_cdbook_series(metas)
        series_names = {m["series"] for m in metas}
        # At least 2 should share a series
        non_empty = [s for s in series_names if s]
        assert len(non_empty) >= 1

    def test_single_file_no_series(self):
        metas = [{"title": "独立作品", "series": "", "order": ""}]
        detect_cdbook_series(metas)
        assert metas[0]["series"] == ""
