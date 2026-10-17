#!/usr/bin/env bash
# Puts `jocal` on PATH as a symlink into this repo, so repo edits take effect without reinstalling.
#   ./install.sh [bin dir]    default ~/.local/bin
set -euo pipefail
src="$(cd "$(dirname "$0")" && pwd)/jocal"
dest="${1:-$HOME/.local/bin}/jocal"
if { [ -e "$dest" ] || [ -L "$dest" ]; } && [ "$(readlink -f "$dest")" != "$(readlink -f "$src")" ]; then
  echo "install.sh: $dest exists and isn't a link to $src; remove it first" >&2; exit 1
fi
mkdir -p "$(dirname "$dest")"
ln -sfn "$src" "$dest"
echo "linked $dest -> $src"
