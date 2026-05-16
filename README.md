# 小红书自动化工作流

这个公开仓库只保留小红书自动化工作流的核心代码、示例配置和项目说明。
本地敏感配置、登录态、抓取数据、生成素材、发布历史、媒体文件和 Notebook 运行产物不会随仓库发布。

项目按四段流水线整理：

1. 爬取数据：采集关键词链接、笔记详情、图片/视频媒体。
2. 账号复盘：采集自己账号笔记表现，并反哺下一轮素材生成策略。
3. 生成素材：生成小红书标题、正文、封面、轮播图和发布适配清单。
4. 自动发布：读取 `publish_manifest.json`，校验平台限制后填充小红书创作者后台。
   发布话题由素材生成阶段提前确定，优先写入 `recommended_topics`，发布器会在正文末尾逐个输入 `#话题`。
   发布合集会在声明原创之后处理：统一归入 `塔罗牌合集`、`数据资源的合集`、`随便发发合集` 三个已创建合集，找不到目标合集时停止，不自动创建。

## 当前入口

- 图片下载模块：`src/xhs_workflow/scraper/image_downloader.py`
- 视频下载模块：`src/xhs_workflow/scraper/video_downloader.py`
- 账号数据抓取：`python scripts/fetch_account_metrics.py --port 9209`
- 账号表现复盘：`python scripts/analyze_account_performance.py --account-metrics <小红书笔记数据分析.xlsx>`
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
- `publish_manifest.json` 必须包含话题字段，优先使用 `recommended_topics`；话题来自爆款笔记分析，不写入正文或 `推文` 字段。
- 合集固定使用三类：塔罗内容归入 `塔罗牌合集`；数据爬取、数据分析、公开数据、表格字段等内容归入 `数据资源的合集`；热点素材、泛内容和其他内容归入 `随便发发合集`。
- 塔罗牌主题允许发布，标题、正文自然语言和 `recommended_topics` 可以直接出现 `塔罗牌`；但内容只能按牌面知识、卡牌文化、娱乐参考、自我觉察或情绪复盘表达，不能写成预测未来、改运消灾、实现愿望、付费占卜服务或互动换福利。

## 安全说明

- 不提交 `.env`、Cookie、账号、token、发布历史和抓取结果。
- 公开仓库只放核心代码与可复用的示例配置。
- 小红书标题最多 20 个字，正文最多 1000 个字，图片最多 18 张。
