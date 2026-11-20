#!/usr/bin/env python3
"""Convert exported .eml messages into Markdown with offline images.

The converter prefers the HTML body so that emphasis, lists, block quotes and
images survive.  It falls back to the plain-text body when no usable HTML is
available.  Downloaded images are stored under an ``assets/`` directory and
referenced with paths relative to each Markdown file.

Dependencies:
    beautifulsoup4

Usage:
    python eml2md.py [INPUT] [-o OUTPUT] [--assets-dir DIR]
"""

from __future__ import annotations

import argparse
import email
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

USER_AGENT = "eml2md/1.0"
IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}
BLOCK_TAGS = {
    "article",
    "body",
    "center",
    "div",
    "figcaption",
    "figure",
    "footer",
    "header",
    "html",
    "main",
    "p",
    "section",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
}


@dataclass
class EmailDoc:
    path: Path
    subject: str
    author: str
    publication: str
    address: str
    date: datetime
    message_id: str
    url: str
    html: str | None
    plain: str | None
    md_name: str = ""


def sanitize_filename(name: str) -> str:
    """Make a string safe for Windows and POSIX file names."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.strip(" .-")
    return name or "untitled"


def yaml_string(value: str) -> str:
    """Return a double-quoted YAML scalar."""
    return json.dumps(value, ensure_ascii=False)


def escape_heading(value: str) -> str:
    return re.sub(r"([\\`*_\[\]])", r"\\\1", value)


def escape_link_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def clean_markdown(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def plain_to_markdown(value: str) -> str:
    lines = []
    for line in value.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith("View this post on the web at "):
            continue
        if stripped.startswith("Unsubscribe "):
            continue
        lines.append(line.rstrip())
    return clean_markdown("\n".join(lines))


def largest_text_part(message: email.message.EmailMessage, content_type: str) -> str | None:
    best = ""
    for part in message.walk():
        if part.get_content_type() != content_type:
            continue
        try:
            value = part.get_content()
        except Exception:
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            value = payload.decode(charset, "replace")
        if isinstance(value, str) and len(value) > len(best):
            best = value
    return best or None


def parse_date(value: str, path: Path) -> datetime:
    if value:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None:
            return parsed
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone()


def split_author(display: str, address: str) -> tuple[str, str]:
    display = re.sub(r"\s+", " ", display or "").strip()
    match = re.match(r"^(.*?)\s+from\s+(.*)$", display, re.IGNORECASE)
    if match and match.group(1).strip():
        return match.group(1).strip(), match.group(2).strip()
    if display:
        return display, ""
    if address:
        return address.split("@", 1)[0], ""
    return "", ""


def find_url(plain: str | None) -> str:
    if not plain:
        return ""
    match = re.search(r"View this post on the web at\s+(\S+)", plain)
    return match.group(1).rstrip(">") if match else ""


def load_doc(path: Path) -> EmailDoc:
    with path.open("rb") as handle:
        message = email.message_from_binary_file(handle, policy=policy.default)

    subject = re.sub(r"\s+", " ", str(message.get("Subject") or "")).strip()
    display, address = parseaddr(str(message.get("From") or ""))
    author, publication = split_author(display, address)
    plain = largest_text_part(message, "text/plain")
    html = largest_text_part(message, "text/html")

    return EmailDoc(
        path=path,
        subject=subject,
        author=author,
        publication=publication,
        address=address,
        date=parse_date(str(message.get("Date") or ""), path),
        message_id=str(message.get("Message-ID") or "").strip(),
        url=find_url(plain),
        html=html,
        plain=plain,
    )


def select_body(html: str) -> Tag:
    soup = BeautifulSoup(html, "lxml")
    node = soup.select_one("div.body")
    if node is not None and (
        node.find("p") is not None
        or node.find("img") is not None
        or len(node.get_text(strip=True)) > 80
    ):
        return node
    for selector in ("article", "main"):
        candidate = soup.select_one(selector)
        if candidate is not None and candidate.find("p") is not None:
            return candidate
    return soup.body or soup


class MarkdownRenderer:
    def __init__(self, image_handler):
        self.image_handler = image_handler

    def render(self, node: Tag) -> str:
        return clean_markdown(self.render_children(node))

    def render_children(self, node: Tag) -> str:
        return "".join(self.render_node(child) for child in node.children)

    def render_node(self, node) -> str:
        if isinstance(node, NavigableString):
            return str(node)
        if not isinstance(node, Tag):
            return ""

        name = node.name.lower()
        if name == "br":
            return "\n"
        if name == "img":
            return self.image_handler(node)
        if name in {"em", "i", "cite", "var"}:
            return self.inline(node, "*")
        if name in {"strong", "b"}:
            return self.inline(node, "**")
        if name in {"del", "s", "strike"}:
            return self.inline(node, "~~")
        if name == "code":
            text = self.render_children(node)
            leading, core, trailing = self.split_edges(text)
            return f"{leading}`{core}`{trailing}" if core else text
        if name == "pre":
            code = self.render_children(node).strip("\n")
            return f"\n\n```\n{code}\n```\n\n"
        if name == "a":
            return self.link(node)
        if name in {"ul", "ol"}:
            return self.list(node, name == "ol")
        if name == "blockquote":
            return self.quote(node)
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(name[1])
            text = self.render_children(node).strip()
            return f"\n\n{'#' * level} {text}\n\n" if text else ""
        if name == "hr":
            return "\n\n---\n\n"
        if name in BLOCK_TAGS:
            return self.block(node)
        return self.render_children(node)

    def inline(self, node: Tag, marker: str) -> str:
        text = self.render_children(node)
        leading, core, trailing = self.split_edges(text)
        return f"{leading}{marker}{core}{marker}{trailing}" if core else text

    def link(self, node: Tag) -> str:
        href = (node.get("href") or "").strip()
        image = node.find("img")
        if image is not None and not node.get_text(strip=True):
            return self.image_handler(image)
        text = self.render_children(node)
        leading, core, trailing = self.split_edges(text)
        if not core:
            return text
        if not href or href.startswith(("javascript:", "#")):
            return text
        return f"{leading}[{escape_link_text(core)}]({href}){trailing}"

    @staticmethod
    def split_edges(text: str) -> tuple[str, str, str]:
        if not text:
            return "", "", ""
        leading = text[: len(text) - len(text.lstrip())]
        trailing = text[len(text.rstrip()) :]
        return leading, text.strip(), trailing

    def list(self, node: Tag, ordered: bool) -> str:
        items = []
        index = 1
        if ordered:
            try:
                index = int(node.get("start", "1"))
            except (TypeError, ValueError):
                index = 1
        for item in node.find_all("li", recursive=False):
            marker = f"{index}." if ordered else "-"
            index += 1
            text = re.sub(r"\s*\n\s*", " ", self.render_children(item)).strip()
            if text:
                items.append(f"{marker} {text}")
        return "\n\n" + "\n".join(items) + "\n\n" if items else ""

    def quote(self, node: Tag) -> str:
        inner = self.render_children(node).replace("\xa0", " ")
        lines = []
        for line in inner.splitlines():
            line = line.rstrip()
            if line.strip():
                lines.append("> " + line.strip())
            elif lines and lines[-1] != ">":
                lines.append(">")
        while lines and lines[-1] == ">":
            lines.pop()
        return "\n\n" + "\n".join(lines) + "\n\n" if lines else ""

    def block(self, node: Tag) -> str:
        inner = self.render_children(node).strip()
        return f"\n\n{inner}\n\n" if inner else ""


class AssetStore:
    def __init__(self, assets_dir: Path, download: bool = True, refresh: bool = False):
        self.assets_dir = assets_dir
        self.download = download
        self.refresh = refresh
        self.used: dict[str, str] = {}
        self.failures: list[tuple[str, str]] = []
        self.downloaded = 0
        self.cached = 0

    def image_markdown(self, node: Tag, markdown_dir: Path) -> str:
        alt = self.alt_text(node)
        src = self.image_url(node)
        if not src:
            return ""
        alt_md = alt.replace("\\", "\\\\").replace("]", "\\]")
        if not self.download:
            return f"![{alt_md}]({src})"
        local = self.fetch(src, node)
        if local is None:
            return f"![{alt_md}]({src})"
        relative = Path(os.path.relpath(str(local), str(markdown_dir))).as_posix()
        return f"![{alt_md}]({relative})"

    @staticmethod
    def image_url(node: Tag) -> str:
        src = (node.get("src") or "").strip()
        attrs = node.get("data-attrs")
        if attrs:
            try:
                data = json.loads(attrs)
            except (TypeError, ValueError):
                data = {}
            src = (data.get("src") or src).strip()
        if src.startswith("//"):
            src = "https:" + src
        return src

    @staticmethod
    def alt_text(node: Tag) -> str:
        alt = (node.get("alt") or "").strip()
        attrs = node.get("data-attrs")
        if attrs:
            try:
                data = json.loads(attrs)
            except (TypeError, ValueError):
                data = {}
            alt = (data.get("alt") or alt).strip()
        return alt

    def fetch(self, url: str, node: Tag) -> Path | None:
        name = self.asset_name(url, node)
        destination = self.assets_dir / name
        if destination.exists() and destination.stat().st_size > 0 and not self.refresh:
            self.cached += 1
            return destination

        self.assets_dir.mkdir(parents=True, exist_ok=True)
        error: Exception | None = None
        for attempt in range(3):
            try:
                data, _ = self.http_get(url)
                destination.write_bytes(data)
                self.downloaded += 1
                return destination
            except Exception as exc:  # network, HTTP, disk
                error = exc
                if attempt < 2:
                    time.sleep(1 + attempt)

        self.failures.append((url, str(error)))
        print(f"[warn] image download failed: {url} ({error})", file=sys.stderr)
        return None

    @staticmethod
    def http_get(url: str) -> tuple[bytes, str]:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            content_type = response.headers.get_content_type()
            data = response.read()
        if content_type.startswith("text/") or content_type == "application/json":
            raise ValueError(f"expected image, got {content_type}")
        return data, content_type

    def asset_name(self, url: str, node: Tag) -> str:
        path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
        stem, extension = os.path.splitext(os.path.basename(path))
        stem = sanitize_filename(stem)
        extension = extension.lower()
        if extension not in IMAGE_EXTENSIONS:
            extension = self.extension_from_node(node) or ".jpg"
        if not stem:
            stem = "image"
        name = f"{stem}{extension}"
        if name in self.used and self.used[name] != url:
            digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
            name = f"{stem}-{digest}{extension}"
        self.used[name] = url
        return name

    @staticmethod
    def extension_from_node(node: Tag) -> str:
        attrs = node.get("data-attrs")
        if not attrs:
            return ""
        try:
            data = json.loads(attrs)
        except (TypeError, ValueError):
            return ""
        source = data.get("src") or ""
        extension = os.path.splitext(urllib.parse.urlparse(source).path)[1].lower()
        return extension if extension in IMAGE_EXTENSIONS else ""


def assign_names(documents: list[EmailDoc]) -> list[EmailDoc]:
    used: set[str] = set()
    for document in sorted(
        documents, key=lambda item: (item.date, item.subject, str(item.path))
    ):
        stamp = document.date.strftime("%Y-%m-%d-%H%M")
        slug = sanitize_filename(document.subject or document.path.stem)
        base = f"{stamp}-{slug}"
        name = f"{base}.md"
        counter = 2
        while name.lower() in used:
            name = f"{base}-{counter}.md"
            counter += 1
        used.add(name.lower())
        document.md_name = name
    return sorted(documents, key=lambda item: item.md_name)


def frontmatter(document: EmailDoc) -> str:
    lines = ["---"]
    lines.append(f"title: {yaml_string(document.subject or document.path.stem)}")
    lines.append(f"date: {document.date.isoformat()}")
    lines.append(f"author: {yaml_string(document.author)}")
    if document.publication:
        lines.append(f"publication: {yaml_string(document.publication)}")
    lines.append(f"from: {yaml_string(document.address)}")
    if document.message_id:
        lines.append(f"message_id: {yaml_string(document.message_id)}")
    if document.url:
        lines.append(f"url: {yaml_string(document.url)}")
    lines.append(f"source: {yaml_string(document.path.name)}")
    lines.append("---")
    return "\n".join(lines)


def render_body(document: EmailDoc, image_handler) -> str:
    if document.html:
        node = select_body(document.html)
        body = MarkdownRenderer(image_handler).render(node)
        if body:
            return body
    if document.plain:
        return plain_to_markdown(document.plain)
    return ""


def render_document(document: EmailDoc, output_dir: Path, assets: AssetStore) -> Path:
    markdown_path = output_dir / document.md_name

    def image_handler(node: Tag) -> str:
        return assets.image_markdown(node, markdown_path.parent)

    body = render_body(document, image_handler)
    if not body:
        raise ValueError(f"no readable content in {document.path}")

    title = escape_heading(document.subject or document.path.stem)
    text = frontmatter(document) + "\n\n# " + title + "\n\n" + body + "\n"
    markdown_path.write_text(text, encoding="utf-8")
    return markdown_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert .eml messages to Markdown with offline images."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=".",
        help="EML file or directory (default: current directory)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="output",
        help="Markdown output directory (default: output)",
    )
    parser.add_argument(
        "--assets-dir",
        default=None,
        help="Image directory (default: OUTPUT/assets)",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Keep remote image URLs instead of downloading them",
    )
    parser.add_argument(
        "--refresh-images",
        action="store_true",
        help="Re-download images even when the local file exists",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recurse into subdirectories when INPUT is a directory",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print the final summary",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)

    if not input_path.exists():
        print(f"error: input not found: {input_path}", file=sys.stderr)
        return 1

    if input_path.is_file():
        paths = [input_path] if input_path.suffix.lower() == ".eml" else []
    else:
        entries = input_path.rglob("*") if args.recursive else input_path.iterdir()
        paths = sorted(
            path for path in entries if path.is_file() and path.suffix.lower() == ".eml"
        )

    if not paths:
        print(f"error: no .eml files found in {input_path}", file=sys.stderr)
        return 1

    output_dir = Path(args.output)
    assets_dir = Path(args.assets_dir) if args.assets_dir else output_dir / "assets"
    output_dir.mkdir(parents=True, exist_ok=True)

    documents: list[EmailDoc] = []
    for path in paths:
        try:
            documents.append(load_doc(path))
        except Exception as exc:
            print(f"[warn] failed to parse {path}: {exc}", file=sys.stderr)

    if not documents:
        print("error: no messages could be parsed", file=sys.stderr)
        return 1

    documents = assign_names(documents)
    assets = AssetStore(
        assets_dir,
        download=not args.no_download,
        refresh=args.refresh_images,
    )

    written = 0
    for document in documents:
        try:
            markdown_path = render_document(document, output_dir, assets)
            written += 1
            if not args.quiet:
                print(f"[ok] {document.path.name} -> {markdown_path.name}")
        except Exception as exc:
            print(f"[warn] failed to convert {document.path}: {exc}", file=sys.stderr)

    print(f"Converted {written}/{len(paths)} messages to {output_dir}")
    print(
        "Images: "
        f"{assets.downloaded} downloaded, "
        f"{assets.cached} cached, "
        f"{len(assets.failures)} failed"
    )
    return 0 if written == len(paths) and not assets.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())