#!/bin/bash
# Stops and removes the launchd agent. Leaves the PDFs, state and dependencies alone.
set -euo pipefail

LABEL="local.obsidian-pdf-mirror"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
[ -L "$HOME/.local/bin/obsidian-sync" ] && rm -f "$HOME/.local/bin/obsidian-sync"
echo "Removed $LABEL"
