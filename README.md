# AKM

AKM（akm）是一个 Python 命令行作品管理系统，统一管理**小说 / 漫画 / 音乐 / 电影 / 图片**五类作品。支持本地文件导入、元数据编辑、搜索、导出，并内置 **Pixiv** 与**笔趣阁**下载插件，可自动抓取并转换入库。

## 功能特性

- **五类作品管理**：小说（txt/epub/mobi/azw3/docx/doc）、漫画（pdf/zip）、图片（jpg/png/gif）、电影（mp4/avi/mkv）、音乐（mp3/flac/wav）
- **下载插件**：
  - `pixiv`：OAuth 鉴权 + Cookie 池轮换，多图 → EPUB/PDF，动图 → GIF，小说 → EPUB
  - `biquge`：笔趣阁小说下载
- **复合 ID 系统**：10 位 base36 定长 ID（类型 + 作者 + 系列 + 序号），删除后自动重索引保持连续
- **格式转换**：docx/doc → txt，繁简转换，图片文件夹 → PDF/CBZ，EPUB 构建
- **导出**：folder / zip / epub / 完整性校验四种模式，支持系列合并
- **SQLite 存储**：WAL 模式，10 张表，线程安全

## 安装与启动

```bash
# 首次运行：自动创建 .venv 并安装依赖（需要 Python >= 3.11）
./start.sh

# 或手动
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

安装后也可用注册的命令 `akm` 直接调用。

## 命令一览

| 命令 | 说明 |
|------|------|
| `akm stats` | 库统计信息 |
| `akm import <文件/目录>` | 导入作品（自动识别单文件 / cdbook 目录 / 普通文件夹） |
| `akm search <关键词>` | 搜索作品（多字段、正则） |
| `akm list [book/author/series]` | 列出作品 / 作者 / 系列（7 种排序、分页） |
| `akm open <ID/名称>` | 在关联应用中打开作品文件，或打开来源网址 |
| `akm edit <ID>` | 编辑作品 / 作者 / 系列元数据（收藏、评分、标签、改名） |
| `akm delete <ID>` | 删除作品 / 作者 / 系列（支持范围语法） |
| `akm follow` | 关注 Pixiv 作者 / 同步作者新作到下载队列 |
| `akm pull` | 拉取下载队列中的待下载作品并入库 |
| `akm export <查询>` | 导出作品（folder / zip / epub） |
| `akm setting` | 项目设置管理 |

## 架构概览

七层分层架构，调用方向自上而下：

```
入口层        run.py → akm 命令 (src/cli/main.py)
CLI 命令层    src/cli/commands/*_cmd.py  +  下载插件 downplugin (pixiv / biquge)
操作层        src/operations/*_op.py
核心层        src/core/*  (database / importer / converter / managers ...)
领域/导出/SDK  src/domain/cdbook · src/export/* · src/sdk.py
SQLite        library.db (WAL, 10 表)
文件书库      library/  (config: library_path)
```

详见 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)。

## 配置

运行时配置在 `config.json`。**`config.json` 含 Pixiv 凭据（refresh_token / cookie / cookie_pool），不纳入 git 跟踪**。

新环境请：

```bash
cp config.example.json config.json
# 然后编辑 config.json，填入你自己的 Pixiv refresh_token、cookie、cookie_pool
```

主要配置组：

- `project_settings`：`library_path`（书库目录）、`db_path`（数据库路径）、`convert_traditional`（繁简转换）、`export_path`（导出目录）
- `filetype`：扩展名 → 分类映射
- `download`：全局下载参数（线程数、超时、限流）
- `pixiv`：`refresh_token`、`cookie`、`cookie_pool`、各提取器参数、下载参数

## 数据库与 ID 系统

- **SQLite**（`library.db`，WAL 模式）：`works` / `authors` / `series` / `pixiv_trackings` / `download_queue` / `pixiv_likes` / `pixiv_blacklist` / `id_counters` / `settings` / `recent_opens`
- **复合 ID**（10 位定长）：`T AAA SS WWWW` = 类型(1) + 作者(3) + 系列(2) + 序号(4)，全 base36
  - 类型字符：`n` 小说 / `c` 漫画 / `m` 音乐 / `f` 电影 / `i` 图片 / `0` 未知
  - 短 ID 显示：`n001010001` → `n.1.1.1`
- **文件路径**：`library/分类/序号_作者名/[序号_系列名/]序号_标题.后缀`
- **重索引**：删除作品后，同组剩余作品自动重排序号保持连续（两阶段文件重命名）

## 技术栈

Python 3.11+ / SQLite / rich + prompt_toolkit（CLI）/ ebooklib + pypdf + python-docx（文档转换）/ requests + tqdm（下载）
