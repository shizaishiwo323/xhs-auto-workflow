---
name: xhs-auto-workflow-material-pipeline
description: 用于运行用户本地小红书自动化全流程：优先盘点已有爬取/素材数据，足够分析时复用本地素材，不足时再用 conda base 爬取最新数据；把素材生成交给 $xhs-material-pipeline，校验素材包，通过 DrissionPage 发布器按次日白天热门时段定时发布，并用 Gmail 汇报结果。适用于 /Users/wangbin/data/jupyter/实战/爬网页/小红书/自动化工作流 的 material inventory -> optional crawl -> material package -> validate -> scheduled publish -> email report 流程。
---

# 小红书自动化编排流程

默认中文沟通。本 skill 只负责编排全流程，不重复写素材生成规则。文案、封面、配图、爆款学习、拆图、水印、素材包文件由 `$xhs-material-pipeline` 负责。

## 强制 skill 调用协议

- 进入素材生成阶段时，必须显式调用并遵循：
  ```text
  /Users/wangbin/data/jupyter/实战/爬网页/小红书/自动化工作流/.codex/skills/xhs-material-pipeline/SKILL.md
  ```
- 不允许只凭本 skill 的摘要规则、历史记忆或临时判断自行创建 `publish_manifest.json`、正文终稿、封面或配图。编排层只能做盘点、爬取、移交上下文、校验、发布和通知。
- 调用 `$xhs-material-pipeline` 前，必须先组织一段“素材生成移交说明”，包含：素材来源目录、完整参考清单、缺正文参考清单、参考图路径、历史发布差异化要求、违规规避清单、输出目录、humanizer/imagegen 证据要求。
- `$xhs-material-pipeline` 返回前，auto workflow 不得进入发布阶段；如果没有返回完整素材包，必须停止并说明“素材生成阶段未完成”，不能用已有半成品或手写 manifest 顶上。
- 如果执行环境无法真正调用 skill（例如自动任务只跑脚本而没有 LLM skill 调用能力），必须停止在“待素材生成”状态，输出 handoff prompt 或任务清单，不能继续发布。

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
- 编排层不得绕过 `$xhs-material-pipeline` 自己生成发布图或正文终稿；尤其不得用 PIL、matplotlib、HTML/CSS、SVG 或 canvas 直接生成最终封面/配图来替代 [$imagegen](/Users/wangbin/.codex/skills/.system/imagegen/SKILL.md)，也不得跳过 [$humanizer](/Users/wangbin/.codex/skills/humanizer/SKILL.md) 终稿润色。
- 发布前必须看到 `$xhs-material-pipeline` 留下的两个证据文件：`04_分析依据/humanizer润色记录.md` 和 `04_分析依据/imagegen生成记录.md`。缺任意一个都停止发布，回到素材生成阶段补齐。
- 编排层必须把“素材生成合同”显式交给 `$xhs-material-pipeline`，不能只说“生成素材包”。合同必须包含：完整参考不足时停止；正文终稿必须 humanizer；有爆款参考图或素材图时，发布图必须以参考图作为事实/字段/代码/结果/截图感/画面顺序来源，通过 imagegen 重绘或重排并加阅读指引；生成记录必须写清楚参考图路径、保留的信息点、二创方式和隐私/水印清理结果。
- 不按“主题相同”直接跳过发布：同一主题可以连续做不同角度、不同结构、不同读者问题或不同素材来源的内容。
- 如果发现同主题或相近主题已有成功发布记录，默认动作不是跳过，而是要求 `$xhs-material-pipeline` 基于同一主题生成一篇“新角度”素材包并继续发布；新包至少要更换读者问题、切入角度、字段清单、流程步骤、案例场景、封面钩子、图片结构或素材来源中的 3 项。
- 只有确认是同一篇内容时才停止：例如 `publish_manifest.json` 路径相同、发布 key 相同、标题正文高度一致且图片组合基本一致，或发布历史明确显示这一套图文已经提交成功。此时必须说明“同一篇重复提交”，不能笼统写“同主题已发布”。
- 爬取前先盘点已有素材：优先检查 `output/`、`outputs/materials/`、发布历史和当日/近期待发布素材；如果已有爬取结果、爆款参考、媒体文件和分析依据足够支撑本次选题，就不要重新爬取。只有没有可参考素材、素材明显过旧/过少、缺少详情/媒体、或用户明确要求最新数据时，才执行新的 crawl。

## 全流程

1. **预检**
   - 如流程可能变动，查看 `README.md`、`docs/ARCHITECTURE.md` 和相关脚本。
   - 验证环境：
     ```bash
     /Users/wangbin/anaconda3/bin/python -c "import pandas, openpyxl, PIL, tqdm, DrissionPage"
     ```
   - 确认 Gmail 收件人配置和浏览器端口。
   - 如存在 `docs/目前遇到的违规情况`，先提炼历史违规规避清单，移交给 `$xhs-material-pipeline`。
   - 先盘点本地已有素材和历史发布，判断是否需要爬取：
     - 查找与主题相关的最新 `output/*/summary.csv`、`links/links_topN.xlsx`、`posts/posts_topN.xlsx`、`media/`。
     - 查找 `outputs/materials/YYYY-MM-DD/` 下同主题或相近主题素材包，读取 `publish_manifest.json`、`04_分析依据/爆款参考矩阵.md`、`README.md`。
     - 查找 `outputs/publish_history/published_history.*`，确认是否只是同主题、还是同一篇内容已成功提交；同主题成功记录应作为差异化创作参考，不作为跳过理由。
     - 判断“足够分析”的最低条件：至少 3 条高互动参考同时具备可读标题、完整正文、互动字段和可迁移媒体/封面线索，且发布图片或可生成图片的素材线索明确。
     - 如果只有标题、互动数或媒体，缺少 `note_text`/`推文`/`正文`，必须向用户说明“疑似风控或详情页正文未抓到”；这些样本只能学习标题/封面入口，不能交给素材生成阶段学习正文写法。
     - 如果已有素材足够，记录复用路径并直接进入素材生成/校验；不要为了“更新”而默认爬取。若已有同主题发布记录，必须向素材生成阶段传入“避开已发布标题/正文/图片结构，生成新角度内容”的约束。

2. **爬取（仅在素材不足时执行）**
   ```bash
   /Users/wangbin/anaconda3/bin/python scripts/run_pipeline.py crawl --port 9209 --detail-limit 20
   ```
   成功后使用最新 `output/YYYY-MM-DD/`，优先交付这些文件/目录：
   - `summary.csv`
   - `links/links_all.xlsx`
   - `links/links_topN.xlsx`
   - `posts/posts_topN.xlsx`
   - `media/`
   爬取后必须先检查 `summary.csv` 或 `posts/posts_topN.xlsx`：完整参考少于 3 条时停止进入素材生成，汇报缺正文数量、疑似风控原因和 1-3 个缺正文样例标题。
   如果跳过爬取，也要在后续汇报中说明复用的本地素材目录和跳过原因。

3. **交给 `$xhs-material-pipeline` 生成素材包**
   移交上下文：
   - 本次采用的素材来源目录：优先为已盘点可复用的 `output/.../`，素材不足时才是最新爬取目录 `output/YYYY-MM-DD/`
   - 完整爆款参考清单：只包含同时有标题、正文、互动数据和媒体线索的样本；缺正文样本只能作为标题/封面参考，并标注不能学习正文
   - 当日素材历史：`outputs/materials/YYYY-MM-DD/`
   - 发布历史：`outputs/publish_history/published_history.*`
   - 社区规范：`docs/xhs_community_guidelines.pdf`
   - 违规历史：`docs/目前遇到的违规情况`
   - 输出目录：`outputs/materials/YYYY-MM-DD/选题名称/`
   - 强制素材生成合同：
     - 只能把同时具备标题、正文、互动数据和媒体线索的参考作为正文学习样本；缺正文样本只能学习标题/封面入口；
     - 文案必须先按 `$xhs-material-pipeline` 的活人感、价值感、HKR 和反 AI 味规则写草稿，再调用 `humanizer` 做终稿润色；
     - 有爆款图片、截图、表格图、代码图、数据结果图或场景图时，必须把它们作为“参考底图 + 真实数据来源”交给 imagegen；可保留字段、代码片段、数据结果、截图感、场景主体、信息层级和画面顺序，但最终发布图必须由 imagegen 重绘/重排主体，并加入醒目标题、箭头、圈画、表情贴纸或短注释来强化可读性；
     - imagegen 二创必须清理账号名、头像、水印、二维码、联系方式、私信入口和未脱敏隐私数据；目标表述为提升原创表达、可读性和合规性，不写成规避平台识别；
     - `04_分析依据/imagegen生成记录.md` 必须逐图记录参考图路径、保留的真实信息点、二创方式、最终图路径和人工检查结果；
     - `04_分析依据/humanizer润色记录.md` 必须记录润色前问题、humanizer 修改重点、最终正文和无话题标签确认。

   要求 `$xhs-material-pipeline` 生成并校验完整素材包。即使当天已有同主题可发布包或发布历史，也要优先生成新的差异化素材包；不要直接复用已成功提交的同一 manifest。返回后至少应有：
   - `00_自动发推适配/publish_manifest.json`
   - `00_自动发推适配/publish_queue.xlsx`
   - `00_自动发推适配/merged_table.xlsx`
   - `00_自动发推适配/发布图片清单.txt`
   - `04_分析依据/humanizer润色记录.md`
   - `04_分析依据/imagegen生成记录.md`
   - manifest 引用的上传图片
   - manifest 中 `humanizer_used: true`；manifest 中 `imagegen_used: true`，或存在明确的 `imagegen_skipped_reason`
   生成前必须做内容去重判断：允许并鼓励同一主题继续发布，但新包应明确区别于已发布内容，例如更换读者问题、切入角度、字段清单、流程步骤、案例场景、封面钩子或图片结构；如果只是同一 manifest 或同一套图文重复提交，应停止并说明。

4. **发布前校验**
   ```bash
   /Users/wangbin/anaconda3/bin/python scripts/validate_package.py outputs/materials/YYYY-MM-DD/选题名称
   ```
   如果出现以下情况，停止发布并说明原因：
   - 缺图、图片路径不存在、疑似拼接图未拆；
   - 标题超过 20 字、正文超过 1000 字、图片超过 18 张；
   - `body`、`正文`、`publish_row.推文` 等发布正文字段含 `#话题` 或话题占位；
   - 标题、正文、图片文字、话题、合集信息命中历史违规风险；
   - 缺少 `04_分析依据/humanizer润色记录.md`，或 manifest 没有 `humanizer_used: true`；
   - 缺少 `04_分析依据/imagegen生成记录.md`，或 manifest 既没有 `imagegen_used: true` 也没有明确的 `imagegen_skipped_reason`；
   - 上传图是编排层临时用 PIL/HTML/CSS/SVG/canvas 生成的占位图，而不是 imagegen 生成后经裁剪/压缩/水印得到的最终图；
   - `$xhs-material-pipeline` 自身校验未通过。
   - 检查文案和图片内容是否出现像创作者内部合规提醒，文件路径、prompt、manifest、校验词、账号名、二维码、私信入口、工具名等出现在最终图片或正文里，如果有，必须停止发布，回到素材生成阶段修改 imagegen prompt 或 humanizer 终稿要求，重新生成素材包。

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
   - 本次素材来源：复用的本地素材路径，或新爬取输出路径和数量；
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
