# cu-mac-watch

Watcher for Mac Studio / Mac mini listings on [computeruniverse.net](https://www.computeruniverse.net). Polls search pages every 5 min; sends Telegram message when a new SKU appears.

## Why local (Mac) instead of GitHub Actions

ComputerUniverse uses Cloudflare bot management. It hard-blocks (HTTP 403, "Attention Required") all datacenter IP ranges, including GitHub-hosted runners and major proxy providers' datacenter pools. Only **residential IPs** pass — and your Mac's home internet is residential, free, and already running.

## Install on macOS

```bash
git clone https://github.com/Mrdryn/cu-mac-watch.git ~/cu-mac-watch
cd ~/cu-mac-watch
./mac/install.sh
```

The installer:
1. Prompts for `TELEGRAM_BOT_TOKEN` + `TG_CHAT_ID` (stored in `~/.config/cu-mac-watch/env`, 600 perms)
2. Installs Python deps (`playwright`, `playwright-stealth`, `httpx`)
3. Downloads Playwright Chromium (~170 MB, one-time)
4. Writes `~/Library/LaunchAgents/com.cu-mac-watch.plist` and `launchctl load`s it
5. Runs once to confirm everything works (baseline state — no notifications on the first run)

After that, launchd fires `scrape.py` every 5 minutes whenever the Mac is awake.

## Files

- `mac/scrape.py` — Playwright scraper with stealth, diffs against `state.json`, posts to Telegram on new SKUs
- `mac/com.cu-mac-watch.plist` — launchd template (`__PYTHON__`/`__REPO__`/`__HOME__` substituted at install time)
- `mac/install.sh` / `mac/uninstall.sh`

## Logs / debug

```bash
tail -f ~/Library/Logs/cu-mac-watch.log
launchctl kickstart -k gui/$(id -u)/com.cu-mac-watch    # run immediately
launchctl list | grep cu-mac-watch                       # status
```

## How state works

`~/.config/cu-mac-watch/state.json` — last seen `{kind: {sku: {title, price, url}}}`. First run = baseline (no alerts). Subsequent runs alert only on SKUs that weren't there before. If extraction returns zero products on both URLs (transient CF block), state is not overwritten.
