# 项目架构说明

## 一、目标流程

项目未来应收敛为一条稳定流水线：

```text
01 爬取数据 -> 02 生成素材 -> 03 校验发布 -> 04 自动发布/定时发布
```

本仓库公开版本只保留核心代码、示例配置和 Markdown 文档；Notebook、抓取数据、生成素材、媒体文件、发布历史、虚拟环境和本地归档均保留在本机，不提交到 GitHub。

当前最可用的本地落地方式是：

1. 用 `notebooks/scraper/xhs_scraper_formal.ipynb` 采集关键词笔记、详情和媒体。
2. 把生成结果写入 `outputs/materials/YYYY-MM-DD/选题名/`。
3. 每个选题目录产出 `00_自动发推适配/publish_manifest.json`。
4. 在 `publish_manifest.json` 中写入基于爆款参考提炼的 `recommended_topics`；必要来源说明写入 `README.md` 或已有分析记录，不再生成固定的 `爆款参考矩阵.md`。
5. 合集固定归入 `塔罗牌合集`、`数据资源的合集`、`随便发发合集` 三类；发布时只选择已存在合集，找不到目标合集则停止。
6. 塔罗牌内容可以在标题、正文自然语言和 `recommended_topics` 中直接出现 `塔罗牌`，但必须按牌面知识、卡牌文化、娱乐参考、自我觉察或情绪复盘处理，避开预测未来、改运消灾、实现愿望、付费占卜服务和互动换福利。
7. 用 `scripts/validate_package.py` 或 `scripts/run_pipeline.py validate` 检查标题、正文、话题、合集、图片数量和图片文件。
8. 用 `scripts/publish_from_manifest.py` 读取 manifest 进行发布页面填充。

## 二、目录层级

```text
.
├── src/xhs_workflow/
│   ├── notify.py
│   ├── scraper/
│   │   ├── image_downloader.py
│   │   └── video_downloader.py
│   ├── materials/
│   │   ├── split_carousel_images.py
│   │   ├── validate_xhs_package.py
│   │   └── watermark_images.py
│   └── publisher/
├── scripts/
│   ├── run_pipeline.py
│   ├── validate_package.py
│   └── publish_from_manifest.py
├── notebooks/        # 本地运行资产，不提交
├── outputs/          # 本地结果数据，不提交
├── data/input/       # 本地输入数据，不提交
├── docs/
└── archive/
```

## 三、项目逻辑

### 1. 爬取层

核心职责：

- 按关键词抓取搜索结果链接。
- 抓取笔记标题、正文、作者、点赞、收藏、评论等字段。
- 下载图片/视频媒体。
- 输出到 `outputs/crawl/YYYY-MM-DD/`。

当前代码：

- `notebooks/scraper/xhs_scraper_formal.ipynb`
- `src/xhs_workflow/scraper/image_downloader.py`
- `src/xhs_workflow/scraper/video_downloader.py`

### 2. 素材生成层

核心职责：

- 基于爬取结果筛选爆点、选题和参考素材。
- 生成标题、正文、封面、轮播图。
- 给图片加水印、拆分横向拼版、生成发布适配表。
- 输出到 `outputs/materials/YYYY-MM-DD/选题名/`。

每个可发布选题建议固定包含：

```text
00_自动发推适配/
01_文案/
02_封面/
03_配图/
04_分析依据/
README.md
```

### 3. 发布层

核心职责：

- 读取 `publish_manifest.json`。
- 校验标题、正文、话题、合集和图片数量。
- 按 `upload_order` 上传图片。
- 填写标题和正文。
- 正文末尾光标定位完成后，按 `#话题 -> 等待 0.5 秒 -> 回车` 的顺序逐个输入 `recommended_topics`。
- 声明原创后展开合集列表，按三分类选择 `塔罗牌合集`、`数据资源的合集` 或 `随便发发合集`；没有目标合集时停止并报错，不自动创建。
- dry-run 默认不点击发布，带 `--submit` 才真正点击发布按钮。

当前代码：

- `scripts/publish_from_manifest.py`
- `notebooks/publisher/xhs_auto_publish_0509.ipynb`

## 四、保留与归档原则

公开仓库保留的内容：

- 可复用 Python 源码。
- 命令行入口脚本。
- 无敏感信息的配置示例。
- 架构与使用说明。
- 邮件通知工具。

本机保留但不提交的内容：

- 当前爬取结果和生成素材。
- 自动发布 Notebook 与调试 Notebook。
- 社区规范 PDF。
- 历史封面图库。
- 旧草稿 Notebook。
- 旧虚拟环境 `.venv`。
- `.DS_Store`、`__pycache__`、`.ipynb_checkpoints` 等系统/缓存文件。

没有执行批量删除；如需释放磁盘空间，建议人工确认后再删除 `archive/envs/xhs_media_download_venv` 和历史素材库。
