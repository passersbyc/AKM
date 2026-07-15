"""database.py 纯函数测试。"""
import sqlite3
import pytest
from src.core.database import (
    _to_base36, short_id, to_full_id, _get_type_char,
    author_folder_name, series_folder_name, work_file_prefix,
    dict_from_row, dicts_from_rows,
)


class TestToBase36:
    def test_zero(self):
        assert _to_base36(0, 3) == "000"

    def test_zero_length_4(self):
        assert _to_base36(0, 4) == "0000"

    def test_small_number(self):
        assert _to_base36(1, 3) == "001"
        assert _to_base36(35, 3) == "00z"

    def test_medium_number(self):
        assert _to_base36(36, 3) == "010"
        assert _to_base36(1295, 3) == "0zz"

    def test_large_number(self):
        result = _to_base36(1296, 3)
        assert result == "100"

    def test_padding(self):
        assert _to_base36(1, 5) == "00001"
        assert _to_base36(0, 1) == "0"


class TestShortId:
    def test_empty(self):
        assert short_id("") == ""

    def test_short_passthrough(self):
        assert short_id("abc") == "abc"

    def test_full_id_conversion(self):
        assert short_id("a001000001") == "a.1.0.1"

    def test_full_id_all_zeros(self):
        assert short_id("n000000000") == "n.0.0.0"

    def test_full_id_with_letters(self):
        assert short_id("c0ab01zzzz") == "c.ab.1.zzzz"


class TestToFullId:
    def test_dotted_format(self):
        assert to_full_id("a.1.0.1") == "a001000001"

    def test_dotted_with_padding(self):
        assert to_full_id("n.12.3.45") == "n012030045"

    def test_dotted_already_full(self):
        assert to_full_id("c.abc.12.abcd") == "cabc12abcd"

    def test_short_numeric(self):
        assert to_full_id("a1") == "a000000001"

    def test_already_full(self):
        full = "a001000001"
        assert to_full_id(full) == full

    def test_empty(self):
        assert to_full_id("") == ""

    def test_dotted_invalid_parts(self):
        assert to_full_id("a.1.2") == "a.1.2"


class TestGetTypeChar:
    def test_known_types(self):
        assert _get_type_char("小说") == "n"
        assert _get_type_char("漫画") == "c"
        assert _get_type_char("音乐") == "m"
        assert _get_type_char("电影") == "f"
        assert _get_type_char("美图集") == "i"

    def test_unknown_type(self):
        assert _get_type_char("未知") == "0"
        assert _get_type_char("") == "0"


class TestFolderNames:
    def test_author_with_id(self):
        assert author_folder_name("001", "张三") == "001_张三"

    def test_author_no_id(self):
        assert author_folder_name("", "张三") == "张三"

    def test_series_with_name(self):
        assert series_folder_name("01", "系列一") == "01_系列一"

    def test_series_no_name(self):
        assert series_folder_name("01", "") == ""

    def test_work_prefix(self):
        assert work_file_prefix("a001000001") == "0001"

    def test_work_prefix_short(self):
        assert work_file_prefix("ab") == "ab"


class TestDictFromRow:
    def test_none(self):
        assert dict_from_row(None) is None

    def test_row(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE t (a TEXT, b INTEGER)")
        conn.execute("INSERT INTO t VALUES ('x', 1)")
        row = conn.execute("SELECT * FROM t").fetchone()
        result = dict_from_row(row)
        assert result == {"a": "x", "b": 1}
        conn.close()

    def test_dicts_from_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE t (a TEXT)")
        conn.execute("INSERT INTO t VALUES ('x')")
        conn.execute("INSERT INTO t VALUES ('y')")
        rows = conn.execute("SELECT * FROM t").fetchall()
        result = dicts_from_rows(rows)
        assert result == [{"a": "x"}, {"a": "y"}]
        conn.close()
