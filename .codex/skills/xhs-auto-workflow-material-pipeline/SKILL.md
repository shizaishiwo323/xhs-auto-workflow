---
name: xhs-auto-workflow-material-pipeline
description: 用于运行用户本地小红书自动化全流程：用 conda base 爬取最新数据，把素材生成交给 $xhs-material-pipeline，校验素材包，通过 DrissionPage 发布器按次日白天热门时段定时发布，并用 Gmail 汇报结果。适用于 /Users/wangbin/data/jupyter/实战/爬网页/小红书/自动化工作流 的 crawl -> material package -> validate -> scheduled publish -> email report 流程。
---

# 小红书自动化编排流程

默认中文沟通。本 skill 只负责编排全流程，不重复写素材生成规则。文案、封面、配图、爆款学习、拆图、水印、素材包文件由 `$xhs-material-pipeline` 负责。

## 固定路径与硬规则

- 项目根目录：
  ```text
  /Users/wangbin/data/jupyter/实战/爬网页/小红书/自动化工作流
  ```
- 项目 Python 固定使用：
  ```text
  /Users/wangbin/anaconda3/bin/python
  ```
- 默认浏览器远程调试端口：`9209`。
- 不改 `archive/备份`，除非用户明确要求。
- 禁止批量删除文件或目录。
- 测试素材生成时，到 `$xhs-material-pipeline` 生成并校验素材包为止；用户没要求发布时，不打开发布器、不发 Gmail。
- 真实发布默认定时发布，不默认立即发布；发布时间参考 `docs/发布时间原则.md`，优先匹配内容类型和目标人群活跃时间。
- 发布前必须说明：manifest 路径、标题、正文长度、图片数量、定时时间。

## 全流程

1. **预检**
   - 如流程可能变动，查看 `README.md`、`docs/ARCHITECTURE.md` 和相关脚本。
   - 验证环境：
     ```bash
     /Users/wangbin/anaconda3/bin/python -c "import pandas, openpyxl, PIL, tqdm, DrissionPage"
     ```
   - 确认 Gmail 收件人配置和浏览器端口。
   - 如存在 `docs/目前遇到的违规情况`，先提炼历史违规规避清单，移交给 `$xhs-material-pipeline`。

2. **爬取**
   ```bash
   /Users/wangbin/anaconda3/bin/python scripts/run_pipeline.py crawl --port 9209 --detail-limit 20
   ```
   成功后使用最新 `output/YYYY-MM-DD/`，优先交付这些文件/目录：
   - `summary.csv`
   - `links/links_all.xlsx`
   - `links/links_topN.xlsx`
   - `posts/posts_topN.xlsx`
   - `media/`

3. **交给 `$xhs-material-pipeline` 生成素材包**
   移交上下文：
   - 最新爬取目录：`output/YYYY-MM-DD/`
   - 当日素材历史：`outputs/materials/YYYY-MM-DD/`
   - 发布历史：`outputs/publish_history/published_history.*`
   - 社区规范：`docs/xhs_community_guidelines.pdf`
   - 违规历史：`docs/目前遇到的违规情况`
   - 输出目录：`outputs/materials/YYYY-MM-DD/选题名称/`

   要求 `$xhs-material-pipeline` 生成并校验完整素材包。返回后至少应有：
   - `00_自动发推适配/publish_manifest.json`
   - `00_自动发推适配/publish_queue.xlsx`
   - `00_自动发推适配/merged_table.xlsx`
   - `00_自动发推适配/发布图片清单.txt`
   - manifest 引用的上传图片

4. **发布前校验**
   ```bash
   /Users/wangbin/anaconda3/bin/python scripts/validate_package.py outputs/materials/YYYY-MM-DD/选题名称
   ```
   如果出现以下情况，停止发布并说明原因：
   - 缺图、图片路径不存在、疑似拼接图未拆；
   - 标题超过 20 字、正文超过 1000 字、图片超过 18 张；
   - `body`、`正文`、`publish_row.推文` 等发布正文字段含 `#话题` 或话题占位；
   - 标题、正文、图片文字、话题、合集信息命中历史违规风险；
   - `$xhs-material-pipeline` 自身校验未通过。

5. **定时发布**
   按 `docs/发布时间原则.md` 选择次日黄金时段：
   - 通用高峰：工作日 `08:00-09:30`、`12:00-14:00`、`18:00-19:30`、`21:30-23:00`；周末 `10:30-13:30`、`18:00-23:00`。
   - 数据分析/学习教程/知识干货优先 `20:00-21:30` 或午间 `12:00-14:00`；情绪向内容可选 `22:00-23:00`；轻松娱乐可选 `12:00-14:00`。
   - 单条默认优先次日 `20:30`；如果内容更适合午休阅读，改用 `12:00`。

   单条发布命令：
   ```bash
   /Users/wangbin/anaconda3/bin/python scripts/publish_from_manifest.py <manifest> --port 9209 --submit --schedule-time "YYYY-MM-DD 20:30"
   ```
   多条默认时段：
   ```bash
   /Users/wangbin/anaconda3/bin/python scripts/run_pipeline.py publish-batch --materials-date YYYY-MM-DD --port 9209 --slots "12:00,20:30,21:30"
   ```
   只有用户明确要求测试时才加 `--dry-run`。只有用户明确要求立即发布时，才允许不传 `--schedule-time`。

6. **Gmail 汇报**
   发布成功、失败、跳过或 dry-run 后，用 Gmail 插件发送汇报。不要只依赖项目生成的 pending notification JSON。

   邮件至少包含：
   - 爬取输出路径和数量；
   - 素材包路径、manifest 路径；
   - 标题、正文长度、图片数量；
   - 定时时间；
   - 发布状态和页面成功提示；
   - 历史记录路径或失败通知 JSON 路径。

## 发布器关键约束

- 发布内容只能来自 `$xhs-material-pipeline` 产出的 `publish_manifest.json`。
- 正文载体不能包含话题标签；话题只能从 manifest 的独立元数据读取。
- 正文填写后，发布器必须额外输入一个换行，使光标停在正文末尾。
- 话题输入顺序固定：`body_field.input(f"#{topic}")` -> `sleep(0.5)` -> `body_field.input("\n")`，逐个输入。
- 不再点击小红书推荐话题 UI。
- 合集选择/创建必须在声明原创之后、定时发布之前。优先复用相近合集，没有合适合集才新建。
- 合集字段优先 `collection_name`，兼容 `collection_title`、`target_collection`、`collection`；合集名 <=20 字，简介 <=50 字。

## 调试原则

- 保留已跑通的爬虫和发布流程，只做最小修复。
- 爬取、素材生成、发布、通知的问题分开处理。
- 浏览器、登录、验证码、选择器漂移、环境依赖失败时，先报告具体阶段，再做最小改动。
- DrissionPage 行为不确定时，先查官方 4.0 文档或本地库源码。
- 素材包质量不够时，回到 `$xhs-material-pipeline` 修复或重生成，不发布占位图。

## 参考

需要精确命令、路径或通知细节时再读：

- `references/project_commands.md`
- `docs/发布时间原则.md`
