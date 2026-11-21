# encoding_converter.py

通用文件编码转换工具，主要用于修复日文系统创建的文件在中文系统下出现的乱码问题。

## 功能

- 自动检测文件编码（Shift-JIS / EUC-JP / UTF-8 等）
- 转换文件内容编码为 UTF-8
- 转换乱码文件名为正确日文
- 支持批量处理整个目录
- 预览模式，避免误操作

## 用法

### 转换文件内容编码

```bash
# 自动检测并转换目录下所有文本文件
python encoding_converter.py ./docs

# 指定源编码
python encoding_converter.py ./docs --from cp932

# 转换单个文件
python encoding_converter.py file.txt --from euc_jp
```

### 转换文件名编码

```bash
# 修复乱码文件名
python encoding_converter.py ./docs --rename
```

### 同时转换文件名和内容

```bash
python encoding_converter.py ./docs --rename --content
```

### 预览模式

```bash
# 查看哪些文件需要转换，不实际修改
python encoding_converter.py ./docs --dry-run
```

### 查看支持的编码

```bash
python encoding_converter.py --list-encodings
```

## 支持的编码

| 编码 | 说明 |
|------|------|
| cp932 | Shift-JIS (Windows) |
| shift_jis | Shift-JIS (标准) |
| euc_jp | EUC-JP |
| iso2022_jp | ISO-2022-JP |
| utf_8 | UTF-8 |
| utf_8_sig | UTF-8 with BOM |
| gbk | 简体中文 |
| gb2312 | 简体中文 |
| big5 | 繁体中文 |

## 常见场景

### 场景1：解压日文ZIP文件后文件名乱码

```bash
# 解压后发现文件夹名是乱码，用 --rename 修复
python encoding_converter.py ./解压后的文件夹 --rename
```

### 场景2：日文文本文件打开是乱码

```bash
# 指定 Shift-JIS 编码转换
python encoding_converter.py ./乱码文件.txt --from cp932
```

### 场景3：批量转换整个文件夹

```bash
# 先预览，确认无误后再执行
python encoding_converter.py ./docs --dry-run
python encoding_converter.py ./docs
```

## 环境要求

- Python 3.6+
- 无需安装第三方依赖
