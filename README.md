# cu-mac-watch

Polls [computeruniverse.net](https://www.computeruniverse.net) search results for **Mac Studio** and **Mac mini** every 5 minutes (GitHub Actions cron). When a new product ID appears, sends a Telegram message with title, price, and link.

Why GitHub Actions? CU is behind Cloudflare bot management — datacenter IPs (incl. most VPSes) are challenged. GitHub-hosted runners use Azure residential-ish IPs that pass the challenge, and the free tier on public repos is unmetered.

## Secrets

- `TELEGRAM_BOT_TOKEN` — bot to send notifications from
- `TG_CHAT_ID` — chat to send to

## State

`state.json` is committed back after each run. First run = baseline (no notifications), subsequent runs notify on diff. If extraction returns zero products on both URLs, state is not overwritten (guards against transient CF blocks).
