# Project Commands

## Root And Python

Run all project workflow commands from:

```text
/Users/wangbin/data/jupyter/实战/爬网页/小红书/自动化工作流
```

Use conda base Python for project code:

```text
/Users/wangbin/anaconda3/bin/python
```

Do not use system `python3` for crawler, material adapters, validators, publisher, or notification helper. `scripts/run_pipeline.py` launches child scripts with `sys.executable`, so starting it with conda base keeps downstream code in base too.

## Crawl

Primary entry:

```bash
/Users/wangbin/anaconda3/bin/python scripts/run_pipeline.py crawl --port 9209 --detail-limit 20
```

Direct scraper entry:

```bash
/Users/wangbin/anaconda3/bin/python scripts/run_scraper.py --port 9209 --detail-limit 20
```

Useful options:

- `--keyword <word>` can be repeated.
- `--keywords-file <path>` reads one keyword per line.
- `--links-only` collects links without detail/media download.
- `--details-only` reads existing links and fetches details/media.
- `--output-root <path>` overrides the default crawl output path.

Expected crawl outputs:

```text
output/YYYY-MM-DD/
├── links/links_all.csv
├── links/links_all.xlsx
├── links/links_topN.csv
├── links/links_topN.xlsx
├── posts/posts_topN.csv
├── posts/posts_topN.xlsx
├── media/
└── summary.csv
```

The README may mention `outputs/crawl`, but `ScraperConfig` defaults to `output/YYYY-MM-DD` unless `--output-root` is supplied. Inspect actual run output.

## Material Generation

Material generation must be delegated to `$xhs-material-pipeline`. Do not execute an equivalent package-creation process directly from this skill.

Pass `$xhs-material-pipeline`:

- newest crawl folder: `output/YYYY-MM-DD/`;
- same-day package history: `outputs/materials/YYYY-MM-DD/`;
- publish history: `outputs/publish_history/published_history.*`;
- community guideline PDF: `docs/xhs_community_guidelines.pdf`;
- required package destination: `outputs/materials/YYYY-MM-DD/选题名称/`.

`$xhs-material-pipeline` owns reference learning, copywriting, visual creation, imagegen usage, split/watermark handling, adapter files, README, manifest updates, and its own validation. This workflow resumes only after that skill returns a complete package.

Expected publish package:

```text
outputs/materials/YYYY-MM-DD/选题名称/
├── 00_自动发推适配/
│   ├── merged_table.xlsx
│   ├── publish_queue.xlsx
│   ├── publish_manifest.json
│   └── 发布图片清单.txt
├── 01_文案/
├── 02_封面/
├── 03_配图/
├── 04_分析依据/
└── README.md
```

Manifest contract:

- `recommended_title` or `publish_row.标题` is the final title.
- `body` or `publish_row.推文` is the final body.
- `images[]` must list final upload images with `path` and `upload_order`.
- Cover image should be upload order 1.
- Body must not include hashtag topic blocks.

## Validate

Validate a package:

```bash
/Users/wangbin/anaconda3/bin/python scripts/validate_package.py outputs/materials/YYYY-MM-DD/选题名称
```

Validate the latest manifest package selected by `run_pipeline.py`:

```bash
/Users/wangbin/anaconda3/bin/python scripts/run_pipeline.py validate
```

Validation limits:

- title: 20 characters max;
- body: 1000 characters max;
- images: 18 max;
- all image paths must exist;
- wide contact sheets must be split before upload.

## Scheduled Publish

Validation only:

```bash
/Users/wangbin/anaconda3/bin/python scripts/publish_from_manifest.py <manifest>
```

Fill page, no submit:

```bash
/Users/wangbin/anaconda3/bin/python scripts/publish_from_manifest.py <manifest> --port 9209 --fill
```

Real scheduled publish for one manifest:

```bash
/Users/wangbin/anaconda3/bin/python scripts/publish_from_manifest.py <manifest> --port 9209 --submit --schedule-time "YYYY-MM-DD 12:00"
```

Use the next calendar day for `YYYY-MM-DD`. Prefer `12:00`; if that slot is not suitable, use another daytime hot slot such as `10:30` or `16:00`.

Batch dry-run:

```bash
/Users/wangbin/anaconda3/bin/python scripts/run_pipeline.py publish-batch --materials-date YYYY-MM-DD --port 9209 --dry-run --slots "10:30,12:00,16:00"
```

Batch scheduled publish:

```bash
/Users/wangbin/anaconda3/bin/python scripts/run_pipeline.py publish-batch --materials-date YYYY-MM-DD --port 9209 --slots "10:30,12:00,16:00"
```

Batch publisher behavior:

- Discovers `outputs/materials/YYYY-MM-DD/*/00_自动发推适配/publish_manifest.json`.
- Skips publish keys already present in successful history.
- Schedules pending items from the next valid day using the supplied daytime slots.
- Writes history to `outputs/publish_history/published_history.xlsx`, `.csv`, and `.jsonl`.

## Gmail Notification

The project helper `xhs_notify.send_email(...)` writes JSON outbox files instead of sending SMTP:

```text
outputs/gmail_notifications/*_gmail_notification.json
```

The JSON contains:

- `to`
- `subject`
- `body`
- `attachment_files`
- `status`

When the workflow must send a real email, use the Gmail plugin with the JSON payload or with a freshly composed status report. Do not claim the email was sent until the Gmail plugin call succeeds.

Recipient lookup order in the project helper:

1. `GMAIL_RECEIVERS`
2. `GMAIL_TO`
3. `XHS_GMAIL_RECEIVERS`
4. `SMTP_RECEIVERS`
5. `NOTIFY_EMAIL`

If no recipient is configured, ask the user for a recipient before final notification.

## Failure Handling

Send a Gmail report for:

- crawl browser/login/CAPTCHA failure;
- empty crawl result;
- material generation failure;
- validation failure;
- publish fill failure;
- publish submit failure;
- no success marker after scheduled submit;
- missing Gmail recipient or plugin failure.

For each failure, include the stage, exception summary, relevant path, and the next smallest fix.
