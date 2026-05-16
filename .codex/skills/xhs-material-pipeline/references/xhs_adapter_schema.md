# XHS Auto-post Adapter Schema

## Current notebook expectation

The local notebook pattern reads:

```python
df = pd.read_excel(".../merged_table.xlsx")
biaoti = df["标题"].tolist()
tuiwen = df["推文"].tolist()
fengmian = df["封面地址"].tolist()
```

The publisher uploads:

1. cover path from `封面地址`;
2. additional image paths from its configured image folders;
3. fixed project images in `总结/1.png`, `总结/2.png`, `总结/3.png` in some flows.

When producing a material package, keep a self-contained image order in `publish_manifest.json` and `发布图片清单.txt` so the notebook can later be upgraded to read exact upload paths.

## Recommended package files

`00_自动发推适配/merged_table.xlsx`:

- `标题`: direct publish title, <= 20 chars.
- `推文`: direct publish body, <= 1000 chars.
- `封面地址`: absolute path to the cover image.
- `Unnamed: 8`: optional folder containing additional split carousel images.

`00_自动发推适配/publish_manifest.json`:

```json
{
  "date": "YYYY-MM-DD",
  "topic": "选题",
  "status": "ready_for_xhs_auto_publish",
  "limits_check": {
    "title_chars": 10,
    "title_limit": 20,
    "body_chars": 470,
    "body_limit": 1000,
    "image_count": 4,
    "image_limit": 18
  },
  "images": [
    {"role": "cover", "path": "/abs/cover.png", "upload_order": 1},
    {"role": "carousel_page", "path": "/abs/page_01.png", "upload_order": 2}
  ]
}
```

Always use absolute paths in the adapter files.
