#!/usr/bin/env python3
"""
encoding_converter.py - 通用文件编码转换工具

功能：
  1. 转换文件内容编码（Shift-JIS/EUC-JP 等 -> UTF-8）
  2. 转换文件名编码（乱码日文 -> 正确日文）
  3. 自动检测编码
  4. 支持批量处理目录

用法：
  python encoding_converter.py <路径>                 # 自动检测并转换
  python encoding_converter.py <路径> --from cp932    # 指定源编码
  python encoding_converter.py <路径> --rename        # 仅转换文件名
  python encoding_converter.py <路径> --content       # 仅转换文件内容
  python encoding_converter.py <路径> --dry-run       # 预览模式，不实际修改
"""

import os
import sys
import argparse
import codecs
from pathlib import Path

# 常见日文编码
JAPANESE_ENCODINGS = [
    'cp932',       # Shift-JIS (Windows)
    'shift_jis',   # Shift-JIS (标准)
    'euc_jp',      # EUC-JP
    'iso2022_jp',  # ISO-2022-JP
    'utf_8',       # UTF-8
    'utf_8_sig',   # UTF-8 with BOM
]

# 文件扩展名 -> 可能的编码（优先级从高到低）
EXTENSION_HINTS = {
    '.txt': ['cp932', 'euc_jp', 'utf_8'],
    '.md': ['utf_8', 'cp932'],
    '.csv': ['cp932', 'utf_8'],
    '.srt': ['cp932', 'utf_8'],
    '.ass': ['cp932', 'utf_8'],
    '.log': ['cp932', 'euc_jp', 'utf_8'],
    '.ini': ['cp932', 'utf_8'],
    '.json': ['utf_8'],
    '.xml': ['utf_8', 'iso2022_jp'],
    '.html': ['utf_8', 'iso2022_jp'],
    '.js': ['utf_8'],
    '.py': ['utf_8'],
}


def detect_encoding(file_path, sample_size=8192):
    """检测文件编码"""
    with open(file_path, 'rb') as f:
        raw = f.read(sample_size)

    if not raw:
        return 'utf_8'

    # 检查 BOM
    if raw.startswith(codecs.BOM_UTF8):
        return 'utf_8_sig'
    if raw.startswith(codecs.BOM_UTF16_LE):
        return 'utf_16_le'
    if raw.startswith(codecs.BOM_UTF16_BE):
        return 'utf_16_be'

    # 获取扩展名提示
    ext = Path(file_path).suffix.lower()
    hints = EXTENSION_HINTS.get(ext, JAPANESE_ENCODINGS)

    # 尝试用候选编码解码
    for enc in hints:
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue

    # 无 BOM 的 UTF-8 文件也是合法的
    try:
        raw.decode('utf_8')
        return 'utf_8'
    except UnicodeDecodeError:
        pass

    # 尝试所有日文编码
    for enc in JAPANESE_ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue

    return None


def convert_file_content(file_path, source_encoding=None, dry_run=False):
    """转换文件内容编码为UTF-8"""
    if not os.path.isfile(file_path):
        return False, "不是文件"

    # 检测编码
    if source_encoding:
        detected = source_encoding
    else:
        detected = detect_encoding(file_path)

    if not detected:
        return False, "无法检测编码"

    # 如果已经是UTF-8，跳过
    if detected in ('utf_8', 'utf_8_sig'):
        return False, "已经是UTF-8"

    if dry_run:
        return True, f"需要转换: {detected} -> utf_8"

    # 读取并转换
    try:
        with open(file_path, 'r', encoding=detected, errors='replace') as f:
            content = f.read()

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return True, f"{detected} -> utf_8"
    except Exception as e:
        return False, f"转换失败: {e}"


def fix_filename_encoding(name):
    """尝试修复文件名编码（日文乱码 -> 正确日文）"""
    # 尝试用各种编码解码文件名
    for enc in ['cp932', 'euc_jp', 'cp936', 'gbk']:
        try:
            # 先编码回字节，再用目标编码解码
            decoded = name.encode(enc).decode('utf-8')
            if decoded != name:
                return decoded
        except (UnicodeDecodeError, UnicodeEncodeError):
            continue
    return None


def convert_filenames(directory, dry_run=False):
    """转换目录下所有文件名编码"""
    converted = 0
    errors = []

    # 从深层到浅层处理，避免路径问题
    for root, dirs, files in os.walk(directory, topdown=False):
        for name in files + dirs:
            old_path = os.path.join(root, name)
            new_name = fix_filename_encoding(name)

            if new_name is None or new_name == name:
                continue

            new_path = os.path.join(root, new_name)

            if os.path.exists(new_path):
                errors.append(f"目标已存在: {new_name}")
                continue

            if dry_run:
                print(f"  [预览] {name} -> {new_name}")
                converted += 1
            else:
                try:
                    os.rename(old_path, new_path)
                    print(f"  {name} -> {new_name}")
                    converted += 1
                except OSError as e:
                    errors.append(f"重命名失败: {name} - {e}")

    return converted, errors


def scan_directory(directory, source_encoding=None, dry_run=False):
    """扫描目录并转换"""
    results = {'converted': 0, 'skipped': 0, 'errors': []}
    text_extensions = {
        '.txt', '.md', '.csv', '.srt', '.ass', '.log', '.ini',
        '.json', '.xml', '.html', '.js', '.py', '.java', '.c',
        '.cpp', '.h', '.hpp', '.cs', '.rb', '.php', '.sh', '.bat',
        '.yaml', '.yml', '.toml', '.cfg', '.conf', '.rtf'
    }

    for root, dirs, files in os.walk(directory):
        for name in files:
            file_path = os.path.join(root, name)
            ext = Path(name).suffix.lower()

            # 只处理文本文件
            if ext not in text_extensions:
                continue

            success, msg = convert_file_content(file_path, source_encoding, dry_run)
            if success:
                results['converted'] += 1
                rel_path = os.path.relpath(file_path, directory)
                print(f"  {rel_path}: {msg}")
            elif "已经是UTF-8" not in msg:
                results['skipped'] += 1

    return results


def main():
    parser = argparse.ArgumentParser(
        description="通用文件编码转换工具（日文 -> UTF-8）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s ./docs                        # 自动检测并转换目录下所有文本文件
  %(prog)s ./docs --from cp932           # 指定源编码为Shift-JIS
  %(prog)s ./docs --rename               # 仅转换文件名编码
  %(prog)s ./docs --rename --content     # 同时转换文件名和内容
  %(prog)s ./docs --dry-run              # 预览模式
  %(prog)s file.txt --from euc_jp        # 转换单个文件

支持的编码:
  cp932, shift_jis, euc_jp, iso2022_jp, utf_8, gbk, gb2312 等
        """
    )

    parser.add_argument("path", nargs="?", help="文件或目录路径")
    parser.add_argument("--from", dest="source_encoding",
                        help="源编码（如 cp932, euc_jp）")
    parser.add_argument("--rename", action="store_true",
                        help="转换文件名编码")
    parser.add_argument("--content", action="store_true",
                        help="转换文件内容编码")
    parser.add_argument("--dry-run", action="store_true",
                        help="预览模式，不实际修改")
    parser.add_argument("--list-encodings", action="store_true",
                        help="列出支持的编码")

    args = parser.parse_args()

    if args.list_encodings:
        print("支持的编码:")
        for enc in sorted(set(JAPANESE_ENCODINGS + ['gbk', 'gb2312', 'big5'])):
            print(f"  {enc}")
        return

    path = args.path
    if not path:
        parser.error("请指定文件或目录路径")
    if not os.path.exists(path):
        print(f"错误：路径不存在 - {path}")
        sys.exit(1)

    # 默认同时处理文件名和内容
    do_rename = args.rename or (not args.content)
    do_content = args.content or (not args.rename)

    if os.path.isfile(path):
        # 处理单个文件
        if do_content:
            print(f"转换文件内容: {path}")
            success, msg = convert_file_content(path, args.source_encoding, args.dry_run)
            print(f"  结果: {msg}")
        if do_rename:
            dir_name = os.path.dirname(path) or "."
            base_name = os.path.basename(path)
            new_name = fix_filename_encoding(base_name)
            if new_name and new_name != base_name:
                new_path = os.path.join(dir_name, new_name)
                if not args.dry_run:
                    os.rename(path, new_path)
                    print(f"  重命名: {base_name} -> {new_name}")
                else:
                    print(f"  [预览] 重命名: {base_name} -> {new_name}")

    elif os.path.isdir(path):
        # 处理目录
        if do_content:
            print(f"转换文件内容: {path}")
            print("-" * 50)
            results = scan_directory(path, args.source_encoding, args.dry_run)
            print("-" * 50)
            print(f"转换: {results['converted']} 个文件")

        if do_rename:
            print(f"\n转换文件名: {path}")
            print("-" * 50)
            count, errors = convert_filenames(path, args.dry_run)
            print("-" * 50)
            print(f"转换: {count} 个文件名")
            for err in errors:
                print(f"  警告: {err}")

    print("\n完成！")


if __name__ == "__main__":
    main()
