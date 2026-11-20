# eml2md

将导出的 `.eml` 邮件批量转换为 Markdown，并把正文图片下载到本地 `assets/`，生成可离线阅读的归档。

## 环境要求

- Python 3.9 或更高版本（已在 3.11 测试）
- `beautifulsoup4`
- `lxml`

```bash
pip install beautifulsoup4 lxml
```

## 快速开始

在项目根目录执行：

```bash
python eml2md.py
```

默认读取当前目录下的所有 `.eml`，输出到 `output/`：

```text
output/
├── 2026-07-20-1204-Subdue your enemy without fighting.md
├── ...
└── assets/
    └── 44472206-..._1798x1018.jpeg
```

Markdown 中的图片使用相对路径：

```markdown
![Eon Images | Return of Ten Thousand under Xenophon](assets/ca82dc2d-c543-4a7d-ad62-b3e9f6e66c54_1600x970.jpeg)
```

## 常用命令

```bash
# 指定输入目录和输出目录
python eml2md.py inbox -o archive

# 递归处理子目录
python eml2md.py inbox --recursive -o archive

# 只预览，不下载图片（保留远程 URL）
python eml2md.py --no-download -o preview

# 强制重新下载图片
python eml2md.py --refresh-images

# 图片放到其他目录
python eml2md.py -o archive --assets-dir media
```

## 参数

| 参数 | 说明 |
| --- | --- |
| `input` | `.eml` 文件或目录，默认当前目录 |
| `-o, --output` | Markdown 输出目录，默认 `output` |
| `--assets-dir` | 图片目录，默认 `OUTPUT/assets` |
| `--no-download` | 不下载图片，保留远程 URL |
| `--refresh-images` | 已存在的图片也重新下载 |
| `--recursive` | 输入为目录时递归查找 `.eml` |
| `--quiet` | 只输出最终统计 |

## 输出内容

每个 Markdown 文件包含：

- YAML frontmatter：`title`、`date`、`author`、`publication`、`from`、`message_id`、`url`、`source`
- 一级标题
- 正文：段落、引用、强调、列表、图片

文件名格式为 `YYYY-MM-DD-HHMM-<标题>.md`；同名时自动追加 `-2`、`-3`。

## 说明

- 优先解析 HTML 正文以保留格式；无可用 HTML 时回退到 `text/plain`。
- 图片默认缓存：已存在且非空则跳过下载；`--refresh-images` 可强制更新。
- 任意邮件解析失败或图片下载失败时，命令退出码为 `1`。
- 当前目录已生成示例输出：`output/`（16 个 Markdown、8 张图片）。