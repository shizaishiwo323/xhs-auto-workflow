# Account Performance Feedback

Use this reference when material generation should learn from the user's own Xiaohongshu account data.

## Inputs

- Account metrics table from the creator backend, usually `小红书笔记数据分析.xlsx`, with columns like `笔记标题`, `日期`, `浏览量`, `评论量`, `点赞量`, `收藏量`, `转发量`, `add_time`.
- Historical publish log: `outputs/publish_history/published_history.jsonl` or `.xlsx`/`.csv`.
- Historical material packages: `outputs/materials/YYYY-MM-DD/选题名/00_自动发推适配/publish_manifest.json`, plus `README.md` and existing notes under `04_分析依据/` when present.

## Project Interface

In the user's workflow project, the notebook-derived account-data interface lives in:

```bash
python scripts/fetch_account_metrics.py --port 9209
```

It opens the creator note manager through the existing Chromium remote-debugging port and saves a new account metrics Excel under `outputs/account_metrics/YYYY-MM-DD/`.

To turn account metrics into generation guidance:

```bash
python scripts/analyze_account_performance.py --account-metrics <小红书笔记数据分析.xlsx>
```

The analysis writes:

- `outputs/account_performance/<timestamp>/account_performance_report.md`
- `outputs/account_performance/<timestamp>/account_performance_feedback.json`
- `outputs/account_performance/latest_optimization.md`
- `outputs/account_performance/latest_optimization.json`

Read `latest_optimization.json` first when it exists; read the Markdown report for human-readable reasoning.

## Scoring

Use relative account performance, not absolute platform averages. Normalize `万`, `w`, `k`, and blank values. Compute:

- `like_rate = 点赞量 / 浏览量`
- `save_rate = 收藏量 / 浏览量`
- `comment_rate = 评论量 / 浏览量`
- comment-first engagement: `点赞 + 2*收藏 + 4*评论 + 2*转发`
- discussion efficiency: `评论量 / (点赞量 + 收藏量 + 1)`

For this account's current goal, comments and comment rate are the primary signal. Saves remain a secondary usefulness signal for knowledge/tool notes, but do not let high saves override weak comments when selecting爆款 references. Classify notes by account-relative quantiles:

- top quartile: `加固`
- middle: `观察`
- bottom quartile: `避免/重做`

## Translate Data Into Generation Rules

Use high-comment/high-discussion notes to preserve:

- title hook: e.g. 避坑纠错, 数字/步骤, 问题解决, AI工具, 短强结论;
- cover promise: the first image must show the result, checklist, workflow, table, or clear pain point;
- carousel rhythm: cover -> problem/conflict -> A/B choice or boundary -> steps/table -> pitfall -> grounded conclusion;
- content frame: public data source, workflow, field/table, traceability, text/comment analysis, AI workflow, scenario comparison;
- comment trigger: a concrete question, decision fork, field-choice dispute, boundary condition, or reader scenario that people can answer from experience;
- body rhythm: strong pain opening -> specific case/conflict -> decision fork -> numbered steps/checklist -> one real pitfall -> grounded conclusion -> content-driven open question.

Use weak notes to avoid repeating:

- low views: do not only rewrite the body; rework cover, title specificity, and target reader first;
- high views but low saves: add reusable value such as tables, templates, source list, checklist, or step-by-step workflow;
- high views but low comments: add a specific可回答问题, A/B choice, boundary condition, or experience-sharing prompt tied to the note's method;
- many comments but low quality: avoid争吵、求资源、福利交换、互关互赞, and rebuild the prompt around useful cases or decisions;
- low likes: make the opening more concrete and closer to a real personal/workflow复盘;
- image issues: missing files, too-small images, horizontal contact sheets, unclear hierarchy, or weak first-image text must block publish-ready output;
- off-niche experiments: keep them separate unless the user explicitly wants to test a different account direction.

## Package Output Contract

When account feedback affects a generated package:

- save a short applied-feedback note at `04_分析依据/账号数据复盘.md`;
- add `performance_feedback` to `publish_manifest.json` only as metadata;
- never put diagnostic notes, hashtags, or topic suggestions into the post body/`推文`;
- keep title <= 20 characters, body <= 1000 characters, and images <= 18.
