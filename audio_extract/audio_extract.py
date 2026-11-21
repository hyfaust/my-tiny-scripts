#!/usr/bin/env python3
"""audio-extract - inspect video files and pull their audio tracks out in place.

Extraction is a *stream copy*: the original audio bitstream is remuxed into an
audio-only container without re-encoding, so it is lossless and near-instant.

Two sub-commands:

    info     show detailed information about one or more video files
    extract  write the audio track(s) next to each video file

Requires Python 3.8+ and FFmpeg / ffprobe 4.0+ on PATH.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

__version__ = "1.0.0"

# argv[0] without the directory; used in usage lines and error messages.
PROG = Path(sys.argv[0]).name

# How the user actually invoked us, so the hints we print are copy-pasteable.
INVOCATION = "python %s" % PROG if Path(PROG).suffix.lower() in (".py", ".pyw") else PROG

# Extensions considered "video" when an input path is a directory.
VIDEO_EXTS = {
    ".3gp", ".asf", ".avi", ".divx", ".f4v", ".flv", ".m2ts", ".m4v",
    ".mkv", ".mov", ".mp4", ".mpg", ".mpeg", ".mts", ".ogv", ".rmvb",
    ".ts", ".vob", ".webm", ".wmv",
}

# ffprobe codec_name -> output extension.  The container is chosen from the
# codec so that "-c:a copy" always lands in a muxer that accepts that codec.
CODEC_EXT = {
    "aac": ".m4a",
    "alac": ".m4a",
    "mp3": ".mp3",
    "mp2": ".mp2",
    "ac3": ".ac3",
    "eac3": ".eac3",
    "dts": ".dts",
    "flac": ".flac",
    "opus": ".opus",
    "vorbis": ".ogg",
    "wmav1": ".wma",
    "wmav2": ".wma",
}

# Matching by codec-name prefix, checked after the exact table above.
CODEC_EXT_PREFIX = (
    ("pcm_", ".wav"),
    ("adpcm_", ".wav"),
)

# Matroska audio accepts virtually every codec, so it is the safe fallback.
DEFAULT_AUDIO_EXT = ".mka"

# ffmpeg's -progress prints "out_time=HH:MM:SS.ffffff".
OUT_TIME_RE = re.compile(r"^out_time=(\d+):(\d+):(\d+(?:\.\d+)?)$")


def examples_for(command: str = None) -> str:
    """Build the 'examples:' epilog for the top level or a single sub-command."""
    prefix = INVOCATION if command is None else "%s %s" % (INVOCATION, command)
    if command == "info":
        lines = [
            "  %s movie.mp4" % prefix,
            "  %s D:\\videos -r" % prefix,
            "  %s movie.mkv --json" % prefix,
        ]
    elif command == "extract":
        lines = [
            "  %s movie.mp4" % prefix,
            "  %s D:\\videos -r -o D:\\audio" % prefix,
            "  %s concert.mkv --track all" % prefix,
            "  %s dual-audio.mp4 --track 1 -y" % prefix,
        ]
    else:
        lines = [
            "  %s info movie.mp4" % prefix,
            "  %s info D:\\videos -r" % prefix,
            "  %s extract movie.mp4" % prefix,
            "  %s extract D:\\videos -r -o D:\\audio" % prefix,
            "  %s extract concert.mkv --track all" % prefix,
        ]
    return "examples:\n" + "\n".join(lines) + "\n"


class ToolError(RuntimeError):
    """A problem the user has to fix (missing tool, bad input, no audio track)."""


# ---------------------------------------------------------------------------
# Locating the FFmpeg tools
# ---------------------------------------------------------------------------

def find_tool(name: str, env_var: str) -> str:
    """Resolve ffmpeg/ffprobe, honouring an environment variable override."""
    override = os.environ.get(env_var)
    if override:
        candidate = override if Path(override).is_file() else shutil.which(override)
        if candidate:
            return str(candidate)
        raise ToolError(
            "%s is set to %r, which is not an executable file" % (env_var, override)
        )
    found = shutil.which(name)
    if found:
        return found
    raise ToolError(
        "could not find %r on PATH; install FFmpeg or point the %s "
        "environment variable at the executable" % (name, env_var)
    )


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------

def human_size(num_bytes) -> str:
    """Bytes -> '1.24 GiB' style string."""
    if num_bytes in (None, "", "N/A"):
        return "unknown"
    try:
        size = float(num_bytes)
    except (TypeError, ValueError):
        return "unknown"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return "%d %s" % (round(size), unit) if unit == "B" else "%.2f %s" % (size, unit)
        size /= 1024
    return "unknown"


def human_bitrate(bits_per_second) -> str:
    """Bits per second -> '192 kb/s' or '4.83 Mb/s'."""
    if bits_per_second in (None, "", "N/A"):
        return "unknown"
    try:
        bps = float(bits_per_second)
    except (TypeError, ValueError):
        return "unknown"
    if bps <= 0:
        return "unknown"
    if bps >= 1_000_000:
        return "%.2f Mb/s" % (bps / 1_000_000)
    return "%.0f kb/s" % (bps / 1000)


def format_duration(seconds) -> str:
    """Seconds -> 'HH:MM:SS.mmm'."""
    if seconds in (None, "", "N/A"):
        return "unknown"
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "unknown"
    if value < 0:
        return "unknown"
    total_ms = int(round(value * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return "%02d:%02d:%02d.%03d" % (hours, minutes, secs, millis)


def format_clock(seconds) -> str:
    """Seconds -> 'MM:SS' (or 'H:MM:SS'); used for the progress ETA."""
    total = int(round(max(0.0, float(seconds))))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, secs)
    return "%02d:%02d" % (minutes, secs)


def parse_fps(ratio):
    """ffprobe's '30000/1001' -> '29.97'."""
    if not ratio:
        return None
    numerator, _, denominator = str(ratio).partition("/")
    try:
        value = float(numerator) / float(denominator) if denominator else float(numerator)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return "%.2f" % value if value > 0 else None


def quote_arg(value) -> str:
    """Quote a command argument for display when it contains spaces."""
    text = str(value)
    return '"%s"' % text if " " in text else text


def codec_extension(codec_name) -> str:
    """Pick the output extension that matches the source audio codec."""
    if not codec_name:
        return DEFAULT_AUDIO_EXT
    name = str(codec_name).lower()
    if name in CODEC_EXT:
        return CODEC_EXT[name]
    for prefix, extension in CODEC_EXT_PREFIX:
        if name.startswith(prefix):
            return extension
    return DEFAULT_AUDIO_EXT


def stream_index_label(stream) -> str:
    return str(stream.get("index", "?"))


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------

def probe(ffprobe: str, path: Path) -> dict:
    """Run ffprobe and return its parsed JSON report for *path*."""
    command = [
        ffprobe, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", "-i", str(path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or not result.stdout.strip():
        detail = (result.stderr or "").strip().splitlines()
        detail = detail[-1] if detail else "ffprobe produced no output"
        raise ToolError("cannot read %s: %s" % (path, detail))
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ToolError("ffprobe returned unreadable JSON for %s: %s" % (path, exc))


def audio_streams(report: dict) -> list:
    """The audio streams of a report, in --track index order."""
    return [s for s in report.get("streams", []) if s.get("codec_type") == "audio"]


def format_duration_of(report: dict) -> float:
    """Container duration in seconds, falling back to the longest stream."""
    candidates = [report.get("format", {}).get("duration")]
    candidates += [s.get("duration") for s in report.get("streams", [])]
    for value in candidates:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            continue
        if seconds > 0:
            return seconds
    return 0.0


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------

def describe_video(stream: dict) -> str:
    parts = ["  stream #%-3s video" % stream_index_label(stream)]
    codec = stream.get("codec_name") or "?"
    profile = stream.get("profile")
    parts.append("%s (%s)" % (codec, profile) if profile else codec)
    width, height = stream.get("width"), stream.get("height")
    if width and height:
        parts.append("%dx%d" % (width, height))
    fps = parse_fps(stream.get("avg_frame_rate")) or parse_fps(stream.get("r_frame_rate"))
    if fps:
        parts.append("%s fps" % fps)
    if stream.get("pix_fmt"):
        parts.append(stream["pix_fmt"])
    parts.append(human_bitrate(stream.get("bit_rate")))
    return "  ".join(parts)


def stream_tags(stream: dict) -> dict:
    return stream.get("tags") or {}


def describe_audio(stream: dict, track_index: int) -> str:
    parts = ["  stream #%-3s audio" % stream_index_label(stream)]
    codec = stream.get("codec_name") or "?"
    profile = stream.get("profile")
    parts.append("%s (%s)" % (codec, profile) if profile else codec)

    channels, layout = stream.get("channels"), stream.get("channel_layout")
    if channels and layout:
        parts.append("%sch (%s)" % (channels, layout))
    elif channels:
        parts.append("%sch" % channels)
    if stream.get("sample_rate"):
        parts.append("%s Hz" % stream["sample_rate"])
    parts.append(human_bitrate(stream.get("bit_rate")))

    extras = []
    disposition = stream.get("disposition") or {}
    flags = [name for name in ("default", "forced") if disposition.get(name)]
    if flags:
        extras.append("[%s]" % ", ".join(flags))
    tags = stream_tags(stream)
    if tags.get("language"):
        extras.append("lang=%s" % tags["language"])
    if tags.get("title"):
        extras.append("title=%s" % tags["title"])
    extras.append("audio track %d" % track_index)
    return "  ".join(parts) + "  " + "  ".join(extras)


def describe_subtitle(stream: dict) -> str:
    parts = ["  stream #%-3s subtitle" % stream_index_label(stream)]
    parts.append(stream.get("codec_name") or "?")
    tags = stream_tags(stream)
    if tags.get("language"):
        parts.append("lang=%s" % tags["language"])
    if tags.get("title"):
        parts.append("title=%s" % tags["title"])
    return "  ".join(parts)


def describe(path: Path, report: dict) -> None:
    """Print a human-readable summary of one probed file."""
    container = report.get("format", {})
    streams = report.get("streams", [])
    audio = audio_streams(report)
    video = [s for s in streams if s.get("codec_type") == "video"]
    subtitles = [s for s in streams if s.get("codec_type") == "subtitle"]

    try:
        size = path.stat().st_size
    except OSError:
        size = container.get("size")

    print("File       : %s" % path)
    print("Size       : %s" % human_size(size))
    print("Container  : %s" % (container.get("format_long_name") or container.get("format_name") or "unknown"))
    print("Duration   : %s" % format_duration(container.get("duration")))
    print("Bitrate    : %s" % human_bitrate(container.get("bit_rate")))
    print("Streams    : %d  (video %d, audio %d, subtitle %d)"
          % (len(streams), len(video), len(audio), len(subtitles)))
    print()

    audio_seen = 0
    for stream in streams:
        kind = stream.get("codec_type")
        if kind == "video":
            print(describe_video(stream))
        elif kind == "audio":
            print(describe_audio(stream, audio_seen))
            audio_seen += 1
        elif kind == "subtitle":
            print(describe_subtitle(stream))
        else:
            print("  stream #%-3s %s  %s"
                  % (stream_index_label(stream), kind or "?", stream.get("codec_name") or "?"))

    print()
    if audio:
        print("Audio tracks available: %d" % len(audio))
        print("Extract with: %s extract %s" % (INVOCATION, quote_arg(path)))
    else:
        print("No audio track found in this file.")


def cmd_info(args) -> int:
    ffprobe = find_tool("ffprobe", "FFPROBE")
    files = collect_inputs(args.inputs, args.recursive)
    if not files:
        raise ToolError("no input files to process")

    failed = 0
    for position, path in enumerate(files):
        if position:
            print()
        try:
            report = probe(ffprobe, path)
        except ToolError as exc:
            print("%s: %s" % (PROG, exc), file=sys.stderr)
            failed += 1
            continue
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            describe(path, report)
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------

def collect_inputs(paths, recursive: bool) -> list:
    """Expand CLI paths into a stable, de-duplicated list of media files."""
    files = []
    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_dir():
            pattern = "**/*" if recursive else "*"
            found = sorted(
                p for p in path.glob(pattern)
                if p.is_file() and p.suffix.lower() in VIDEO_EXTS
            )
            if not found:
                print("warning: no video files found in %s" % path, file=sys.stderr)
            files.extend(found)
        elif path.is_file():
            files.append(path)
        else:
            raise ToolError("input not found: %s" % raw)

    seen, unique = set(), []
    for path in files:
        key = os.path.normcase(os.path.abspath(str(path)))
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def parse_track_spec(spec: str, count: int) -> list:
    """Turn --track ('0', '0,2' or 'all') into audio-relative indexes."""
    text = (spec or "").strip().lower()
    if text in ("all", "*"):
        return list(range(count))

    indexes = []
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            index = int(chunk)
        except ValueError:
            raise ToolError(
                "invalid --track value %r; use a number, a comma-separated "
                "list, or 'all'" % chunk
            )
        if not 0 <= index < count:
            raise ToolError(
                "--track %d is out of range; this file has %d audio track(s) "
                "(valid: 0..%d)" % (index, count, count - 1)
            )
        if index not in indexes:
            indexes.append(index)
    if not indexes:
        raise ToolError("--track did not select any audio stream")
    return indexes


def output_path_for(src: Path, stream: dict, track_index: int, track_count: int, out_dir) -> Path:
    """Where the extracted audio of one stream should be written."""
    directory = Path(out_dir).expanduser() if out_dir else src.parent
    name = src.stem
    if track_count > 1:
        language = (stream_tags(stream).get("language") or "").strip().lower()
        suffix = language if language and language not in ("und", "unknown") else "track%d" % track_index
        name = "%s.%s" % (name, suffix)
    return directory / (name + codec_extension(stream.get("codec_name")))


class ProgressDisplay:
    """A single self-updating status line.

    The moving bar needs a real terminal: when stdout is a pipe or a file the
    \r repainting would just pollute the output, so only the final line is
    printed there.
    """

    def __init__(self, prefix: str, quiet: bool = False):
        self.enabled = not quiet and sys.stdout.isatty()
        self.prefix = prefix
        self._drawn = 0
        self._visible = False

    def _write(self, text: str) -> None:
        padding = " " * max(0, self._drawn - len(text))
        sys.stdout.write("\r" + text + padding)
        sys.stdout.flush()
        self._drawn = len(text)
        self._visible = True

    def update(self, fraction=None, speed=None, eta=None) -> None:
        if not self.enabled:
            return
        width = 28
        if fraction is None:
            bar, percent = "-" * width, "  ?  "
        else:
            fraction = min(max(fraction, 0.0), 1.0)
            filled = int(width * fraction)
            bar = "#" * filled + "-" * (width - filled)
            percent = "%5.1f%%" % (fraction * 100)
        text = "%s [%s] %s" % (self.prefix, bar, percent)
        tail = [part for part in (speed, "ETA %s" % eta if eta else None) if part]
        if tail:
            text += "  " + "  ".join(tail)
        self._write(text)

    def finish(self, message: str = "") -> None:
        if self.enabled and self._visible:
            sys.stdout.write("\r" + " " * self._drawn + "\r")
            sys.stdout.flush()
            self._visible = False
            self._drawn = 0
        if message:
            print(message)


def parse_progress_seconds(line: str):
    """Read ffmpeg's -progress timestamp, tolerating version differences."""
    key, _, value = line.partition("=")
    if key == "out_time":
        match = OUT_TIME_RE.match(line)
        if not match:
            return None
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if key in ("out_time_ms", "out_time_us"):
        # Both keys have historically carried microseconds, and out_time_us
        # only exists from FFmpeg 4.3 on, so both are read the same way.
        try:
            return int(value) / 1_000_000
        except ValueError:
            return None
    return None


def run_ffmpeg(ffmpeg: str, src: Path, track_index: int, out_path: Path,
               duration: float, overwrite: bool, display: ProgressDisplay,
               verbose: bool) -> str:
    """Remux one audio stream.  Returns '' on success, else the error text."""
    command = [
        ffmpeg, "-hide_banner", "-nostdin", "-v", "error",
        "-y" if overwrite else "-n",
        "-i", str(src),
        "-map", "0:a:%d" % track_index,
        "-c:a", "copy",
        "-progress", "pipe:1",
        "-nostats",
        str(out_path),
    ]
    if verbose:
        print("  $ " + " ".join(quote_arg(part) for part in command))

    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    # ffmpeg writes its progress to stdout and its errors to stderr; drain
    # stderr on a thread so a chatty error cannot deadlock the pipe.
    stderr_chunks = []

    def drain_stderr():
        try:
            stderr_chunks.append(process.stderr.read() or "")
        finally:
            process.stderr.close()

    drainer = threading.Thread(target=drain_stderr, daemon=True)
    drainer.start()

    out_time = None
    speed = None
    try:
        for raw_line in process.stdout:
            line = raw_line.strip()
            key, _, value = line.partition("=")
            if key in ("out_time", "out_time_ms", "out_time_us"):
                seconds = parse_progress_seconds(line)
                if seconds is not None:
                    out_time = seconds
            elif key == "speed":
                speed = None if value in ("", "N/A") else value
            elif key == "progress":
                fraction = out_time / duration if out_time is not None and duration else None
                eta = None
                if fraction is not None and out_time < duration and speed:
                    try:
                        factor = float(speed.rstrip("x"))
                    except ValueError:
                        factor = 0.0
                    if factor > 0:
                        eta = format_clock((duration - out_time) / factor)
                display.update(fraction=fraction, speed=speed, eta=eta)
                if value == "end":
                    break
        process.stdout.close()
        returncode = process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        raise
    finally:
        drainer.join(timeout=5)

    if returncode == 0:
        return ""
    lines = [line for line in "".join(stderr_chunks).splitlines() if line.strip()]
    return lines[-1].strip() if lines else "ffmpeg exited with code %d" % returncode


def cmd_extract(args) -> int:
    ffmpeg = find_tool("ffmpeg", "FFMPEG")
    ffprobe = find_tool("ffprobe", "FFPROBE")
    files = collect_inputs(args.inputs, args.recursive)
    if not files:
        raise ToolError("no input files to process")

    jobs, skipped, failures = [], [], []
    for src in files:
        try:
            report = probe(ffprobe, src)
        except ToolError as exc:
            failures.append((src, str(exc)))
            continue

        streams = audio_streams(report)
        if not streams:
            failures.append((src, "no audio track"))
            continue
        try:
            indexes = parse_track_spec(args.track, len(streams))
        except ToolError as exc:
            failures.append((src, str(exc)))
            continue

        duration = format_duration_of(report)
        for index in indexes:
            out_path = output_path_for(src, streams[index], index, len(streams), args.output)
            if os.path.abspath(str(out_path)) == os.path.abspath(str(src)):
                failures.append((src, "output would overwrite the input file"))
                continue
            if out_path.exists() and not args.overwrite:
                skipped.append((out_path, "already exists (use -y to overwrite)"))
                continue
            jobs.append((src, index, out_path, duration))

    if jobs:
        print("Extracting %d audio track(s) from %d file(s)" % (len(jobs), len(files)))

    succeeded = 0
    for position, (src, index, out_path, duration) in enumerate(jobs, start=1):
        label = "[%d/%d] %s -> %s" % (position, len(jobs), src.name, out_path.name)
        display = ProgressDisplay(label, quiet=args.quiet)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            error = run_ffmpeg(
                ffmpeg, src, index, out_path, duration,
                args.overwrite, display, args.verbose,
            )
        except KeyboardInterrupt:
            display.finish()
            print("\n%s: interrupted" % PROG, file=sys.stderr)
            return 130
        except OSError as exc:
            display.finish("%s  FAILED: %s" % (label, exc))
            failures.append((src, str(exc)))
            continue

        if error:
            display.finish("%s  FAILED: %s" % (label, error))
            failures.append((src, "track %d: %s" % (index, error)))
        else:
            display.finish("%s  done in %.1fs" % (label, time.monotonic() - started))
            succeeded += 1

    if len(jobs) > 1 or skipped or failures:
        print()
        print("Summary: %d succeeded, %d skipped, %d failed"
              % (succeeded, len(skipped), len(failures)))
        for path, reason in skipped:
            print("  skipped  %s: %s" % (path, reason))
        for src, reason in failures:
            print("  failed   %s: %s" % (src, reason))

    return 1 if (failures or skipped) else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def add_input_arguments(parser) -> None:
    parser.add_argument(
        "inputs", nargs="+", metavar="PATH",
        help="video file(s), or directories to scan for video files",
    )
    parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="also scan sub-directories of directory inputs",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Inspect video files and extract their audio tracks in place. "
                    "Extraction is a lossless stream copy, never a re-encode.",
        epilog=examples_for(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="%s %s" % (PROG, __version__))

    subparsers = parser.add_subparsers(dest="command", metavar="{info,extract}")
    subparsers.required = True

    info = subparsers.add_parser(
        "info",
        help="show detailed information about video file(s)",
        description="Show container, duration and per-stream details for each file.",
        epilog=examples_for("info"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_input_arguments(info)
    info.add_argument("--json", action="store_true",
                      help="print the raw ffprobe JSON instead of a summary")
    info.set_defaults(func=cmd_info)

    extract = subparsers.add_parser(
        "extract",
        help="extract audio track(s) from video file(s)",
        description="Remux the audio track(s) of each video into an audio-only file. "
                    "Output defaults to the input's own directory, same base name.",
        epilog=examples_for("extract"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_input_arguments(extract)
    extract.add_argument(
        "-t", "--track", default="0", metavar="SPEC",
        help="audio track(s) to extract: a number, a comma-separated list, "
             "or 'all' (default: 0)",
    )
    extract.add_argument(
        "-o", "--output", metavar="DIR",
        help="write the audio files into DIR instead of next to each input",
    )
    extract.add_argument(
        "-y", "--overwrite", action="store_true",
        help="overwrite existing output files (default: skip them)",
    )
    extract.add_argument("-q", "--quiet", action="store_true",
                         help="do not draw the progress line")
    extract.add_argument("-v", "--verbose", action="store_true",
                         help="print the ffmpeg command before running it")
    extract.set_defaults(func=cmd_extract)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ToolError as exc:
        print("%s: error: %s" % (PROG, exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n%s: interrupted" % PROG, file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())