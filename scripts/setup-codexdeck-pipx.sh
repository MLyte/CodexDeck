#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  setup-codexdeck-pipx.sh [--auto|--local|--github|--git-latest] [--tag <tag>] [--inspect-logs]

Modes:
  --auto         Try local build/install first, fallback to GitHub release/tag if needed.
  --local        Build from repo only. If no wheel exists, runs `uv build`.
  --github       Install from GitHub. Uses latest local v* tag if present, else main branch.
  --git-latest   Alias of --github.
  --tag <tag>    Install from a specific git tag when used with --github/--git-latest.
  --inspect-logs Also show resolved log paths (print-config) and tails of log files.
  --follow-logs  Keep following log files after install. Implies --inspect-logs.
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ORIGINAL_PATH="${PATH:-}"
MODE="auto"
GIT_TAG=""
INSPECT_LOGS=false
FOLLOW_LOGS=false

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --auto|-auto)
      MODE="auto"
      shift
      ;;
    --local|-local)
      MODE="local"
      shift
      ;;
    --github|-github|--git-latest|-git-latest)
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

export XDG_STATE_HOME="${CODEXDECK_XDG_STATE_HOME:-$HOME/.local/state}"
export PIPX_HOME="${CODEXDECK_PIPX_HOME:-$HOME/.local/share/pipx}"
export PIPX_BIN_DIR="${CODEXDECK_PIPX_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$XDG_STATE_HOME" "$PIPX_HOME" "$PIPX_BIN_DIR"
export PATH="$PIPX_BIN_DIR:$PATH"

if [ -x "${PIPX_BIN_DIR}/pipx" ]; then
  echo "Using existing pipx binary in $PIPX_BIN_DIR"
fi

install_from_local() {
  cd "$REPO_ROOT"
  rm -rf dist
  UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/uv-cache} uv build
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

resolve_in_path() {
  local binary="$1"
  local path_value="$2"
  local old_ifs="$IFS"
  local seen=":"
  local dir=""
  IFS=':'
  for dir in $path_value; do
    if [ -z "$dir" ]; then
      dir="."
    fi
    case "$seen" in
      *":$dir:"*) continue ;;
    esac
    seen="${seen}${dir}:"
    if [ -x "$dir/$binary" ]; then
      printf '%s\n' "$dir/$binary"
    fi
  done
  IFS="$old_ifs"
}

repair_temporary_pipx_shadow() {
  local candidate="$1"
  local pipx_entrypoint="$2"
  case "$candidate" in
    /tmp/pipx-bin/codexdeck)
      if [ -L "$candidate" ] || [ -w "$(dirname "$candidate")" ]; then
        ln -sfn "$pipx_entrypoint" "$candidate"
        echo "Repaired temporary PATH shadow: $candidate -> $pipx_entrypoint"
      fi
      ;;
  esac
}

diagnose_path_resolution() {
  local pipx_entrypoint="$1"
  local original_first=""
  local current_first=""
  local candidate=""
  local reached_pipx=false

  original_first="$(resolve_in_path codexdeck "$ORIGINAL_PATH" | head -n 1 || true)"
  current_first="$(command -v codexdeck || true)"

  echo "pipx-managed entrypoint: $pipx_entrypoint"
  if [ -x "$pipx_entrypoint" ]; then
    "$pipx_entrypoint" --version
  else
    echo "pipx-managed entrypoint not found."
  fi

  if [ -n "$current_first" ]; then
    echo "script-resolved entrypoint: $current_first"
    "$current_first" --version || true
  else
    echo "script-resolved entrypoint: not found in current PATH"
  fi

  if [ -n "$original_first" ]; then
    echo "caller-shell first entrypoint before script PATH fix: $original_first"
    "$original_first" --version || true
  else
    echo "caller-shell first entrypoint before script PATH fix: not found"
  fi

  while IFS= read -r candidate; do
    if [ "$candidate" = "$pipx_entrypoint" ]; then
      reached_pipx=true
      continue
    fi
    if [ "$reached_pipx" = false ]; then
      repair_temporary_pipx_shadow "$candidate" "$pipx_entrypoint"
      if [ -n "${VIRTUAL_ENV:-}" ] && [ "$candidate" = "$VIRTUAL_ENV/bin/codexdeck" ]; then
        echo "WARN: active virtualenv shadows pipx for this shell: $candidate"
        echo "      Run: deactivate && hash -r"
      else
        echo "WARN: PATH entry can shadow pipx in your caller shell: $candidate"
      fi
    fi
  done < <(resolve_in_path codexdeck "$ORIGINAL_PATH")

  if [ -n "${VIRTUAL_ENV:-}" ]; then
    echo "Active virtualenv: $VIRTUAL_ENV"
  fi

  echo
  echo "Reliable launch command:"
  echo "  $pipx_entrypoint"
  echo "If plain 'codexdeck' resolves to an older version after this script:"
  echo "  deactivate  # if a virtualenv is active"
  echo "  hash -r"
  echo "  export PATH=\"$PIPX_BIN_DIR:\$PATH\""
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
diagnose_path_resolution "$PIPX_BIN_CMD"

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
