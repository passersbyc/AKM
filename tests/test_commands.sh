#!/bin/bash
# ============================================================
#  bkm 手动测试命令清单
#  用法:
#    cd /Users/passersbyc/代码/cli-book-manager
#    bash tests/test_commands.sh
#    bash tests/test_commands.sh --json    # JSON 输出模式
# ============================================================
set -euo pipefail

TEST_DIR="${TEST_DIR:-/Users/passersbyc/Desktop/test}"
JSON="${1:-}"
JSON_FLAG=""
if [ "$JSON" = "--json" ]; then
    JSON_FLAG="--json"
fi

# ── 颜色 ──
G='\033[92m'; R='\033[91m'; C='\033[96m'; Y='\033[93m'; M='\033[95m'; D='\033[2m'; B='\033[1m'; N='\033[0m'
_divider() { echo -e "\n${B}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"; }
_section() { echo; _divider; echo -e "  ${B}${Y}$*${N}"; _divider; }
_info()    { echo -e "    ${C}● $*${N}"; }
_cmd()     { echo; echo -e "  ${B}▶ 执行:${N} ${B}${Y}$*${N}"; echo -e "  ${C}──────────────────────────────────────────────${N}"; }
_ok()      { echo -e "  ${G}✓${N} $*"; }
_err()     { echo -e "  ${R}✗${N} $*"; }
_note()    { echo -e "    ${D}$*${N}"; }
_expect()  { echo -e "  ${M}◎ 验证:${N} $*"; }

# ── 安全退出 ──
_cleanup() {
    _section "收尾: 恢复设置并清理测试数据"
    python3 run.py settings reset $JSON_FLAG 2>/dev/null
    rm -rf tests/test_library tests/test_manifest.csv tests/test_library.db manual-test* 小说_manual-test* 漫画_manual-test* ___bkm_test_export* 2>/dev/null
    echo
}
trap _cleanup EXIT

# ======================== Phase 0: 隔离测试环境 ========================
_section "Phase 0: 隔离测试库"
_info "切换为测试专用库路径和数据库，测试数据隔离在 tests/ 内"
_cmd "python3 run.py settings set library_path tests/test_library"
python3 run.py settings set library_path tests/test_library $JSON_FLAG
_cmd "python3 run.py settings set db_path tests/test_library.db"
python3 run.py settings set db_path tests/test_library.db $JSON_FLAG
_ok "测试库已隔离 (tests/test_library + tests/test_library.db)"
sleep 1

# ======================== Phase 1: 导入 ========================
_section "Phase 1: 导入"

# R1 基础导入（2 EPUB）
_info "R1 基础导入"
_cmd 'python3 run.py import "$TEST_DIR/不要说出心愿哦.epub" "$TEST_DIR/中年危机的大叔？不！我是姐姐最好的妹妹.epub" --yes'
python3 run.py import \
    "$TEST_DIR/不要说出心愿哦.epub" \
    "$TEST_DIR/中年危机的大叔？不！我是姐姐最好的妹妹.epub" \
    --yes $JSON_FLAG
_ok "R1 完成 (2 文件)"

# R2 完整元数据（3 EPUB，含系列/标签/收藏/评分/简介/来源）
_info "R2 完整元数据 (系列+标签+收藏+评分+简介+来源)"
_cmd 'python3 run.py import "$TEST_DIR/家暴男的轮回转世.epub" "$TEST_DIR/被取代的女偶像.epub" "$TEST_DIR/首尔海关奇遇记.epub" --author testchain --series "test-series" --tags "R18,TSF" --favorite --rating 8.5 --description "测试简介" --source "https://example.com/test" --yes'
python3 run.py import \
    "$TEST_DIR/家暴男的轮回转世.epub" \
    "$TEST_DIR/被取代的女偶像.epub" \
    "$TEST_DIR/首尔海关奇遇记.epub" \
    --author testchain --series "test-series" \
    --tags "R18,TSF" --favorite --rating 8.5 \
    --description "测试简介内容" \
    --source "https://example.com/test-series" \
    --yes $JSON_FLAG
_ok "R2 完成 (3 文件)"

# R3 标题管线（含 ? 的书）
_info "R3 标题管线测试 (验证 ? 保留)"
_cmd 'python3 run.py import "$TEST_DIR/慢性换身欲望：健身女教练×肥宅大学生.epub" "$TEST_DIR/美女大学高材生，因为控制狂妈妈，去当大排档老板娘！.epub" --author testchain --source "https://pixiv.net/novel/show.php?id=99999" --yes'
python3 run.py import \
    "$TEST_DIR/慢性换身欲望：健身女教练×肥宅大学生.epub" \
    "$TEST_DIR/美女大学高材生，因为控制狂妈妈，去当大排档老板娘！.epub" \
    --author testchain \
    --source "https://pixiv.net/novel/show.php?id=99999" \
    --yes $JSON_FLAG
_ok "R3 完成 (2 文件)"

# R4 DOC 转换
_info "R4 DOC 转换 (DOC → EPUB)"
_cmd 'python3 run.py import "$TEST_DIR/[附身] [碟中谍]游泳衣2 第四章 行动X计划.doc" --author testchain --target-format epub --yes'
python3 run.py import \
    "$TEST_DIR/[附身] [碟中谍]游泳衣2 第四章 行动X计划.doc" \
    --author testchain --target-format epub --yes $JSON_FLAG
_ok "R4 完成 (1 DOC)"

# R5 PDF
_info "R5 PDF 导入"
_cmd 'python3 run.py import "$TEST_DIR/更衣人偶.pdf" "$TEST_DIR/变相怪盗-代价.pdf" --author testchain --yes'
python3 run.py import \
    "$TEST_DIR/更衣人偶.pdf" \
    "$TEST_DIR/变相怪盗-代价.pdf" \
    --author testchain --yes $JSON_FLAG
_ok "R5 完成 (2 PDF)"

# R6 边界：MD5 重复
_info "R6 重复导入 (MD5 去重验证)"
_cmd 'python3 run.py import "$TEST_DIR/不要说出心愿哦.epub" --author testchain --yes'
python3 run.py import \
    "$TEST_DIR/不要说出心愿哦.epub" \
    --author testchain --yes $JSON_FLAG
_expect "MD5重复，已存在，跳过"

# ======================== Phase 2: Info ========================
_section "Phase 2: 查看详情"

_info "列表当前所有作品"
_cmd "python3 run.py list -w --sort-by id"
python3 run.py list -w --sort-by id $JSON_FLAG

echo
# 辅助函数：从 list -w --json 中提取第 N 个 ID
_nth_id() {
    local n=${1:-0}
    python3 run.py list -w --sort-by id --json 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
works=d.get('data',d).get('works',[])
print(works[$n]['ID'] if len(works)>$n else '')
" 2>/dev/null
}

_info "取第一个 ID 查看详情"
FIRST_ID=$(_nth_id 0)
[ -z "$FIRST_ID" ] && FIRST_ID="n001000001"
_cmd "python3 run.py info $FIRST_ID"
python3 run.py info "$FIRST_ID" $JSON_FLAG

echo
_expect "作者应为 testchain, 来源非空, 文件路径存在"
_expect "标题中 ? 应保留为 ? (不为 _)"

# ======================== Phase 3: Search ========================
_section "Phase 3: 搜索"

_info "按作者搜索"
_cmd "python3 run.py search --author testchain"
python3 run.py search --author testchain $JSON_FLAG

_info "按关键词搜索"
_cmd 'python3 run.py search --keyword "心愿"'
python3 run.py search --keyword "心愿" $JSON_FLAG

_info "按 ID 前缀搜索"
_cmd 'python3 run.py search --id-prefix "n0010"'
python3 run.py search --id-prefix "n0010" $JSON_FLAG

_info "按系列搜索"
_cmd 'python3 run.py search --series "test-series"'
python3 run.py search --series "test-series" $JSON_FLAG

# ======================== Phase 4: Edit ========================
_section "Phase 4: 编辑"

# 取两个 ID：第一个做安全编辑，第二个做危险编辑
ID1=$(_nth_id 0)
[ -z "$ID1" ] && ID1="n001000001"
ID2=$(_nth_id 1)
[ -z "$ID2" ] && ID2="n001000002"

# ── 安全编辑 ──
_info "安全编辑: $ID1 (收藏/评分/标签/点赞) — 路径不应变化"

_info "编辑前"
_cmd "python3 run.py info $ID1"
python3 run.py info "$ID1"

_cmd "python3 run.py edit $ID1 --favorite yes --rating 9.0 --add-tag test-tag --like 3"
python3 run.py edit "$ID1" --favorite yes --rating 9.0 --add-tag "test-tag" --like 3 $JSON_FLAG

_info "编辑后"
_cmd "python3 run.py info $ID1"
python3 run.py info "$ID1"
_expect " ID 不变, 路径不变, 收藏=是, 评分=9.0, 标签含 test-tag"

# ── 删除标签 ──
_info "删除标签: $ID1"
_cmd "python3 run.py edit $ID1 --rm-tag test-tag"
python3 run.py edit "$ID1" --rm-tag "test-tag" $JSON_FLAG

_info "删标签后"
_cmd "python3 run.py info $ID1"
python3 run.py info "$ID1"
_expect " 标签中不含 test-tag"

# ── 危险编辑：修改系列 ──
_info "危险编辑: $ID2 (修改系列) — 路径应迁移, ID 应变更"
_info "编辑前 (修改系列前)"
_cmd "python3 run.py info $ID2"
python3 run.py info "$ID2"

_cmd "python3 run.py edit $ID2 --series new-series"
# 捕获 edit 输出，提取新 ID 短格式 (c.1.0.2 → c.1.2.1)
EDIT_OUT=$(python3 run.py edit "$ID2" --series "new-series" $JSON_FLAG 2>&1)
echo "$EDIT_OUT"
# 用 list --json 找到系列为 new-series 的新 ID
NEW_ID=$(python3 run.py list -w --sort-by id --json 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
works=d.get('data',d).get('works',[])
for w in works:
    if w.get('系列')=='new-series':
        print(w['ID'])
        break" 2>/dev/null)

_info "编辑后 (新 ID: $NEW_ID)"
_cmd "python3 run.py info $NEW_ID"
if [ -n "$NEW_ID" ]; then
    python3 run.py info "$NEW_ID"
fi
_expect " 旧 ID 已消失, 新 ID 含 series_id != 00, 新路径含 new-series"
_info "旧 ID ($ID2) 应无法查询:"
_cmd "python3 run.py info $ID2"
python3 run.py info "$ID2" $JSON_FLAG 2>/dev/null | tail -3 || echo "  (查询失败 — 符合预期)"
echo

# ======================== Phase 5: Export ========================
_section "Phase 5: 导出"

_info "folder 模式"
_cmd "python3 run.py export testchain --name manual-test --format folder"
python3 run.py export testchain --name manual-test --format folder $JSON_FLAG
ls -la manual-test/ 2>/dev/null | head -10
_ok "folder 导出完成"

_info "zip 模式"
_cmd "python3 run.py export testchain --name manual-test --format zip"
python3 run.py export testchain --name manual-test --format zip $JSON_FLAG
unzip -l manual-test.zip 2>/dev/null | head -10
_ok "zip 导出完成"

_info "completeness 模式"
_cmd "python3 run.py export testchain --name manual-test --format completeness"
python3 run.py export testchain --name manual-test --format completeness $JSON_FLAG
ls -la 小说_manual-test.* 漫画_manual-test.* 2>/dev/null || echo "    (无混合格式错误)"
_ok "completeness 导出完成"

# ======================== Phase 6: Delete ========================
_section "Phase 6: 删除"

_info "删除前统计"
_cmd "python3 run.py stats"
python3 run.py stats $JSON_FLAG

_info "取当前第一个 ID 删除"
DEL_ID=$(_nth_id 0)
[ -z "$DEL_ID" ] && DEL_ID="n001000001"
_cmd "python3 run.py delete $DEL_ID --yes --no-confirm"
python3 run.py delete "$DEL_ID" --yes --no-confirm $JSON_FLAG
_ok "删除完成: $DEL_ID"

_info "再取一个删除（验证计数递减）"
DEL_ID2=$(_nth_id 0)
if [ -n "$DEL_ID2" ]; then
    _cmd "python3 run.py delete $DEL_ID2 --yes --no-confirm"
    python3 run.py delete "$DEL_ID2" --yes --no-confirm $JSON_FLAG
    _ok "删除完成: $DEL_ID2"
fi

_info "删除后统计 + 列表"
_cmd "python3 run.py stats"
python3 run.py stats $JSON_FLAG
_cmd "python3 run.py list -w --sort-by id"
python3 run.py list -w --sort-by id $JSON_FLAG
_expect " 数量应减少 2"

# ======================== Phase 7: Verify ========================
_section "Phase 7: 完整性校验"

_cmd "python3 run.py verify"
python3 run.py verify $JSON_FLAG
_expect " 所有作品应通过校验 (total == valid_count)"

# ======================== Phase 8: Stats ========================
_section "Phase 8: 统计信息"

_cmd "python3 run.py stats"
python3 run.py stats $JSON_FLAG
_expect " 应有 小说/漫画 两个分类, 有作品/作者/系列计数"

# ======================== DONE ========================
_section "测试完成"
echo -e "  ${G}所有 8 个 Phase 执行完毕${N}"
echo -e "  ${D}收尾将自动清空库...${N}"
echo
