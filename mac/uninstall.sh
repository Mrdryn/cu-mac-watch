#!/bin/bash
set -euo pipefail
PLIST="$HOME/Library/LaunchAgents/com.cu-mac-watch.plist"
if [ -f "$PLIST" ]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm "$PLIST"
  echo "✓ unloaded + removed $PLIST"
else
  echo "no plist found"
fi
echo "(env, state, logs intact in ~/.config/cu-mac-watch/, ~/Library/Logs/)"
