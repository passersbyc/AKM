# AKM 项目结构分析

> 本文档基于实际代码核实，反映当前 `*_cmd.py` 新版命令与下载插件现状。

## 一、目录树

```
AKM/
├── run.py                          # 程序入口（sys.path 注入 src，调用 main）
├── pyproject.toml                  # 构建配置（name=akm，script: akm = src.cli.main:main）
├── requirements.txt                # 依赖清单
├── config.json                     # 运行时配置（含 Pixiv 凭据，已 gitignore，不入库）
├── config.example.json             # 配置模板（脱敏，新环境复制为 config.json）
├── start.sh                        # 启动脚本（自动建 .venv 装依赖）
├── library.db                      # SQLite 数据库（WAL 模式）
├── src/
│   ├── __init__.py
│   ├── sdk.py                      # SDK 批量导入入口
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py                 # CLI 入口：注册命令、启动 CLIApp
│   │   ├── core.py                 # CLIApp 命令注册/调度/交互模式
│   │   ├── base.py                 # BaseCommand 基类（_respond/_print/_confirm）
│   │   ├── matcher.py              # ID/名称解析器（resolve_work / resolve_author）
│   │   ├── output.py               # 输出渲染
│   │   ├── completion.py           # 命令补全
│   │   ├── commands/
│   │   │   ├── __init__.py
│   │   │   ├── _download_utils.py  # DownloadGroupRunner（多线程下载工具）
│   │   │   ├── stats_cmd.py        # 库统计
│   │   │   ├── import_cmd.py       # 导入作品（单文件/目录/cdbook）
│   │   │   ├── search_cmd.py       # 搜索作品
│   │   │   ├── list_cmd.py         # 列出作品/作者/系列
│   │   │   ├── open_cmd.py         # 打开作品文件 / 来源网址
│   │   │   ├── edit_cmd.py         # 编辑元数据
│   │   │   ├── delete_cmd.py       # 删除作品/作者/系列
│   │   │   ├── follow_cmd.py       # 关注 Pixiv 作者 / 同步新作到下载队列
│   │   │   ├── pull_cmd.py         # 拉取下载队列并入库
│   │   │   ├── export.py           # 导出作品（folder/zip/epub）
│   │   │   └── setting_cmd.py      # 项目设置管理
│   │   └── downplugin/
│   │       ├── __init__.py         # DownloaderRegistry（自动发现下载器）
│   │       ├── base.py             # BaseDownloader 抽象基类
│   │       ├── context.py          # 下载上下文
│   │       ├── pixiv/              # Pixiv 下载插件
│   │       │   ├── __init__.py
│   │       │   ├── client.py       # Pixiv API 客户端（OAuth + Cookie 池轮换）
│   │       │   ├── config.py       # PixivConfig
│   │       │   ├── convert.py      # 多图→EPUB/PDF、动图→GIF、小说→EPUB
│   │       │   ├── downloader.py   # PixivDownloader 实现
│   │       │   ├── extractors.py   # URL/内容解析器
│   │       │   └── types.py        # WorkInfo / ExtractMessage
│   │       └── biquge/             # 笔趣阁下载插件
│   │           ├── __init__.py
│   │           └── client.py       # 笔趣阁小说客户端
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py               # 配置加载 / 项目根定位
│   │   ├── logging.py              # 日志系统
│   │   ├── database.py             # SQLite 管理 + ID 生成（WAL、base36）
│   │   ├── registry.py             # ID 注册表（作者/系列/作品 ID 生成解析）
│   │   ├── resolvers.py            # 名称→ID 解析器（打破循环依赖）
│   │   ├── queries.py              # 共享 SQL + row_to_manifest
│   │   ├── work_repository.py      # 作品数据访问层（CRUD）
│   │   ├── work_manager.py         # WorkManager facade
│   │   ├── work_search.py          # 作品搜索引擎（内存多字段匹配）
│   │   ├── work_index.py           # 重索引引擎（两阶段文件重命名）
│   │   ├── work_source.py          # 作品来源追踪（source 去重）
│   │   ├── work_stats.py           # 作品统计
│   │   ├── importer.py             # 单文件导入引擎（import_one / import_batch）
│   │   ├── paths.py                # 书库路径构建 + 封面提取
│   │   ├── filetype.py             # 文件类型判定
│   │   ├── hashing.py              # MD5 哈希 + 去重
│   │   ├── manifest.py             # 文件完整性校验
│   │   ├── reindex.py              # 按来源重排序
│   │   ├── author_manager.py       # 作者 CRUD
│   │   ├── series_manager.py       # 系列 CRUD
│   │   ├── activity.py             # 作者活跃度计算
│   │   ├── download.py             # 下载队列管理
│   │   ├── converter.py            # 格式转换引擎入口
│   │   ├── docx_converter.py       # DOCX/DOC → TXT
│   │   ├── epub_builder.py         # EPUB 构建与后处理
│   │   ├── pdf_converter.py        # PDF 转换
│   │   ├── image_converter.py      # 图片文件夹 → PDF/CBZ
│   │   ├── cjk_converter.py        # 繁简中文转换
│   │   ├── utils.py                # 工具函数
│   │   └── migrate_to_db.py        # 一次性 CSV/JSON→SQLite 迁移脚本
│   ├── domain/
│   │   └── cdbook.py               # cdbook 文件名解析（标签/标题/章节/系列检测）
│   ├── export/
│   │   ├── __init__.py             # 导出引擎入口（standard/epub/completeness）
│   │   ├── collector.py            # 导出行收集（按作者/标签过滤分组）
│   │   ├── merger.py               # EPUB/PDF/ZIP 合并
│   │   ├── formatter.py            # folder/zip 格式化
│   │   └── models.py               # ExportRequest/ExportPlan/ExportResult
│   ├── operations/
│   │   ├── __init__.py             # 统一导出（含 source_op 全套函数）
│   │   ├── import_op.py            # 导入操作
│   │   ├── list_op.py              # 列表操作（4 类型、7 排序）
│   │   ├── search_op.py            # 搜索操作
│   │   ├── info_op.py              # 信息查看
│   │   ├── edit_op.py              # 编辑操作（book/author/series）
│   │   ├── delete_op.py            # 删除操作（ID 解析含范围语法）
│   │   ├── export_op.py            # 导出操作
│   │   ├── stats_op.py             # 统计操作
│   │   ├── verify_op.py            # 校验操作
│   │   ├── clean_op.py             # 清理操作（含 source_set）
│   │   └── source_op.py            # Pixiv 来源/关注/同步操作（follow/pull 后端）
│   └── ui/
│       └── __init__.py             # 预留
└── tests/
    ├── conftest.py
    ├── seed_test_files.py          # 测试数据生成
    ├── test_cdbook.py
    ├── test_chain.py               # 完整集成测试
    ├── test_commands.sh            # Shell 手动测试
    ├── test_operations.py
    ├── test_pure_database.py
    ├── test_queries.py
    ├── test_source_op.py
    └── fixtures/                   # 测试夹具
```

---

## 二、分层依赖

```
第零层（无依赖）  domain/cdbook · export/models · export/formatter · core/queries · core/manifest
第一层（基础设施）core/config · core/logging · core/utils
第二层（数据存储）core/database · core/filetype · core/hashing · core/download
第三层（ID 与解析）core/registry · core/resolvers
第四层（实体管理）core/author_manager · core/series_manager · core/paths · core/converter(+子模块)
第五层（作品管理）core/work_repository · core/work_search · core/work_stats · core/work_index · core/work_source · core/work_manager · core/importer · core/activity · core/reindex
第六层（导出引擎）export/collector · export/merger · export/__init__
第七层（操作层）  operations/*  ← work_manager / author_manager / series_manager / export
第八层（CLI 层）  cli/base · cli/core · cli/matcher · cli/output · cli/main · cli/commands/* · sdk
独立层（下载插件）downplugin/base · downplugin/context · pixiv/* · biquge/*
```

---

## 三、核心数据流

### 3.1 导入一本书

```
import_cmd → operations/import_op → core.importer.import_one
  ├── 文档转换（docx/doc → txt，按需繁简转换）
  ├── MD5 计算 + 去重检查
  ├── 文件类型判定（小说/漫画/...）
  ├── 生成复合 ID（type_char + author_id + series_id + seq）
  ├── 构建目标路径（library/分类/作者/系列/文件）
  ├── 复制文件到书库
  └── 入库（INSERT INTO works）+ 确保作者已注册
```

### 3.2 follow + pull 下载流程

```
follow_cmd → operations/source_op（关注 Pixiv 作者、同步新作到 download_queue）
pull_cmd   → downplugin/registry.resolve() → PixivDownloader / BiqugeClient
  ├── expand_urls() → 展开用户页
  ├── extractors → 解析页面
  ├── client → Pixiv API（OAuth）/ 笔趣阁抓取
  ├── convert → 多图→EPUB/PDF、动图→GIF、小说→EPUB
  ├── import_one() → 入库
  └── 多线程并行（DownloadGroupRunner）
```

### 3.3 编辑 / 删除 / 导出

```
edit   → operations/edit_op → work_repository.update_entry / update_entry_full
         （安全编辑 UPDATE；迁移编辑：新 ID + 文件 move + DELETE+INSERT）
delete → operations/delete_op → work_index.delete_and_reindex
         （删文件 + 删记录 + 两阶段重索引）
export → operations/export_op → export.export_works
         （collector 分组 → standard/epub/completeness 三种模式 → folder/zip 输出）
```

---

## 四、数据库 Schema（10 张表）

| 表 | 主键 | 说明 |
|----|------|------|
| `works` | id (10位复合ID) | 作品表：title/author_id/series_id/tags/source/file_ext/file_type/file_path/md5/favorite/rating/likes 等 |
| `authors` | id (3位 base36) | 作者表：name/aliases/source/note/favorite |
| `series` | (id, author_id) | 系列表：id(2位)/author_id/name |
| `pixiv_trackings` | author_id | Pixiv 追踪：pixiv_uid/homepage/follow_status/latest_work_id/last_checked |
| `download_queue` | id (自增) | 下载队列：url(唯一)/author_id/status |
| `pixiv_likes` | work_id | Pixiv 点赞数据：like_count/title/author |
| `pixiv_blacklist` | work_id | 无效作品 ID 黑名单 |
| `id_counters` | name | ID 计数器：name/value |
| `settings` | key | 键值设置 |
| `recent_opens` | — | 最近打开记录 |

---

## 五、ID 系统 — base36 复合 ID

### 5.1 ID 结构（10 位定长）

```
位置:  0     1-3     4-5     6-9
      ┌──┐ ┌────┐  ┌────┐  ┌──────┐
      │ T│ │AAA │  │ SS │  │ WWWW │
      └──┘ └────┘  └────┘  └──────┘
      类型  作者ID   系列ID   作品序号
```

| 字段 | 位数 | 编码 | 范围 | 说明 |
|------|------|------|------|------|
| T | 1 | 字符映射 | n/c/m/f/i/0 | 小说/漫画/音乐/电影/图片/未知 |
| AAA | 3 | base36 | 000~zzz | 作者ID（最多 46,655 位） |
| SS | 2 | base36 | 00~zz | 系列ID（每作者最多 1,295 个） |
| WWWW | 4 | base36 | 0000~zzzz | 组内序号（每组最多 1,679,615 个） |

### 5.2 短 ID（显示用）

`n001010001` → `n.1.1.1`（各部分去前导零，用 `.` 分隔）

### 5.3 文件系统路径

```
library/
├── 小说/
│   └── 001_作者名/
│       ├── 0001_作品标题.epub          # 无系列
│       └── 01_系列名/
│           ├── 0001_作品1.epub          # 有系列
│           └── 0002_作品2.epub
├── 漫画/  音乐/  电影/  图片/
```

### 5.4 重索引机制

删除作品后，剩余作品自动重排 ID 保持连续：
1. 按 (type, author, series) 分组
2. 组内排序后重置计数器
3. Phase 1：文件改临时名（`.tmp_xxxx`）
4. Phase 2：临时名改最终名，更新路径

---

## 六、配置系统

`config.json` 由 `core/config.py :: load_config()` 加载（带内存缓存），项目根通过向上查找 `pyproject.toml` 或 `config.json` 定位。

> ⚠️ `config.json` 含 Pixiv 凭据（refresh_token / cookie / cookie_pool），**已加入 .gitignore，不入库**。新环境从 `config.example.json` 复制并填入自己的凭据。

主要配置组：

- **project_settings**：library_path、db_path、convert_traditional、migrate_mode、export_path
- **log**：文件日志（RotatingFileHandler）+ 控制台（RichHandler）
- **filetype**：扩展名 → 分类映射
- **translations**：argparse 错误消息中文化
- **download**：全局下载参数（线程数、超时、限流）
- **pixiv**：refresh_token、cookie、cookie_pool、各提取器参数、下载参数

配置修改入口：`akm setting`。
