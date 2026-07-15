# cli-book-manager 项目全面结构分析

## 一、目录树

```
cli-book-manager/
├── run.py                          # 程序入口 (9行)
├── pyproject.toml                  # 构建配置
├── requirements.txt                # 依赖清单 (10个包)
├── config.json                     # 运行时配置
├── .gitignore
├── src/
│   ├── __init__.py
│   ├── sdk.py                      # SDK 批量导入入口 (255行)
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py                 # CLI 入口 (45行)
│   │   ├── core.py                 # CLI 框架 (418行)
│   │   ├── commands/
│   │   │   ├── auth.py             # Pixiv Cookie 鉴权 (228行)
│   │   │   ├── batch_import.py     # 批量导入 cdbook (101行)
│   │   │   ├── clean.py            # 清理临时/缓存 (347行)
│   │   │   ├── convert.py          # 文件格式转换 (78行)
│   │   │   ├── delete.py           # 删除作品/作者/系列 (173行)
│   │   │   ├── download.py         # 下载资源并导入 (346行)
│   │   │   ├── edit.py             # 编辑元数据 (207行)
│   │   │   ├── export.py           # 导出作品 (90行)
│   │   │   ├── import_cmd.py       # 导入单文件/目录 (186行)
│   │   │   ├── info.py             # 查看详细信息 (239行)
│   │   │   ├── list.py             # 列出作品/作者/系列 (249行)
│   │   │   ├── migrate.py          # 旧系统数据迁移 (331行)
│   │   │   ├── rank.py             # 点赞量排行榜 (595行)
│   │   │   ├── search.py           # 搜索作品 (91行)
│   │   │   ├── settings.py         # 项目设置管理 (375行)
│   │   │   ├── source.py           # Pixiv 订阅管理 (982行)
│   │   │   ├── stats.py            # 库统计信息 (50行)
│   │   │   └── verify.py           # 文件完整性校验 (45行)
│   │   └── downplugin/
│   │       ├── __init__.py         # DownloaderRegistry (74行)
│   │       ├── base.py             # BaseDownloader 抽象基类 (284行)
│   │       └── pixiv/
│   │           ├── __init__.py     # 导出 PixivDownloader (3行)
│   │           ├── client.py       # Pixiv API 客户端 (335行)
│   │           ├── config.py       # PixivConfig (201行)
│   │           ├── convert.py      # Pixiv→EPUB/PDF 转换 (503行)
│   │           ├── downloader.py   # PixivDownloader 实现 (481行)
│   │           ├── extractors.py   # URL/内容解析器 (772行)
│   │           └── types.py        # WorkInfo/ExtractMessage (76行)
│   ├── core/
│   │   ├── activity.py             # 作者活跃度计算 (111行)
│   │   ├── author_manager.py       # 作者 CRUD (326行)
│   │   ├── config.py               # 配置加载/项目根定位 (88行)
│   │   ├── converter.py            # 文件格式转换引擎 (962行)
│   │   ├── database.py             # SQLite 管理 + ID 生成 (263行)
│   │   ├── download.py             # 下载队列管理 (65行)
│   │   ├── filetype.py             # 文件类型判定 (20行)
│   │   ├── hashing.py              # MD5 哈希 + 去重 (24行)
│   │   ├── importer.py             # 单文件导入引擎 (201行)
│   │   ├── logging.py              # 日志系统 (143行)
│   │   ├── manifest.py             # 文件完整性校验 (41行)
│   │   ├── migrate_to_db.py        # CSV/JSON→SQLite 迁移 (440行)
│   │   ├── paths.py                # 书库路径构建 + 封面提取 (156行)
│   │   ├── queries.py              # 共享 SQL + row 转换 (29行)
│   │   ├── registry.py             # ID 注册表 (102行)
│   │   ├── reindex.py              # 按来源重索引 (47行)
│   │   ├── resolvers.py            # ID 解析器 (27行)
│   │   ├── series_manager.py       # 系列 CRUD (155行)
│   │   ├── utils.py                # 工具函数 (35行)
│   │   ├── work_index.py           # 作品重索引引擎 (212行)
│   │   ├── work_manager.py         # WorkManager facade (164行)
│   │   ├── work_repository.py      # 作品数据访问层 (278行)
│   │   ├── work_search.py          # 作品搜索引擎 (69行)
│   │   ├── work_source.py          # 作品来源追踪 (29行)
│   │   └── work_stats.py           # 作品统计 (78行)
│   ├── domain/
│   │   └── cdbook.py               # cdbook 文件名解析 (177行)
│   ├── export/
│   │   ├── __init__.py             # 导出引擎入口 (333行)
│   │   ├── collector.py            # 导出行收集 (147行)
│   │   ├── formatter.py            # 格式化 folder/zip (21行)
│   │   ├── merger.py               # EPUB/PDF/ZIP 合并 (312行)
│   │   └── models.py               # 导出数据类 (47行)
│   ├── operations/
│   │   ├── __init__.py             # 统一导出 (10行)
│   │   ├── clean_op.py             # 清理操作 (19行)
│   │   ├── delete_op.py            # 删除操作 (118行)
│   │   ├── edit_op.py              # 编辑操作 (83行)
│   │   ├── export_op.py            # 导出操作 (48行)
│   │   ├── import_op.py            # 导入操作 (114行)
│   │   ├── info_op.py              # 信息查看 (43行)
│   │   ├── list_op.py              # 列表操作 (96行)
│   │   ├── search_op.py            # 搜索操作 (42行)
│   │   ├── stats_op.py             # 统计操作 (45行)
│   │   └── verify_op.py            # 校验操作 (7行)
│   └── ui/
│       └── __init__.py             # (空，预留)
└── tests/
    ├── test_chain.py               # 完整集成测试 (608行)
    └── test_commands.sh            # Shell 手动测试 (292行)
```

---

## 二、各模块详解

### 2.1 顶层与 SDK

| 文件 | 行数 | 用途 | 关键类/函数 | 项目内依赖 |
|------|------|------|------------|-----------|
| `run.py` | 9 | 程序入口，将 src 加入 sys.path 并调用 main | — | `src.cli.main` |
| `src/sdk.py` | 255 | 精简 SDK：cdbook 批量导入、文件夹批量导入、批量文件导入 | `batch_import_cdbook()`, `import_files_batch()`, `batch_import_folder()` | `core.registry`, `core.reindex`, `core.filetype`, `core.logging`, `domain.cdbook`, `core.importer`, `core.config` |

### 2.2 CLI 层 (`src/cli/`)

| 文件 | 行数 | 用途 | 关键类/函数 |
|------|------|------|------------|
| `cli/main.py` | 45 | CLI 入口：自动加载 commands 包中所有模块，注册命令类，启动 CLIApp | `main()`, `load_commands()` |
| `cli/core.py` | 418 | CLI 框架核心：CLIApp 命令注册/调度/交互模式/快捷命令展开；BaseCommand 提供 `_respond()`、`_print()`、`_confirm()` 等统一接口 | `CLIApp`, `BaseCommand`, `NoExitArgumentParser` |
| `commands/auth.py` | 228 | 管理 Pixiv Cookie 鉴权：添加 Cookie、Cookie 池管理、连通性测试 | `AuthCommand` |
| `commands/batch_import.py` | 101 | 独立的批量导入 cdbook 目录命令 | `BatchImportCommand` |
| `commands/clean.py` | 347 | 清理操作：书库清空、清单清空、日志清理、空目录清理、深度检查 | `CleanCommand` |
| `commands/convert.py` | 78 | 文件格式转换 CLI 入口（docx/doc→txt/epub/pdf） | `ConvertCommand` |
| `commands/delete.py` | 173 | 删除作品/作者/系列：支持按 ID、按名称、按过滤器批量删除 | `DeleteCommand` |
| `commands/download.py` | 346 | 下载资源并导入：多线程、pull 模式、pull-base 模式 | `DownloadCommand` |
| `commands/edit.py` | 207 | 编辑作品/作者/系列元数据：收藏、评分、标签增删、改名 | `EditCommand` |
| `commands/export.py` | 90 | 导出作品到目录：folder/zip/epub/completeness 四种格式 | `ExportCommand` |
| `commands/import_cmd.py` | 186 | 统一导入入口：自动检测单文件、cdbook 目录、普通文件夹 | `ImportCommand` |
| `commands/info.py` | 239 | 查看作品/作者/系列完整元数据 | `InfoCommand` |
| `commands/list.py` | 249 | 列出作品/作者/系列/分类：7 种排序、分页 | `ListCommand` |
| `commands/migrate.py` | 331 | 从旧版 CSV 系统迁移数据 | `MigrateCommand` |
| `commands/rank.py` | 595 | Pixiv 点赞量排行榜 | `RankCommand` |
| `commands/search.py` | 91 | 搜索作品：多字段筛选、正则 | `SearchCommand` |
| `commands/settings.py` | 375 | 项目设置管理：show/set/reset/filetype/cookie | `SettingsCommand` |
| `commands/source.py` | 982 | Pixiv 来源订阅管理：7 个子命令 | `SourceCommand` |
| `commands/stats.py` | 50 | 库统计信息展示 | `StatsCommand` |
| `commands/verify.py` | 45 | 文件完整性校验 | `VerifyCommand` |

### 2.3 下载插件层 (`src/cli/downplugin/`)

| 文件 | 行数 | 用途 | 关键类/函数 |
|------|------|------|------------|
| `downplugin/__init__.py` | 74 | 下载器注册中心：自动扫描并注册下载器 | `DownloaderRegistry` |
| `downplugin/base.py` | 284 | 下载器抽象基类：URL 模式匹配、元数据映射、process_url 主流程 | `BaseDownloader`(ABC) |
| `pixiv/client.py` | 335 | Pixiv API 客户端：OAuth 鉴权、API 请求、Cookie 池轮换、限流 | `PixivClient` |
| `pixiv/config.py` | 201 | Pixiv 配置类 | `PixivConfig` |
| `pixiv/convert.py` | 503 | Pixiv 内容转换：多图→EPUB/PDF、动图→GIF、小说→EPUB | 多个转换函数 |
| `pixiv/downloader.py` | 481 | Pixiv 下载器实现 | `PixivDownloader` |
| `pixiv/extractors.py` | 772 | URL 和内容解析提取器 | `extract_pixiv_id()`, 多个 Extractor 类 |
| `pixiv/types.py` | 76 | 数据类 | `ExtractMessage`, `WorkInfo` |

### 2.4 核心层 (`src/core/`)

| 文件 | 行数 | 用途 | 关键类/函数 |
|------|------|------|------------|
| `database.py` | 263 | SQLite 核心：线程安全连接、WAL 模式、8张表、base36 编码、ID 计数器 | `get_db()`, `init_db()`, `_make_work_id()`, `next_author_id()`, `short_id()`, `to_full_id()` |
| `config.py` | 88 | 配置系统：项目根定位、配置缓存、书库路径、错误翻译 | `get_project_root()`, `load_config()`, `MANIFEST_FIELDS` |
| `registry.py` | 102 | ID 注册表：作者/系列/作品 ID 的生成和解析 | `generate_id()`, `_get_author_id()`, `_get_series_id()` |
| `resolvers.py` | 27 | ID 解析器：将名称解析为 ID，打破循环依赖 | `resolve_author_id()`, `resolve_series_id()` |
| `queries.py` | 29 | 共享 SQL：JOIN_SQL 三表联合查询，row_to_manifest 行转换 | `JOIN_SQL`, `row_to_manifest()` |
| `work_repository.py` | 278 | 作品数据访问层：全部 CRUD | `read_all()`, `append_one()`, `get_by_id()`, `update_entry()`, `update_entry_full()`, `delete_entries()` |
| `work_manager.py` | 164 | WorkManager facade：统一接口 | `WorkManager`(全 classmethod) |
| `work_search.py` | 69 | 搜索引擎：内存多字段匹配 | `search()` |
| `work_index.py` | 212 | 重索引引擎：分组重排 ID，两阶段文件重命名 | `reindex_groups()`, `delete_and_reindex()` |
| `work_source.py` | 29 | 来源追踪：source URL 去重集合 | `source_set()`, `is_source_imported()` |
| `work_stats.py` | 78 | 统计模块 | `get_stats()`, `aggregate()` |
| `reindex.py` | 47 | 按来源重排序 | `reindex_for_source()` |
| `importer.py` | 201 | 单文件导入引擎：完整导入管线 | `ImportResult`, `import_one()`, `import_batch()` |
| `converter.py` | 962 | 格式转换引擎（项目最大文件） | `convert_to_txt()`, `convert_to_epub()`, `convert_to_simplified()` |
| `paths.py` | 156 | 路径构建：书库路径计算、封面提取 | `build_import_target()`, `extract_pdf_cover()` |
| `filetype.py` | 20 | 文件类型判定 | `determine_file_type()` |
| `hashing.py` | 24 | MD5 哈希与去重 | `generate_file_md5()`, `check_duplicate_by_md5()` |
| `manifest.py` | 41 | 文件完整性校验 | `check_file_integrity()` |
| `download.py` | 65 | 下载队列管理 | `read_download_json()`, `append_to_download_json()` |
| `author_manager.py` | 326 | 作者管理 | `list_all()`, `upsert()`, `register()`, `resolve()`, `rename()` |
| `series_manager.py` | 155 | 系列管理 | `get_or_create()`, `rename()`, `delete()` |
| `activity.py` | 111 | 活跃度计算 | `compute_status()`, `build_author_stats()` |
| `logging.py` | 143 | 日志系统 | `setup_logging()`, `get_logger()` |
| `utils.py` | 35 | 工具函数 | `description_to_text()`, `strip_tag_prefix()` |
| `migrate_to_db.py` | 440 | 一次性迁移脚本 | `migrate()` |

### 2.5 领域层 (`src/domain/`)

| 文件 | 行数 | 用途 | 关键函数 |
|------|------|------|---------|
| `cdbook.py` | 177 | cdbook 文件名解析：提取标签/标题/章节/完结状态，系列自动检测 | `parse_cdbook_filename()`, `detect_cdbook_series()`, `normalize_series_name()` |

### 2.6 导出层 (`src/export/`)

| 文件 | 行数 | 用途 | 关键函数 |
|------|------|------|---------|
| `__init__.py` | 333 | 导出引擎入口：三种模式 | `export_works()`, `_do_standard()`, `_do_epub_export()`, `_do_completeness()` |
| `collector.py` | 147 | 导出行收集：按作者/标签过滤分组 | `collect_rows()` |
| `merger.py` | 312 | 合并引擎：多 EPUB 合并、多 PDF 合并、ZIP 打包 | `merge_epubs()`, `merge_pdfs()`, `merge_series_group()` |
| `formatter.py` | 21 | 输出格式化 | `format_as_folder()`, `format_as_zip()` |
| `models.py` | 47 | 导出数据类 | `ExportRequest`, `ExportPlan`, `ExportResult` |

### 2.7 操作层 (`src/operations/`)

| 文件 | 行数 | 用途 |
|------|------|------|
| `import_op.py` | 114 | 导入操作入口 |
| `list_op.py` | 96 | 列表操作：4 种类型分发，7 种排序 |
| `search_op.py` | 42 | 搜索操作：加 id_prefix 和 liked 过滤 |
| `edit_op.py` | 83 | 编辑操作：book/author/series 三种分发 |
| `delete_op.py` | 118 | 删除操作：ID 解析（含范围语法）、名称匹配 |
| `export_op.py` | 48 | 导出操作入口 |
| `info_op.py` | 43 | 信息查看 |
| `stats_op.py` | 45 | 统计操作 |
| `verify_op.py` | 7 | 校验操作 |
| `clean_op.py` | 19 | 清理操作 |

---

## 三、依赖图（按层组织）

```
第零层：无依赖
  domain/cdbook       export/models       export/formatter
  core/queries        core/manifest

第一层：基础设施
  core/config         core/logging        core/utils

第二层：数据存储
  core/database       core/filetype       core/hashing      core/download

第三层：ID 与解析
  core/registry       core/resolvers

第四层：实体管理
  core/author_manager core/series_manager core/paths        core/converter

第五层：作品管理
  core/work_repository  core/work_search    core/work_stats
  core/work_index       core/work_source    core/work_manager
  core/importer         core/activity       core/reindex

第六层：导出引擎
  export/collector    export/merger       export/__init__

第七层：操作层
  operations/*        ← core/work_manager, core/author_manager,
                         core/series_manager, export

第八层：CLI 层
  cli/core            cli/main            cli/commands/*    sdk

独立层：下载插件
  downplugin/base     pixiv/client        pixiv/extractors
  pixiv/convert       pixiv/downloader
```

---

## 四、核心数据流

### 4.1 导入一本书

```
用户命令 → import_cmd → sdk.import_files_batch → core.importer.import_one
    │
    ├── [1] 文档转换 (.doc/.docx → .epub)
    ├── [2] MD5 计算 + 去重检查
    ├── [3] 文件类型判定 (小说/漫画/...)
    ├── [4] 生成复合 ID (type_char + author_id + series_id + seq)
    ├── [5] 构建目标路径 (library/分类/作者/系列/文件)
    ├── [6] 复制文件到书库
    ├── [7] 繁简转换（如需要）
    ├── [8] 入库 (INSERT INTO works)
    └── [9] 确保作者已注册
```

### 4.2 列出/搜索

```
list → operations/list_op → work_manager.read() → work_repository.read_all()
    → SQL: SELECT w.*, a.name, s.name FROM works w JOIN authors a JOIN series s
    → row_to_manifest() → Rich Table 渲染

search → operations/search_op → work_search.search()
    → read_all() 全量 → 内存多字段匹配（AND 逻辑）→ 返回结果
```

### 4.3 编辑

```
edit → operations/edit_op → work_repository.update_entry / update_entry_full
    │
    ├── 安全编辑（不改作者/系列）→ UPDATE works SET ... WHERE id = ?
    └── 迁移编辑（改变作者/系列）→ 新 ID → 文件 shutil.move → DELETE + INSERT
```

### 4.4 删除

```
delete → operations/delete_op → work_index.delete_and_reindex
    ├── 删除文件 (unlink)
    ├── 删除记录 (DELETE FROM works)
    └── 重索引剩余（两阶段文件重命名避免冲突）
```

### 4.5 导出

```
export → operations/export_op → export.export_works
    ├── collector.collect_rows() → 过滤分组
    ├── _do_standard() → 系列合并 (EPUB/PDF/ZIP) → 输出 folder/zip
    ├── _do_epub_export() → 全部转 EPUB → 合并
    └── _do_completeness() → 按分类全局合并为一个文件
```

### 4.6 批量导入 (cdbook)

```
import /cdbook_dir → sdk.batch_import_cdbook
    ├── 扫描文件 → 过滤支持的后缀
    ├── parse_cdbook_filename() → 提取元数据
    ├── detect_cdbook_series() → 公共前缀自动检测系列
    ├── 排序（系列→序号→标题）
    ├── 逐个 import_one()
    └── reindex_for_source("cdbook")
```

### 4.7 下载

```
download URL → DownloaderRegistry.resolve() → PixivDownloader
    ├── expand_urls() → 展开用户页
    ├── extractors → 解析页面
    ├── client → Pixiv API (OAuth)
    ├── convert → 多图→EPUB/PDF
    ├── import_one() → 入库
    └── 多线程并行
```

---

## 五、数据库 Schema（8 张表）

### authors — 作者表
| 列 | 类型 | 说明 |
|----|------|------|
| id | TEXT PK | 3位 base36 (000~zzz) |
| name | TEXT | 作者名 |
| aliases | TEXT | 曾用名 |
| source | TEXT | local/pixiv |
| note | TEXT | 备注 |
| favorite | INTEGER | 0/1 |

### pixiv_trackings — Pixiv 追踪表
| 列 | 类型 | 说明 |
|----|------|------|
| author_id | TEXT PK FK | 关联 authors |
| pixiv_uid | TEXT UNIQUE | Pixiv 用户 ID |
| homepage | TEXT | 主页 URL |
| follow_status | TEXT | active/paused/dead |
| latest_work_id | TEXT | 最新 Pixiv 作品 ID |
| last_checked | TEXT | 上次检查时间 |

### series — 系列表
| 列 | 类型 | 说明 |
|----|------|------|
| id | TEXT | 2位 base36 |
| author_id | TEXT FK | 关联 authors |
| name | TEXT | 系列名 |
| PRIMARY KEY | (id, author_id) | |

### works — 作品表
| 列 | 类型 | 说明 |
|----|------|------|
| id | TEXT PK | 10位复合 ID |
| title | TEXT | 标题 |
| author_id | TEXT FK | 关联 authors |
| series_id | TEXT | 系列 ID |
| tags | TEXT | 标签(逗号分隔) |
| source | TEXT | 来源 URL |
| source_status | TEXT | ok/deleted |
| file_ext | TEXT | 文件后缀 |
| file_type | TEXT | 分类 |
| imported_at | TEXT | 导入时间 |
| file_size_kb | REAL | 文件大小 |
| md5 | TEXT | 文件 MD5 |
| file_path | TEXT | 磁盘路径 |
| favorite | INTEGER | 0/1 |
| rating | REAL | 评分 |
| description | TEXT | 简介 |
| likes | INTEGER | 点赞数 |

### download_queue — 下载队列表
| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | 自增 |
| url | TEXT UNIQUE | 下载 URL |
| author_id | TEXT | 关联作者 |
| status | TEXT | pending/... |

### id_counters — ID 计数器表
| 列 | 类型 | 说明 |
|----|------|------|
| name | TEXT PK | 计数器名称 |
| value | INTEGER | 当前值 |

### pixiv_likes — 点赞数据表
| 列 | 类型 | 说明 |
|----|------|------|
| work_id | TEXT PK | Pixiv 作品 ID |
| like_count | INTEGER | 点赞数 |
| title | TEXT | 标题 |
| author | TEXT | 作者 |

### pixiv_blacklist — 黑名单表
| 列 | 类型 | 说明 |
|----|------|------|
| work_id | TEXT PK | 无效作品 ID |

### settings — 键值设置表
| 列 | 类型 | 说明 |
|----|------|------|
| key | TEXT PK | 设置名 |
| value | TEXT | 设置值 |

---

## 六、ID 系统 — base36 复合 ID

### 6.1 ID 结构（10位定长）

```
 位置:  0     1-3     4-5     6-9
       ┌──┐ ┌────┐  ┌────┐  ┌──────┐
       │ T│ │AAA │  │ SS │  │ WWWW │
       └──┘ └────┘  └────┘  └──────┘
       类型  作者ID   系列ID   作品序号
```

| 字段 | 位数 | 编码 | 范围 | 说明 |
|------|------|------|------|------|
| T | 1 | 字符映射 | n/c/m/f/i/0 | 小说/漫画/音乐/电影/美图集/未知 |
| AAA | 3 | base36 | 000~zzz | 作者ID，最多 46,655 位 |
| SS | 2 | base36 | 00~zz | 系列ID，每作者最多 1,295 个 |
| WWWW | 4 | base36 | 0000~zzzz | 组内序号，每组最多 1,679,615 个 |

### 6.2 短 ID（显示用）

```
n001010001  →  n.1.1.1      （各部分去前导零，用 . 分隔）
n0a30b00ff  →  n.a3.b.ff
```

### 6.3 文件系统路径

```
library/
├── 小说/
│   └── 001_作者名/
│       ├── 0001_作品标题.epub          # 无系列
│       └── 01_系列名/
│           ├── 0001_作品1.epub          # 有系列
│           └── 0002_作品2.epub
├── 漫画/
│   └── 003_漫画作者/
│       └── 0001_漫画.pdf
├── 音乐/
├── 电影/
└── 美图集/
```

### 6.4 重索引机制

删除作品后，剩余作品自动重排 ID 保持连续性：
1. 按 (type, author, series) 分组
2. 每组内排序后重置计数器
3. Phase 1: 文件改临时名 (.tmp_xxxx)
4. Phase 2: 临时名改最终名，更新路径

---

## 七、配置系统

config.json 通过 `core/config.py :: load_config()` 加载（带内存缓存），项目根通过向上查找 `pyproject.toml` 或 `config.json` 定位。

主要配置组：
- **project_settings**: library_path, db_path, convert_traditional, migrate_mode
- **log**: 文件日志 (RotatingFileHandler) + 控制台 (RichHandler)
- **filetype**: 扩展名 → 分类映射
- **translations**: argparse 错误消息中文化
- **download**: 全局下载参数（线程数、超时、限流）
- **pixiv**: OAuth token, Cookie 池, 各提取器参数, 下载参数

配置修改入口：`akm settings show/set/reset/filetype/cookie`
