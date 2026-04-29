#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  setup-codexdeck-pipx.sh [--auto|--local|--git-latest] [--tag <tag>] [--inspect-logs]

Modes:
  --auto         Try local build/install first, fallback to GitHub release/tag if needed.
  --local        Build from repo only. If no wheel exists, runs `uv build`.
  --git-latest   Install from git. Uses latest local v* tag if present, else main branch.
  --tag <tag>    Install from a specific git tag when used with --git-latest.
  --inspect-logs Also show resolved log paths (print-config) and tails of log files.
  --follow-logs  Keep following log files after install. Implies --inspect-logs.
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MODE="auto"
GIT_TAG="${1:-}"
INSPECT_LOGS=false
FOLLOW_LOGS=false

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --auto)
      MODE="auto"
      shift
      ;;
    --local)
      MODE="local"
      shift
      ;;
    --git-latest)
      MODE="git-latest"
      shift
      ;;
    --tag)
      shift
      if [ "$#" -lt 1 ]; then
        echo "ERROR: --tag requires a tag value."
        exit 1
      fi
      MODE="git-latest"
      GIT_TAG="$1"
      shift
      ;;
    --inspect-logs)
      INSPECT_LOGS=true
      shift
      ;;
    --follow-logs)
      INSPECT_LOGS=true
      FOLLOW_LOGS=true
      shift
      ;;
    *)
      echo "ERROR: Unknown argument '$1'"
      usage
      exit 1
      ;;
  esac
done

export XDG_STATE_HOME=/tmp/pipx-state
export PIPX_HOME=/tmp/pipx-home
export PIPX_BIN_DIR=/tmp/pipx-bin
mkdir -p "$XDG_STATE_HOME" "$PIPX_HOME" "$PIPX_BIN_DIR"
export PATH="$PIPX_BIN_DIR:$PATH"

if [ -x "${PIPX_BIN_DIR}/pipx" ]; then
  echo "Using existing pipx binary in $PIPX_BIN_DIR"
fi

install_from_local() {
  cd "$REPO_ROOT"
  if [ ! -d "dist" ] || ! ls dist/codexdeck-*.whl >/dev/null 2>&1; then
    UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/uv-cache} uv build
  fi
  WHEEL_PATH="$(ls dist/codexdeck-*.whl | sort | tail -n 1)"
  if [ -z "$WHEEL_PATH" ] || [ ! -f "$WHEEL_PATH" ]; then
    echo "ERROR: No wheel found after build."
    return 1
  fi
  if ! pipx install --force "$WHEEL_PATH"; then
    return 1
  fi
}

install_from_git() {
  cd "$REPO_ROOT"
  git fetch --tags --force
  if [ -z "${GIT_TAG}" ]; then
    GIT_TAG="$(git tag --sort=-v:refname | grep '^v[0-9]' | head -n 1 || true)"
  fi
  if [ -n "${GIT_TAG}" ]; then
    if pipx install --force "git+https://github.com/MLyte/CodexDeck.git@${GIT_TAG}"; then
      return 0
    fi
    return 1
  else
    if pipx install --force "git+https://github.com/MLyte/CodexDeck.git"; then
      return 0
    fi
    return 1
  fi
}

if [ "$MODE" = "local" ]; then
  install_from_local
elif [ "$MODE" = "git-latest" ]; then
  install_from_git
else
  if install_from_local; then
    :
  else
    echo "Local install failed; fallback to GitHub."
    install_from_git
  fi
fi

hash -r

echo
echo "Post-install checks:"

PIPX_BIN_CMD="$PIPX_BIN_DIR/codexdeck"
PATH_BIN="$(command -v codexdeck || true)"

if [ -x "$PIPX_BIN_CMD" ]; then
  echo "pipx-managed entrypoint: $PIPX_BIN_CMD"
  "$PIPX_BIN_CMD" --version
else
  echo "pipx-managed entrypoint not found at: $PIPX_BIN_CMD"
fi

if [ -n "$PATH_BIN" ]; then
  echo "shell-resolved entrypoint: $PATH_BIN"
  "$PATH_BIN" --version
else
  echo "shell-resolved entrypoint: not found in current PATH"
fi

if [ -n "$PATH_BIN" ] && [ "$PATH_BIN" != "$PIPX_BIN_CMD" ]; then
  echo "⚠️  PATH points to a different codexdeck executable than pipx."
  echo "   Run: hash -r"
  echo "   Consider using: $PIPX_BIN_CMD --version"
fi

if [ -n "${VIRTUAL_ENV:-}" ]; then
  echo "Active virtualenv: $VIRTUAL_ENV"
fi

if [ "$INSPECT_LOGS" = true ]; then
  echo
  echo "Log diagnostics (from pipx-managed binary):"
  PIPX_CONFIG="$("$PIPX_BIN_CMD" --print-config || true)"
  if [ -n "$PIPX_CONFIG" ]; then
    echo "$PIPX_CONFIG"
    LOG_PATH="$(printf '%s\n' "$PIPX_CONFIG" | awk -F': ' '/^log_path:/ {print $2}')"
    USER_LOG_PATH="$(printf '%s\n' "$PIPX_CONFIG" | awk -F': ' '/^user_log_path:/ {print $2}')"
    for log_file in "$LOG_PATH" "$USER_LOG_PATH"; do
      if [ -n "$log_file" ]; then
        if [ -f "$log_file" ]; then
          echo "---- $log_file (last 20 lines) ----"
          tail -n 20 "$log_file"
        else
          echo "---- $log_file (not found yet) ----"
        fi
      fi
    done
    if [ "$FOLLOW_LOGS" = true ]; then
      if [ -n "$LOG_PATH" ] && [ -n "$USER_LOG_PATH" ]; then
        echo
        echo "Following logs (Ctrl-C to stop):"
        tail -n 20 "$LOG_PATH" "$USER_LOG_PATH"
        tail -f "$LOG_PATH" "$USER_LOG_PATH"
      fi
    fi
  fi
fi
