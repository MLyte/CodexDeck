#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export XDG_STATE_HOME=/tmp/pipx-state
export PIPX_HOME=/tmp/pipx-home
export PIPX_BIN_DIR=/tmp/pipx-bin
mkdir -p "$XDG_STATE_HOME" "$PIPX_HOME" "$PIPX_BIN_DIR"
export PATH="$PIPX_BIN_DIR:$PATH"

if [ -x "${PIPX_BIN_DIR}/pipx" ]; then
  echo "Using existing pipx binary in $PIPX_BIN_DIR"
fi

cd "$REPO_ROOT"

WHEEL_PATH="$(ls dist/codexdeck-*.whl 2>/dev/null | sort | tail -n 1 || true)"
if [ -n "$WHEEL_PATH" ] && [ -f "$WHEEL_PATH" ]; then
  pipx install --force "$WHEEL_PATH" || true
else
  echo "WARN: dist/ wheel not found in $REPO_ROOT/dist."
  echo "Run: UV_CACHE_DIR=/tmp/uv-cache uv build"
fi

hash -r
