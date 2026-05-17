# AGENTS.md

本目录用于小红书素材创作、图片处理、自动发布整理与相关代码维护。默认用中文沟通。

## 环境约定

- 本项目默认使用 `conda` 的 `base` 环境运行 Python、Notebook、爬虫、素材生成、发布调试和相关脚本。
- 执行项目命令前，优先确认或切换到 `base` 环境，例如 `conda activate base`；需要非 `base` 环境时，必须先说明原因并得到用户确认。

## 强制技能调用

- 生成可发布素材包时，正文终稿必须调用 `/Users/wangbin/.codex/skills/humanizer/SKILL.md` 润色；不要只“参考”规则后自己改写。
- 需要新封面或新配图时，必须调用 `/Users/wangbin/.codex/skills/.system/imagegen/SKILL.md` 生成最终视觉来源；不要用 PIL、matplotlib、HTML/CSS、SVG、canvas 或截图式代码图替代 imagegen。
- 本地代码只允许做裁剪、压缩、拆图、搬运、加水印和 manifest/Excel 适配，不允许作为最终发布图的主要生成方式，除非用户明确要求。
- 每个可发布素材包必须在 `04_分析依据/` 记录 `humanizer润色记录.md` 和 `imagegen生成记录.md`；如果用户明确只用已有图片，`imagegen生成记录.md` 必须写明跳过原因。
- 发布前检查 manifest：`humanizer_used` 必须为 `true`；`imagegen_used` 必须为 `true`，或存在明确的 `imagegen_skipped_reason`。

## 代码维护边界

- 以后对本地项目文件做任何代码、Notebook、脚本或配置改动时，必须遵循 `/Users/wangbin/.codex/skills/karpathy-guidelines/SKILL.md`：先明确假设和成功标准，优先最简单方案，只做与用户请求直接相关的最小改动，匹配现有风格，并验证结果。
- `archive/备份` 只作参考和回溯基线，默认不得修改其中任何 Notebook、脚本或资源文件。
- 已跑通的发布与定时流程优先参考：
  - `/Users/wangbin/data/jupyter/实战/爬网页/小红书/自动化工作流/archive/备份/debug.ipynb`
  - `/Users/wangbin/data/jupyter/实战/爬网页/小红书/自动化工作流/archive/备份/xhs媒体下载/正式.ipynb`
- 不主动重写爬虫、定时、发布、登录态、上传、填写、点击等核心流程。
- 主要职责是整理现有流程：函数拆分、命名、配置集中、路径整理、日志、异常处理、发布前校验、Notebook 顺序、重复代码合并、说明文档。
- 规范化函数时优先包裹和复用现有代码，保持输入输出、执行顺序、等待逻辑、选择器、请求参数、文件命名和调度触发方式不变。
- 用户要求完善代码逻辑时，默认同时检查并同步修改 `notebooks` 和 `scripts` 中的相关代码，避免规则漂移。
- 发现明显 bug 或风险时，先说明位置、影响和最小修改建议；只有风险直接阻塞当前任务或用户确认后，才小范围修复。
- 修改 Notebook 或脚本前，先定位成功代码中的对应单元、函数或变量，说明本次只整理哪一层流程。
- 调试浏览器自动化时，优先参考 DrissionPage 4.0 官方文档：`https://drissionpage.cn/dp40docs/get_start/installation`；文档不足时再看本地 `DrissionPage` 源码。

## 删除限制

禁止批量删除文件或目录。

不要使用：

- `del /s`
- `rd /s`
- `rmdir /s`
- `Remove-Item -Recurse`
- `rm -rf`

需要删除文件时，只能一次删除一个明确路径的文件。若需要批量删除，应停止操作，并请用户手动删除。

## 协作方式

- 素材不足时，先基于已有内容给出可用版本，再说明还缺什么能继续优化。
- 涉及品牌、产品功效、医疗、金融、法律等高风险内容时，不夸大效果，并提醒核实合规表述。
- 用户提供参考账号或爆款链接时，先分析标题、封面、正文结构和评论区需求，再迁移方法，不直接抄袭。
- 每次交付尽量给可直接发布或轻改后可发布的版本。
