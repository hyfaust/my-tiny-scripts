#!/usr/bin/env bash
# Fast Hugging Face download for LM Studio.
#
# LM Studio's own downloader uses a single connection against huggingface.co,
# which is reset/throttled on mainland networks -> ~100 KB/s. This script pulls
# the same file from a mirror with 16 parallel connections (aria2c), verifies
# sha256 against the repo metadata, and drops it into the LM Studio model dir.
#
# Usage:
#   ./dl_hf_fast.sh <repo_id> [file ...] [-d DEST_DIR]
# Example:
#   ./dl_hf_fast.sh prithivMLmods/VibeThinker-3B-GGUF VibeThinker-3B.Q4_K_S.gguf
# Runs under Git Bash / MSYS2 natively; started from WSL it re-execs into
# "C:\Program Files\Git\bin\bash.exe" automatically.
#
# Env:
#   HF_MIRROR  mirror base URL (default: https://hf-mirror.com)
#   ARIA_CONN  parallel connections per server (default: 16)
set -euo pipefail

# Hand off to Windows Git Bash when started from WSL: the Linux side usually has
# no aria2c/python, and Windows aria2c.exe cannot consume /mnt/c POSIX paths.
if [ -n "${WSL_DISTRO_NAME:-}" ] && [ -d /mnt/c ]; then
  GB="/mnt/c/Program Files/Git/bin/bash.exe"
  if [ -x "$GB" ]; then
    to_win() {
      case "$1" in
        /mnt/[a-z]/*) printf '%s:/%s' "$(printf '%s' "${1:5:1}" | tr 'a-z' 'A-Z')" "${1:7}" ;;
        *) printf '%s' "$1" ;;
      esac
    }
    self="$0"
    case "$self" in
      */*) ;;
      *) self="$(command -v -- "$self" 2>/dev/null || printf '%s' "$self")" ;;
    esac
    exec "$GB" -c 'cd "$1" || exit 1; shift; exec bash "$@"' \
         _ "$(to_win "$PWD")" "$(to_win "$self")" "$@"
  fi
fi

MIRROR="${HF_MIRROR:-https://hf-mirror.com}"
CONN="${ARIA_CONN:-16}"
DEST=""
# USERPROFILE/HOME are Windows-style in some shells, POSIX in others.
to_posix() {
  local p="${1//\\//}"
  if [[ "$p" =~ ^([A-Za-z]):/(.*)$ ]]; then
    printf '/%s/%s' "${BASH_REMATCH[1],,}" "${BASH_REMATCH[2]}"
  else
    printf '%s' "$p"
  fi
}
# Pick the profile dir that actually holds .lmstudio; HOME may be a POSIX-only
# path (e.g. /home/<user>) in some MSYS shells.
PROF_U=""
for cand in "${USERPROFILE:-}" "${HOME:-}"; do
  [ -n "$cand" ] || continue
  p="$(to_posix "$cand")"
  if [ -d "$p/.lmstudio" ]; then PROF_U="$p"; break; fi
done
if [ -z "$PROF_U" ]; then
  for d in /c/Users/*/ /mnt/c/Users/*/; do
    if [ -d "$d/.lmstudio" ]; then PROF_U="${d%/}"; break; fi
  done
fi

REPO=""; FILES=()
while [ $# -gt 0 ]; do
  case "$1" in
    -d) DEST="$2"; shift 2 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *)  if [ -z "$REPO" ]; then REPO="$1"; else FILES+=("$1"); fi; shift ;;
  esac
done
[ -n "$REPO" ] || { echo "usage: $0 <repo_id> [file ...] [-d DEST_DIR]" >&2; exit 2; }

# repo_id = owner/name; subfolders inside the repo are kept as-is.
DEST="${DEST:-$PROF_U/.lmstudio/models/$REPO}"
DEST="$(to_posix "$DEST")"

# Metadata (size + sha256) comes from the mirror's tree API, which works where
# huggingface.co/api is unreachable.
META="$(mktemp)"
trap 'rm -f "$META"' EXIT
if ! curl -fsSL --max-time 60 "$MIRROR/api/models/$REPO/tree/main?recursive=true" -o "$META"; then
  echo "failed to fetch repo metadata from $MIRROR" >&2
  exit 1
fi

# WSL 只带 python3，Git Bash 通常只有 python；用哪个都行。
PY="${PYTHON:-}"
if [ -z "$PY" ] || [ ! -x "$PY" ]; then
  PY="$(command -v python || command -v python3 || true)"
fi
[ -n "$PY" ] || { echo "python not found; install python 3" >&2; exit 1; }

# Look up one entry: prints "<size> <sha256>".
lookup() {
  "$PY" - "$META" "$1" <<'PY'
import json, sys
meta, path = sys.argv[1], sys.argv[2]
for e in json.load(open(meta, encoding="utf-8")):
    if e.get("path") == path:
        lfs = e.get("lfs") or {}
        print(e.get("size") or "", lfs.get("oid") or "")
        break
PY
}
if [ ${#FILES[@]} -eq 0 ]; then
  echo "no file given; available files in $REPO:"
  "$PY" - "$META" <<'PY'
import json, sys
for e in json.load(open(sys.argv[1], encoding="utf-8")):
    if e.get("type") == "file":
        print("  ", e["path"])
PY
  exit 0
fi

# aria2c is not always on PATH (e.g. scoop shims entry without a drive letter).
ARIA="${ARIA2C:-}"
if [ -z "$ARIA" ] || [ ! -x "$ARIA" ]; then
  ARIA="$(command -v aria2c || true)"
fi
if [ -z "$ARIA" ] || [ ! -x "$ARIA" ]; then
  ARIA=""
  for c in "$PROF_U"/scoop/shims/aria2c.exe /c/Users/*/scoop/shims/aria2c.exe \
           /mnt/c/Users/*/scoop/shims/aria2c.exe \
           /c/ProgramData/scoop/shims/aria2c.exe "/c/Program Files/aria2/aria2c.exe" \
           /usr/bin/aria2c /usr/local/bin/aria2c; do
    [ -x "$c" ] && { ARIA="$c"; break; }
  done
fi
[ -n "$ARIA" ] && [ -x "$ARIA" ] || { echo "aria2c not found; install it with: scoop install aria2" >&2; exit 1; }

mkdir -p "$DEST"
rc=0
for f in "${FILES[@]}"; do
  info="$(lookup "$f")"
  size="${info%% *}"; sha="${info##* }"
  [ -n "$size" ] || { echo "!! $f not found in repo $REPO" >&2; rc=1; continue; }
  out="$DEST/$f"
  mkdir -p "$(dirname "$out")"
  echo "==> $f ($size bytes)"
  # -c resume, -x/-s many connections, --file-allocation=none keeps sparse
  # preallocation off so a restart does not rewrite the whole file.
  "$ARIA" -x"$CONN" -s"$CONN" -k1M -c --file-allocation=none \
         --console-log-level=warn --summary-interval=0 --check-certificate=false \
         -d "$(dirname "$out")" -o "$(basename "$out")" \
         "$MIRROR/$REPO/resolve/main/$f"
  if [ -n "$sha" ]; then
    echo "    verifying sha256"
    got="$(sha256sum "$out" | cut -d' ' -f1)"
    if [ "$got" != "$sha" ]; then
      echo "!! sha256 mismatch for $f" >&2
      echo "   expected $sha" >&2
      echo "   got      $got" >&2
      rm -f "$out"
      rc=1
    fi
  fi
done
exit $rc