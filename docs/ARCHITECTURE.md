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
4. 用 `scripts/validate_package.py` 或 `scripts/run_pipeline.py validate` 检查标题、正文、图片数量和图片文件。
5. 用 `scripts/publish_from_manifest.py` 读取 manifest 进行发布页面填充。

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
- 校验标题、正文和图片数量。
- 按 `upload_order` 上传图片。
- 填写标题和正文。
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
