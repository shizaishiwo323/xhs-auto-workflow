# 小红书自动化工作流

这个公开仓库只保留小红书自动化工作流的核心代码、示例配置和项目说明。
本地敏感配置、登录态、抓取数据、生成素材、发布历史、媒体文件和 Notebook 运行产物不会随仓库发布。

项目按三段流水线整理：

1. 爬取数据：采集关键词链接、笔记详情、图片/视频媒体。
2. 生成素材：生成小红书标题、正文、封面、轮播图和发布适配清单。
3. 自动发布：读取 `publish_manifest.json`，校验平台限制后填充小红书创作者后台。

## 当前入口

- 图片下载模块：`src/xhs_workflow/scraper/image_downloader.py`
- 视频下载模块：`src/xhs_workflow/scraper/video_downloader.py`
- 素材处理模块：`src/xhs_workflow/materials/`
- 素材包校验：`python scripts/run_pipeline.py validate`
- Manifest 发布校验：`python scripts/publish_from_manifest.py outputs/materials/2026-05-09/数据获取爬虫_公开数据流程/00_自动发推适配/publish_manifest.json`
- 发布页面 dry-run：`python scripts/run_pipeline.py publish-dry-run --port 9209`
- 真正点击发布：`python scripts/run_pipeline.py publish --port 9209`

## 关键目录

- `src/xhs_workflow/`：可复用 Python 源码。
- `scripts/`：命令行任务入口。
- `config/pipeline.example.json`：无敏感信息的配置示例。
- `docs/`：项目规范、示例和架构说明。

## 通知方式

- 自动化通知不再使用项目内 SMTP/QQ 邮箱逻辑。
- `xhs_notify.send_email(...)` 会生成 `outputs/gmail_notifications/*_gmail_notification.json` 待发送通知。
- Codex 自动化线程读取待发送通知后，使用 Gmail 插件发送；收件人优先配置 `GMAIL_RECEIVERS`，也兼容旧的 `SMTP_RECEIVERS` 作为收件人回退。

以下目录属于本地运行资产，已被 `.gitignore` 排除：

- `notebooks/`：交互式采集、发布、调试 Notebook，可能包含运行输出或登录上下文。
- `data/`：输入表格和原始数据。
- `output/`、`outputs/`：爬取结果、生成素材包和发布历史。
- `archive/`：历史素材、旧 Notebook、旧环境和系统缓存归档。
- `.deps/`、`.venv/`：本地依赖或虚拟环境。

## 发布限制

发布前必须校验：

- 标题最多 20 个字。
- 正文最多 1000 个字。
- 图片最多 18 张。

## 安全说明

- 不提交 `.env`、Cookie、账号、token、发布历史和抓取结果。
- 公开仓库只放核心代码与可复用的示例配置。
- 小红书标题最多 20 个字，正文最多 1000 个字，图片最多 18 张。
