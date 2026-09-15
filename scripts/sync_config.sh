#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_PATH="$REPO_ROOT/daemon/config/config.json"
DEST_DIR="$REPO_ROOT/config"
DEST_PATH="$DEST_DIR/config.json"

if [[ ! -f "$SRC_PATH" ]]; then
  echo "Source config not found at $SRC_PATH" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"
cp "$SRC_PATH" "$DEST_PATH"
echo "Synced $SRC_PATH -> $DEST_PATH"
