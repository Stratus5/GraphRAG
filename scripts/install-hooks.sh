#!/usr/bin/env bash
#
# Install this repo's git hooks into the active hooks directory.
# Safe to re-run; copies over any existing hook of the same name.
# Works from the main checkout and from linked worktrees (hooks are
# shared via the common git dir).
#
#   ./scripts/install-hooks.sh
#
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
src_dir="$repo_root/scripts/hooks"

# Respect a configured core.hooksPath; otherwise use the common git dir.
hooks_dir="$(git config --get core.hooksPath || true)"
if [ -z "$hooks_dir" ]; then
  hooks_dir="$(git rev-parse --git-common-dir)/hooks"
fi
# Resolve a relative path against the repo root.
case "$hooks_dir" in
  /*) ;;
  *) hooks_dir="$repo_root/$hooks_dir" ;;
esac

mkdir -p "$hooks_dir"

installed=0
for src in "$src_dir"/*; do
  [ -f "$src" ] || continue
  name="$(basename "$src")"
  install -m 0755 "$src" "$hooks_dir/$name"
  echo "installed: $hooks_dir/$name"
  installed=$((installed + 1))
done

if [ "$installed" -eq 0 ]; then
  echo "no hooks found in $src_dir" >&2
  exit 1
fi

echo "done ($installed hook(s))."
