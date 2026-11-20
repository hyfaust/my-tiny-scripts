"""
symlink.py - Move directory to another drive and replace with symbolic link.

Workflow: copy -> verify hash -> delete source -> create symlink.

Usage:
    symlink.py <dir_path> <target_path>         Copy dir to target, create symlink
    symlink.py <dir_path>                       Use default target
    symlink.py <dir_path> -d <drive>            Copy to same path on another drive
    symlink.py --set-default <target_path>      Set default target directory
    symlink.py --show-default                   Show current default target
"""

import argparse
import hashlib
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log = logging.getLogger("symlink")
log.setLevel(logging.DEBUG)

fmt = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S")
sh = logging.StreamHandler(sys.stdout)
sh.setLevel(logging.INFO)
sh.setFormatter(fmt)
log.addHandler(sh)


def setup_file_log(log_path: Path) -> None:
    """Add a file handler for detailed error logs."""
    fh = logging.FileHandler(str(log_path), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
CONFIG_FILE = Path.home() / ".symlink_config"


def get_default_target() -> str | None:
    if CONFIG_FILE.exists():
        text = CONFIG_FILE.read_text(encoding="utf-8").strip()
        return text if text else None
    return None


def set_default_target(target: str) -> None:
    CONFIG_FILE.write_text(target, encoding="utf-8")
    log.info("Default target set to: %s", target)


def show_default_target() -> None:
    target = get_default_target()
    if target:
        log.info("Current default target: %s", target)
    else:
        log.info("No default target configured.")


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def resolve_path(p: str) -> Path:
    """Resolve a path to absolute, handling relative paths."""
    path = Path(p)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def drive_letter(path: Path) -> str:
    """Return uppercase drive letter, e.g. 'C'."""
    drive = path.drive  # 'C:' or ''
    if drive:
        return drive[0].upper()
    return ""


# ---------------------------------------------------------------------------
# Hash computation
# ---------------------------------------------------------------------------
def compute_hashes(root: Path) -> dict[str, str]:
    """Compute MD5 for every file under *root*, keyed by relative path."""
    hashes: dict[str, str] = {}
    for file_path in sorted(root.rglob("*")):
        if file_path.is_file():
            rel = file_path.relative_to(root).as_posix()
            md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    md5.update(chunk)
            hashes[rel] = md5.hexdigest()
    return hashes


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------
def copy_directory(src: Path, dst: Path) -> None:
    """Copy src directory to dst using robocopy. Raises on failure."""
    log.info("Copying: %s -> %s", src, dst)
    dst.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["robocopy", str(src), str(dst), "/E", "/R:3", "/W:1"],
        capture_output=True,
        text=True,
    )

    # robocopy exit codes: 0-7 = success, 8+ = failure
    # 0 = no files copied (already identical)
    # 1 = files copied successfully
    # 2 = extra files/dirs in destination
    # 4 = mismatched files (name only)
    # 8+ = actual errors
    if result.returncode >= 8:
        error_detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"robocopy failed (exit code {result.returncode}):\n{error_detail}"
        )

    log.info("Copy completed (robocopy exit code: %d)", result.returncode)


def verify_hashes(src: Path, dst: Path) -> list[str]:
    """Compare file hashes between src and dst. Return list of mismatches."""
    log.info("Computing source hashes...")
    src_hashes = compute_hashes(src)
    log.info("Computing target hashes...")
    dst_hashes = compute_hashes(dst)

    mismatches: list[str] = []

    # Check all source files exist in destination with same hash
    for rel, src_hash in src_hashes.items():
        dst_hash = dst_hashes.get(rel)
        if dst_hash is None:
            mismatches.append(f"MISSING in target: {rel}")
        elif dst_hash != src_hash:
            mismatches.append(f"HASH MISMATCH: {rel} (src={src_hash} dst={dst_hash})")

    # Check for extra files in destination (not critical, but log it)
    for rel in dst_hashes:
        if rel not in src_hashes:
            log.warning("Extra file in target (not in source): %s", rel)

    return mismatches


def delete_source(src: Path) -> None:
    """Recursively delete the source directory."""
    log.info("Deleting source: %s", src)
    shutil.rmtree(str(src))

    # Try to remove empty parent directories up to drive root
    parent = src.parent
    drive_root = Path(src.drive + "\\") if src.drive else None
    while parent != drive_root:
        try:
            parent.rmdir()  # only removes if empty
            log.info("Removed empty parent: %s", parent)
            parent = parent.parent
        except OSError:
            break  # directory not empty or other error, stop


def create_symlink(link_path: Path, target_path: Path) -> None:
    """Create a directory symbolic link (avoids cmd.exe to handle special chars)."""
    log.info("Creating symlink: %s -> %s", link_path, target_path)
    try:
        os.symlink(str(target_path), str(link_path), target_is_directory=True)
    except OSError as e:
        raise RuntimeError(f"Failed to create symlink: {e}")

    log.info("Symlink created successfully.")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_source(src: Path) -> None:
    """Validate the source directory."""
    if not src.exists():
        raise FileNotFoundError(f"Source does not exist: {src}")
    if src.is_file():
        raise ValueError(f"Source is a file, not a directory: {src}")
    if src.is_symlink():
        raise ValueError(f"Source is already a symbolic link: {src}")


def validate_target(src: Path, target: Path) -> None:
    """Validate the target path."""
    if drive_letter(src) == drive_letter(target):
        raise ValueError(
            f"Source ({drive_letter(src)}:) and target ({drive_letter(target)}:) "
            f"are on the same drive. No need to symlink."
        )
    # Check target is not a descendant of source
    try:
        target.resolve().relative_to(src.resolve())
        raise ValueError(f"Target ({target}) is inside source ({src}). Cannot proceed.")
    except ValueError as e:
        if "is inside source" in str(e):
            raise
    except Exception:
        pass  # target is not inside source, which is what we want


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------
def run_symlink(src: Path, target_base: Path) -> None:
    """Execute the full symlink workflow."""
    # Target directory = target_base / src_name
    target = target_base / src.name

    validate_source(src)
    validate_target(src, target)

    log.info("=" * 60)
    log.info("Source:      %s", src)
    log.info("Target:      %s", target)
    log.info("=" * 60)

    # Step 1: Copy
    try:
        copy_directory(src, target)
    except RuntimeError as e:
        log.error("Copy failed: %s", e)
        sys.exit(1)

    # Step 2: Verify hashes
    mismatches = verify_hashes(src, target)
    if mismatches:
        log.error("Hash verification FAILED! %d file(s) mismatched.", len(mismatches))
        log.error("Source directory will NOT be deleted.")

        # Write log
        log_path = Path.cwd() / f"symlink_hash_error_{datetime.now():%Y%m%d_%H%M%S}.log"
        setup_file_log(log_path)
        log.error("Detailed log written to: %s", log_path)
        for entry in mismatches:
            log.error("  %s", entry)

        sys.exit(2)

    log.info("Hash verification passed. All files match.")

    # Step 3: Delete source
    try:
        delete_source(src)
    except OSError as e:
        log.error("Failed to delete source: %s", e)
        sys.exit(3)

    # Step 4: Create symlink
    try:
        create_symlink(src, target)
    except RuntimeError as e:
        log.error("Failed to create symlink: %s", e)
        log.error("Data is at: %s", target)
        sys.exit(4)

    log.info("=" * 60)
    log.info("Done! Symlink created:")
    log.info("  %s -> %s", src, target)
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Move directory to another drive and replace with symbolic link.",
        usage="%(prog)s <dir_path> [target_path | -d DRIVE] [options]\n"
              "       %(prog)s --set-default <target_path>\n"
              "       %(prog)s --show-default",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("dir_path", nargs="?", help="Source directory path")
    parser.add_argument("target_path", nargs="?", help="Target base directory")
    parser.add_argument(
        "-d", "--drive",
        help="Target drive letter (e.g. E). Uses same absolute path on that drive.",
    )
    parser.add_argument(
        "--set-default",
        metavar="TARGET",
        help="Set the default target directory.",
    )
    parser.add_argument(
        "--show-default",
        action="store_true",
        help="Show the current default target directory.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # --- Handle config commands ---
    if args.show_default:
        show_default_target()
        return

    if args.set_default:
        target = resolve_path(args.set_default)
        if not target.exists():
            log.error("Default target path does not exist: %s", target)
            sys.exit(1)
        set_default_target(str(target))
        return

    # --- Require source ---
    if not args.dir_path:
        log.error("Error: source directory is required.")
        log.error("Usage: symlink.py <dir_path> [target_path | -d DRIVE]")
        sys.exit(1)

    src = resolve_path(args.dir_path)

    # --- Determine target ---
    if args.drive:
        # -d mode: same absolute path on different drive
        drive = args.drive.upper().rstrip(":")
        if len(drive) != 1 or not drive.isalpha():
            log.error("Invalid drive letter: %s", args.drive)
            sys.exit(1)

        src_drive = drive_letter(src)
        if src_drive == drive:
            log.error(
                "Source drive (%s:) and target drive (%s:) are the same.",
                src_drive, drive,
            )
            sys.exit(1)

        # Build target: same path but on different drive
        target = Path(drive + ":" + src.anchor[2:] + "\\".join(src.parts[1:]))
        # Special case: if src is "C:\foo\bar", target is "E:\foo\bar"
        # src.parts = ('C:\\', 'foo', 'bar')
        # We want: E:\foo\bar
        target = Path(drive + ":\\" + "\\".join(src.parts[1:]))

        log.info("Drive mode: target = %s", target)
        run_symlink(src, target.parent)
        return

    if args.target_path:
        target_base = resolve_path(args.target_path)
    else:
        # Use default target
        default = get_default_target()
        if not default:
            log.error("No target specified and no default configured.")
            log.error("Set a default with: symlink.py --set-default <target_path>")
            log.error("Or specify a target: symlink.py <dir_path> <target_path>")
            sys.exit(1)
        target_base = Path(default)
        log.info("Using default target: %s", target_base)

    run_symlink(src, target_base)


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        log.error(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        log.info("Interrupted.")
        sys.exit(130)
