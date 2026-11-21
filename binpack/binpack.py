#!/usr/bin/env python3
"""binpack - split a directory's top-level entries into numbered bins, and restore them.

Bin mode:
    binpack.py <PATH> <n>
Counts the direct children of PATH (non-recursive). Hidden and system entries
are counted but never moved. When both the total entry count and the movable
entry count exceed n, the movable entries are sorted by name (natural,
case-insensitive) and distributed into PATH\\<prefix>_<NN> folders holding n
entries each; the last folder takes the remainder. Every top-level entry is
moved as a whole unit, so the structure inside a folder is always preserved.

File-count mode:
    binpack.py <PATH> <n> -f
Same bin layout and the same restore command, but the strategy is counted in
files: PATH is scanned recursively for its total file count (hidden files
included) and whole top-level entries are packed greedily in name order into
bins holding at most n files each. Entries are still never split, so folder
structure stays intact and an entry heavier than n gets a bin of its own.

Restore mode:
    binpack.py <PATH> -r
Finds PATH\\<prefix>_<number> folders (prefix = last component of PATH, the
%~nx1 equivalent), moves their content back to the top level of PATH and
removes the emptied folders. Entries that already exist are never overwritten.

Options:
    -f, --files count and pack by recursive file totals instead of entry counts
    -y, --yes   skip the confirmation prompt (unattended use)
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import sys

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_CANCELLED = 2
EXIT_PARTIAL = 3

VERSION = "1.0"

RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)

HIDDEN_ATTRIBUTES = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0x2) | getattr(
    stat, "FILE_ATTRIBUTE_SYSTEM", 0x4
)

# Blocks drive roots and the root of a user profile (exact match only).
PROTECTED_EXACT_ENV = ("USERPROFILE",)
# Blocks these directories and everything below them.
PROTECTED_WITHIN_ENV = (
    "WINDIR",
    "ProgramFiles",
    "ProgramFiles(x86)",
    "ProgramData",
    "APPDATA",
    "LOCALAPPDATA",
)


# --------------------------------------------------------------------- helpers


def natural_key(name: str):
    """Case-insensitive natural sort key: a2 < a10, ties broken by raw name."""
    key = []
    for index, part in enumerate(re.split(r"(\d+)", name)):
        if index % 2:
            key.append((1, int(part), ""))
        else:
            key.append((0, 0, part.casefold()))
    key.append((0, 0, name))
    return key


def canonical(path: str) -> str:
    """Absolute, '..'- and link-resolved, case-folded, without trailing separator."""
    resolved = os.path.realpath(os.path.abspath(path))
    drive, tail = os.path.splitdrive(resolved)
    if os.name == "nt":
        # Windows silently drops trailing dots and spaces in path components, so a
        # path like "C:\Windows\ " reaches the same folder as "C:\Windows".
        parts = [cleaned for cleaned in (p.rstrip(" .") for p in tail.split(os.sep)) if cleaned]
        resolved = (drive + os.sep + os.sep.join(parts)) if parts else drive + os.sep
    return os.path.normcase(resolved)


def protected_sets():
    exact = {canonical(drive + os.sep) for drive in ("C:", "D:", "E:")}
    exact = {item for item in exact if os.path.exists(item)}
    within = set()
    for name in PROTECTED_EXACT_ENV:
        value = os.environ.get(name)
        if value:
            exact.add(canonical(value))
    for name in PROTECTED_WITHIN_ENV:
        value = os.environ.get(name)
        if value:
            within.add(canonical(value))
    profile = os.environ.get("USERPROFILE")
    if profile:
        within.add(canonical(os.path.join(profile, "AppData")))
        parent = os.path.dirname(profile)
        if parent:
            exact.add(canonical(parent))
    within -= exact
    return exact, within


def refusal_reason(path: str):
    """Return a human readable reason when PATH must not be touched, else None."""
    exact, within = protected_sets()
    target = canonical(path)
    drive, tail = os.path.splitdrive(target)
    if not tail.strip(os.sep):
        return "drive root"
    if target in exact:
        return "protected location"
    for item in sorted(within):
        if target == item or target.startswith(item + os.sep):
            return f"inside {item}"
    return None


def validate_prefix(prefix: str):
    if not prefix:
        return "the last component of the path is empty"
    if prefix in RESERVED_NAMES or prefix.upper().split(".")[0] in RESERVED_NAMES:
        return f"the last component '{prefix}' is a reserved device name"
    if prefix[-1] in " .":
        return f"the last component '{prefix}' ends with a dot or a space"
    return None


def is_hidden_entry(parent: str, name: str) -> bool:
    if os.name == "nt":
        try:
            attributes = os.stat(
                os.path.join(parent, name), follow_symlinks=False
            ).st_file_attributes
        except OSError:
            return name.startswith(".")
        return bool(attributes & HIDDEN_ATTRIBUTES)
    return name.startswith(".")


def scan_entries(path: str):
    """Direct children of path as (name, is_directory) pairs."""
    entries = []
    with os.scandir(path) as iterator:
        for item in iterator:
            entries.append((item.name, item.is_dir(follow_symlinks=False)))
    return entries


def move_entry(source: str, target: str) -> None:
    try:
        os.replace(source, target)
    except OSError:
        shutil.move(source, target)


def confirm(prompt: str = "Proceed? [y/N] ") -> bool:
    try:
        answer = input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer.strip().lower() in ("y", "yes")


def print_bin_line(name: str, members, files=None) -> None:
    word = "entry" if len(members) == 1 else "entries"
    if files is None:
        print(f"  {name:<16} <- {len(members):>4} {word:<7} ({members[0]} .. {members[-1]})")
    else:
        file_word = "file" if files == 1 else "files"
        print(f"  {name:<16} <- {files:>6} {file_word:<5} / {len(members):>4} {word:<7}"
              f" ({members[0]} .. {members[-1]})")


def bin_names_for(prefix: str, count: int):
    width = max(1, len(str(count)))
    return [f"{prefix}_{index:0{width}d}" for index in range(1, count + 1)]


# ------------------------------------------------------------ file-count mode


def recursive_file_count(root: str) -> int:
    """Number of files below root: hidden ones included, links never followed."""
    count = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as iterator:
                for item in iterator:
                    try:
                        if item.is_dir(follow_symlinks=False):
                            stack.append(item.path)
                        else:
                            count += 1
                    except OSError:
                        count += 1
        except OSError:
            continue
    return count


def pack_by_files(movable, weights, n: int):
    """Whole entries in name order, greedily filled up to n files per bin.

    An entry heavier than n gets a bin of its own instead of being split, so the
    structure inside a folder is always preserved.
    """
    groups = []
    current = []
    current_files = 0
    for name in movable:
        weight = weights[name]
        if current and current_files + weight > n:
            groups.append(current)
            current = []
            current_files = 0
        current.append(name)
        current_files += weight
    if current:
        groups.append(current)
    return groups


# ------------------------------------------------------------------- bin mode


def cmd_bin(path: str, n: int, assume_yes: bool, file_mode: bool = False) -> int:
    target = os.path.abspath(path)
    if not os.path.isdir(target):
        print(f"Error: not an existing directory: {target}")
        return EXIT_USAGE

    reason = refusal_reason(target)
    if reason:
        print(f"Error: refusing to operate on {target} ({reason}).")
        print("Edit PROTECTED_* / refusal_reason() in binpack.py if this is intentional.")
        return EXIT_USAGE

    prefix = os.path.basename(os.path.normpath(target))
    problem = validate_prefix(prefix)
    if problem:
        print(f"Error: unusable folder name prefix: {problem}.")
        return EXIT_USAGE

    entries = scan_entries(target)
    total = len(entries)
    folder_count = sum(1 for _, is_dir in entries if is_dir)
    movable, hidden = [], []
    for name, _ in entries:
        (hidden if is_hidden_entry(target, name) else movable).append(name)
    movable.sort(key=natural_key)

    weights = {}
    total_files = movable_files = 0
    if file_mode:
        for name, flag in entries:
            weights[name] = recursive_file_count(os.path.join(target, name)) if flag else 1
        total_files = sum(weights.values())
        movable_files = sum(weights[name] for name in movable)

    print(f"binpack {VERSION} - bin mode" + (" (packing by file count)" if file_mode else ""))
    print(f"Target path   : {target}")
    print(f"Total entries : {total} (files {total - folder_count}, folders {folder_count})"
          "  [non-recursive]")
    if file_mode:
        print(f"Total files   : {total_files} (recursive, hidden files included)")
    print(f"Hidden/system : {len(hidden)} entries (counted, never moved)")
    if file_mode:
        print(f"Movable       : {len(movable)} entries / {movable_files} files")
        print(f"Parameter n   : {n} files per bin")
    else:
        print(f"Movable       : {len(movable)}")
        print(f"Parameter n   : {n}")

    if file_mode:
        if total_files <= n:
            print(f"Nothing to do: recursive file count ({total_files}) is not greater"
                  f" than n ({n}).")
            return EXIT_OK
        groups = pack_by_files(movable, weights, n)
        if len(groups) < 2:
            if movable_files <= n:
                print(f"Nothing to do: only {movable_files} movable files, they already fit"
                      f" in a single bin (same rule as n).")
            else:
                heaviest = max(movable, key=lambda name: weights[name])
                print(f"Nothing to do: entry '{heaviest}' alone holds {weights[heaviest]}"
                      f" files, more than n ({n}), and whole folders are never split.")
                print("A recursive-splitting mode would be needed to meet n here.")
            return EXIT_OK
    else:
        if total <= n:
            print(f"Nothing to do: total entries ({total}) is not greater than n ({n}).")
            return EXIT_OK
        if len(movable) <= n:
            print(f"Nothing to do: only {len(movable)} movable entries, they already fit in a"
                  f" single bin (same rule as total == n).")
            return EXIT_OK
        groups = [movable[start:start + n] for start in range(0, len(movable), n)]

    bin_count = len(groups)
    names = bin_names_for(prefix, bin_count)
    collisions = [name for name in names if os.path.lexists(os.path.join(target, name))]
    if collisions:
        print(f"Error: target folder(s) already exist: {', '.join(collisions)}.")
        print("Nothing was changed.")
        return EXIT_USAGE

    group_files = [sum(weights[item] for item in members) for members in groups] if file_mode else []
    print(f"Prefix        : {prefix}")
    print(f"Plan          : {bin_count} bin folders")
    for index, (name, members) in enumerate(zip(names, groups)):
        if file_mode:
            print_bin_line(name, members, files=group_files[index])
        else:
            print_bin_line(name, members)
    print("Order         : case-insensitive natural sort by name")
    if file_mode:
        heavy = [(name, files) for name, files in zip(names, group_files) if files > n]
        if heavy:
            print(f"Warning: {len(heavy)} bin(s) exceed n, because a single entry is heavier"
                  f" than n and whole entries are never split:")
            for name, files in heavy:
                print(f"  {name}: {files} files")

    if not assume_yes and not confirm():
        print("Cancelled by user. Nothing was changed.")
        return EXIT_CANCELLED

    failures = []
    moved = moved_files = 0
    for name, members in zip(names, groups):
        bin_path = os.path.join(target, name)
        os.makedirs(bin_path)
        for member in members:
            try:
                move_entry(os.path.join(target, member), os.path.join(bin_path, member))
                moved += 1
                if file_mode:
                    moved_files += weights[member]
            except OSError as error:
                failures.append((member, f"{error}"))
    print(f"Created {bin_count} bin folders under {target}")

    if failures:
        print(f"Failures ({len(failures)}):")
        for member, message in failures:
            print(f"  {member}: {message}")
        print(f"Partial completion: {moved} entries moved, {len(failures)} not moved.")
        return EXIT_PARTIAL

    counted = f"{moved} entries ({moved_files} files)" if file_mode else f"{moved} entries"
    print(f"Done: {counted} moved into {bin_count} bins"
          f" (top level now holds {len(hidden)} hidden/system entries plus the bins).")
    return EXIT_OK


# --------------------------------------------------------------- restore mode


def cmd_restore(path: str, assume_yes: bool) -> int:
    target = os.path.abspath(path)
    if not os.path.isdir(target):
        print(f"Error: not an existing directory: {target}")
        return EXIT_USAGE

    reason = refusal_reason(target)
    if reason:
        print(f"Error: refusing to operate on {target} ({reason}).")
        print("Edit PROTECTED_* / refusal_reason() in binpack.py if this is intentional.")
        return EXIT_USAGE

    prefix = os.path.basename(os.path.normpath(target))
    problem = validate_prefix(prefix)
    if problem:
        print(f"Error: unusable folder name prefix: {problem}.")
        return EXIT_USAGE

    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)$", re.IGNORECASE)
    bins = []
    for name, is_dir in scan_entries(target):
        if is_dir:
            match = pattern.match(name)
            if match:
                bins.append((int(match.group(1)), name))
    bins.sort()

    print(f"binpack {VERSION} - restore mode")
    print(f"Target path   : {target}")
    print(f"Prefix        : {prefix}")

    if not bins:
        print(f"Nothing to do: no {prefix}_<number> folder found.")
        return EXIT_OK

    contents = [(name, [item for item, _ in scan_entries(os.path.join(target, name))])
                for _, name in bins]
    entry_count = sum(len(members) for _, members in contents)

    print(f"Bins found    : {len(bins)}"
          f" ({', '.join(name for name, _ in contents)})")
    print(f"Entries       : {entry_count} to move back")
    print("Plan          : existing entries are never overwritten;"
          " every bin that ends up empty is removed")

    if not assume_yes and not confirm():
        print("Cancelled by user. Nothing was changed.")
        return EXIT_CANCELLED

    moved = 0
    removed = 0
    conflicts = []
    failures = []
    for name, members in contents:
        bin_path = os.path.join(target, name)
        for member in sorted(members, key=natural_key):
            destination = os.path.join(target, member)
            if os.path.lexists(destination):
                conflicts.append(f"{name}/{member}")
                continue
            try:
                move_entry(os.path.join(bin_path, member), destination)
                moved += 1
            except OSError as error:
                failures.append((f"{name}/{member}", f"{error}"))
        try:
            if not scan_entries(bin_path):
                os.rmdir(bin_path)
                removed += 1
        except OSError as error:
            failures.append((name, f"could not remove empty bin: {error}"))

    print(f"Moved {moved} entries back, removed {removed} empty bins.")
    if conflicts:
        print(f"Conflicts ({len(conflicts)}) kept inside their bins (never overwritten):")
        for item in conflicts:
            print(f"  {item}")
    if failures:
        print(f"Failures ({len(failures)}):")
        for member, message in failures:
            print(f"  {member}: {message}")
    if conflicts or failures:
        return EXIT_PARTIAL
    return EXIT_OK


# -------------------------------------------------------------------- startup


def parse_n(value: str):
    try:
        number = int(value, 10)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def main(argv) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    arguments = list(argv)
    assume_yes = False
    restore = False
    file_mode = False
    positional = []
    for argument in arguments:
        lowered = argument.lower()
        if lowered in ("-y", "--yes"):
            assume_yes = True
        elif lowered in ("-r", "--restore"):
            restore = True
        elif lowered in ("-f", "--files"):
            file_mode = True
        elif lowered in ("-h", "--help"):
            print(__doc__.strip())
            return EXIT_OK
        elif argument.startswith("-") and len(argument) > 1 and not re.fullmatch(r"[-+]?[0-9.]+", argument):
            # A numeric token such as -3 falls through, so that parse_n() can
            # explain the rule instead of calling it an unknown option.
            print(f"Error: unknown option: {argument}")
            return EXIT_USAGE
        else:
            positional.append(argument)

    if not positional:
        print("Error: missing <PATH>.")
        print(f"Usage: {os.path.basename(__file__)} <PATH> <n> [-f] [-y]")
        print(f"       {os.path.basename(__file__)} <PATH> -r [-y]")
        return EXIT_USAGE

    path = positional[0]
    extra = positional[1:]

    if restore:
        if extra:
            print(f"Note: n ({extra[0]}) is ignored in restore mode.")
        if file_mode:
            print("Note: -f is ignored in restore mode (bins always hold whole entries).")
        return cmd_restore(path, assume_yes)

    if not extra:
        print("Error: missing <n>.")
        print(f"Usage: {os.path.basename(__file__)} <PATH> <n> [-f] [-y]")
        return EXIT_USAGE
    number = parse_n(extra[0])
    if number is None:
        print(f"Error: n must be a positive integer (got {extra[0]!r}).")
        return EXIT_USAGE
    if len(extra) > 1:
        print(f"Error: unexpected argument: {extra[1]}")
        return EXIT_USAGE
    return cmd_bin(path, number, assume_yes, file_mode)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))