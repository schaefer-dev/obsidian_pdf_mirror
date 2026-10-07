#!/bin/bash
# Installs dependencies and the launchd agent that runs mirror.py periodically.
# Idempotent: re-run after moving the project or changing the interval.
#   INTERVAL=1800 ./install.sh   # run every 30 min instead of hourly
set -euo pipefail

cd "$(dirname "$0")"
PROJECT="$(pwd)"
LABEL="local.obsidian-pdf-mirror"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
INTERVAL="${INTERVAL:-3600}"
BIN_DIR="$HOME/.local/bin"

command -v brew >/dev/null || { echo "Homebrew is required: https://brew.sh" >&2; exit 1; }
brew bundle install --no-upgrade --file Brewfile
command -v uv >/dev/null || brew install uv
UV="$(command -v uv)"

BREW_PREFIX="$(brew --prefix)"
PATH_FOR_AGENT="$BREW_PREFIX/bin:$(dirname "$UV"):/usr/local/bin:/usr/bin:/bin"

mkdir -p .state "$HOME/Library/LaunchAgents"
sed -e "s|__LABEL__|$LABEL|g" \
    -e "s|__UV__|$UV|g" \
    -e "s|__PROJECT__|$PROJECT|g" \
    -e "s|__PATH__|$PATH_FOR_AGENT|g" \
    -e "s|__INTERVAL__|$INTERVAL|g" \
    launchd/mirror.plist.template > "$PLIST"
plutil -lint "$PLIST" >/dev/null

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

mkdir -p "$BIN_DIR"
ln -sf "$PROJECT/bin/obsidian-sync" "$BIN_DIR/obsidian-sync"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "Note: add $BIN_DIR to your PATH to use the obsidian-sync command." ;;
esac

echo "Installed $LABEL (every ${INTERVAL}s). It runs once now; log: $PROJECT/.state/mirror.log"
echo "Sync on demand:   obsidian-sync"
