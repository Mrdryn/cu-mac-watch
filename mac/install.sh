#!/bin/bash
# CU Mac Watch — installer for macOS.
# Usage:
#   cd ~/cu-mac-watch
#   ./mac/install.sh
#
# Asks for Telegram bot token + chat id, installs Python deps + chromium,
# registers launchd job that scrapes every 5 min.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CFG_DIR="$HOME/.config/cu-mac-watch"
ENV_FILE="$CFG_DIR/env"
PLIST="$HOME/Library/LaunchAgents/com.cu-mac-watch.plist"
PY="$(command -v python3 || true)"

if [ -z "$PY" ]; then
  echo "❌ python3 not found. Install from python.org or 'brew install python'." >&2
  exit 1
fi
echo "✓ Python: $PY ($($PY --version))"

mkdir -p "$CFG_DIR" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

# 1. Prompt for secrets if env file doesn't exist
if [ ! -f "$ENV_FILE" ]; then
  echo
  echo "→ Setting up Telegram notifications"
  read -p "  TELEGRAM_BOT_TOKEN (from BotFather): " tg_token
  read -p "  TG_CHAT_ID (your numeric Telegram user id): " tg_chat
  cat > "$ENV_FILE" <<EOF
TELEGRAM_BOT_TOKEN=$tg_token
TG_CHAT_ID=$tg_chat
EOF
  chmod 600 "$ENV_FILE"
  echo "  wrote $ENV_FILE"
else
  echo "✓ Found existing $ENV_FILE — keeping"
fi

# 2. Python deps
echo
echo "→ Installing Python deps (playwright, playwright-stealth, httpx)"
"$PY" -m pip install --user --quiet --upgrade pip
"$PY" -m pip install --user --quiet playwright==1.48.0 playwright-stealth==2.0.0 httpx==0.27.2

# 3. Chromium for playwright
if [ ! -d "$HOME/Library/Caches/ms-playwright" ]; then
  echo "→ Installing playwright chromium (one-time, ~170MB)"
  "$PY" -m playwright install chromium
else
  echo "✓ playwright cache exists, skipping chromium install (run 'playwright install chromium' manually to refresh)"
fi

# 4. Render launchd plist
echo "→ Writing $PLIST"
sed -e "s|__PYTHON__|$PY|g" \
    -e "s|__REPO__|$REPO|g" \
    -e "s|__HOME__|$HOME|g" \
    "$REPO/mac/com.cu-mac-watch.plist" > "$PLIST"

# 5. Unload previous (if any), then load
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load -w "$PLIST"
echo "✓ launchd registered"

# 6. Smoke test — run once now (with env vars), confirm telegram works
echo
echo "→ Smoke test: running once (~30 sec)"
set -a
. "$ENV_FILE"
set +a
if "$PY" "$REPO/mac/scrape.py"; then
  echo "✓ smoke test passed"
else
  echo "⚠ smoke test exited non-zero — check $HOME/Library/Logs/cu-mac-watch.log"
fi

echo
echo "Готово. Скрипт будет крутиться каждые 5 минут."
echo "  логи:        tail -f ~/Library/Logs/cu-mac-watch.log"
echo "  uninstall:   ~/cu-mac-watch/mac/uninstall.sh"
echo "  run сейчас:  launchctl kickstart -k gui/\$(id -u)/com.cu-mac-watch"
