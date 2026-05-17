---
name: xhs-auto-workflow-material-pipeline
description: 用于运行本地小红书图文自动化全流程：盘点已有素材，必要时爬取最新数据，把素材生成交给 xhs-material-pipeline，校验素材包，通过 DrissionPage 定时发布，并用 Gmail 汇报结果。
---

# 小红书自动化编排流程

默认中文沟通。本 skill 只负责编排，不重复写素材生成规则。文案、封面、配图、爆款学习、拆图、水印、素材包文件由 `xhs-material-pipeline` 负责。

先遵循共享规则：

```text
/Users/wangbin/data/jupyter/实战/爬网页/小红书/自动化工作流/.codex/skills/xhs-shared-rules/SKILL.md
```

## 边界

- 可以做：预检、盘点、判断是否爬取、运行爬虫、组织素材生成移交说明、校验素材包、定时发布、Gmail 汇报。
- 不可以做：绕过 `xhs-material-pipeline` 直接写正文终稿、生成封面/配图、手写半成品 manifest 顶上、发布缺证据素材包。
- 测试素材生成时，到素材包生成和校验为止；用户没要求发布时，不打开发布器、不发 Gmail。

## 固定路径与硬规则

- 项目根目录：
  ```text
  /Users/wangbin/data/jupyter/实战/爬网页/小红书/自动化工作流
  ```
- 项目 Python：
  ```text
  /Users/wangbin/anaconda3/bin/python
  ```
- 默认浏览器远程调试端口：`9209`。
- 不改 `archive/备份`，除非用户明确要求。
- 真实发布默认定时发布，不默认立即发布；发布时间参考 `docs/发布时间原则.md`。
- 发布前必须说明：manifest 路径、标题、正文长度、图片数量、定时时间。

## 全流程

1. **预检**
   - 如流程可能变动，查看 `README.md`、`docs/ARCHITECTURE.md` 和相关脚本。
   - 验证环境：
     ```bash
     /Users/wangbin/anaconda3/bin/python -c "import pandas, openpyxl, PIL, tqdm, DrissionPage"
     ```
   - 确认 Gmail 收件人配置和浏览器端口。
   - 如存在 `docs/目前遇到的违规情况`，先提炼历史违规规避清单，交给素材生成阶段。

2. **盘点已有素材**
   - 查找与主题相关的最新 `output/*/summary.csv`、`links/links_topN.xlsx`、`posts/posts_topN.xlsx`、`media/`。
   - 查找 `outputs/materials/YYYY-MM-DD/` 下同主题或相近主题素材包，读取 `publish_manifest.json`、`README.md` 和已有分析记录。
   - 查找 `outputs/publish_history/published_history.*`，确认是同主题还是同一篇内容已成功提交。
   - “足够分析”的最低条件：至少 3 条高互动参考同时具备可读标题、完整正文、互动字段和可迁移媒体/封面线索，且发布图片或可生成图片的素材线索明确。
   - 如果只有标题、互动数或媒体，缺少 `note_text`/`推文`/`正文`，说明“疑似风控或详情页正文未抓到”；这些样本只能作为标题/封面参考。
   - 如果已有素材足够，记录复用路径并直接进入素材生成/校验；不要为了“更新”默认爬取。

3. **爬取，仅在素材不足时执行**
   ```bash
   /Users/wangbin/anaconda3/bin/python scripts/run_pipeline.py crawl --port 9209 --detail-limit 20
   ```
   成功后使用最新 `output/YYYY-MM-DD/`，优先交付：
   - `summary.csv`
   - `links/links_all.xlsx`
   - `links/links_topN.xlsx`
   - `posts/posts_topN.xlsx`
   - `media/`

   爬取后检查 `summary.csv` 或 `posts/posts_topN.xlsx`。完整参考少于 3 条时停止进入素材生成，汇报缺正文数量、疑似风控原因和 1-3 个缺正文样例标题。

4. **移交给 `xhs-material-pipeline`**
   - 必须显式调用并遵循：
     ```text
     /Users/wangbin/data/jupyter/实战/爬网页/小红书/自动化工作流/.codex/skills/xhs-material-pipeline/SKILL.md
     ```
   - 移交说明必须包含：
     - 素材来源目录；
     - 完整爆款参考清单；
     - 缺正文参考清单，并标注不能学习正文写法；
     - 参考图路径；
     - 当日素材历史和发布历史；
     - 历史违规规避清单；
     - 同主题差异化要求；
     - 输出目录；
     - 共享规则中的 humanizer/imagegen 证据要求。
   - `xhs-material-pipeline` 返回完整素材包前，不进入发布阶段。
   - 如果执行环境无法真正调用 skill，停止在“待素材生成”状态，输出 handoff prompt 或任务清单。

5. **发布前校验**
   ```bash
   /Users/wangbin/anaconda3/bin/python scripts/validate_package.py outputs/materials/YYYY-MM-DD/选题名称
   ```
   出现以下情况时停止发布：
   - 缺图、图片路径不存在、疑似拼接图未拆；
   - 标题超过 20 字、正文超过 1000 字、图片超过 18 张；
   - 发布正文字段含 `#话题` 或话题占位；
   - 标题、正文、图片文字、话题、合集信息命中历史违规风险；
   - 缺少 `04_分析依据/humanizer润色记录.md`，或 manifest 没有 `humanizer_used: true`；
   - 缺少 `04_分析依据/imagegen生成记录.md`，或 manifest 既没有 `imagegen_used: true` 也没有明确的 `imagegen_skipped_reason`；
   - 上传图是临时占位图，或出现内部合规提醒、文件路径、prompt、manifest、校验词、账号名、二维码、私信入口、工具名等读者不该看到的内容；
   - `xhs-material-pipeline` 自身校验未通过。

6. **定时发布**
   按 `docs/发布时间原则.md` 选择次日黄金时段。单条默认优先次日 `20:30`；如果内容更适合午休阅读，改用 `12:00`。

   单条发布命令：
   ```bash
   /Users/wangbin/anaconda3/bin/python scripts/publish_from_manifest.py <manifest> --port 9209 --submit --schedule-time "YYYY-MM-DD 20:30"
   ```

   多条默认时段：
   ```bash
   /Users/wangbin/anaconda3/bin/python scripts/run_pipeline.py publish-batch --materials-date YYYY-MM-DD --port 9209 --slots "12:00,20:30,21:30"
   ```

   只有用户明确要求测试时才加 `--dry-run`。只有用户明确要求立即发布时，才允许不传 `--schedule-time`。

7. **Gmail 汇报**
   发布成功、失败、跳过或 dry-run 后，用 Gmail 插件发送汇报。不要只依赖项目生成的 pending notification JSON。

   邮件至少包含：
   - 本次素材来源；
   - 素材包路径、manifest 路径；
   - 标题、正文长度、图片数量；
   - 定时时间；
   - 发布状态和页面成功提示；
   - 历史记录路径或失败通知 JSON 路径。

## 发布器关键约束

- 发布内容只能来自 `xhs-material-pipeline` 产出的 `publish_manifest.json`。
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
- 素材包质量不够时，回到 `xhs-material-pipeline` 修复或重生成，不发布占位图。

## 参考

- 共享规则：`../xhs-shared-rules/SKILL.md`
- 精确命令和路径：`references/project_commands.md`
- 发布时间原则：`docs/发布时间原则.md`
