#!/usr/bin/env python3
"""CU Mac Studio/Mini watcher — runs locally on macOS via launchd (every 5 min).

Reads creds from ~/.config/cu-mac-watch/env (TELEGRAM_BOT_TOKEN, TG_CHAT_ID).
Stores last-seen products in ~/.config/cu-mac-watch/state.json.
Logs to ~/Library/Logs/cu-mac-watch.log.
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

URLS = {
    "mac-studio": "https://www.computeruniverse.net/de/search?query=mac%20studio",
    "mac-mini": "https://www.computeruniverse.net/de/search?query=mac%20mini",
}
CFG = Path.home() / ".config" / "cu-mac-watch"
ENV_FILE = CFG / "env"
STATE = CFG / "state.json"
ICON = {"mac-studio": "🖥", "mac-mini": "🍎"}


def load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("TELEGRAM_BOT_TOKEN", "TG_CHAT_ID"):
        if k in os.environ:
            out[k] = os.environ[k]
    return out


def extract_products(page) -> dict[str, dict]:
    return page.evaluate(
        """() => {
            const out = {};
            const anchors = document.querySelectorAll('a[href*="/de/"]');
            for (const a of anchors) {
                const href = a.getAttribute('href') || '';
                const m = href.match(/\\/de\\/[a-zA-Z0-9-]+-(\\d{6,})\\.html/)
                       || href.match(/\\/de\\/[a-zA-Z0-9-]+\\/(\\d{6,})/);
                if (!m) continue;
                const id = m[1];
                if (out[id]) continue;
                let title = (a.getAttribute('aria-label') || a.textContent || '').trim();
                title = title.replace(/\\s+/g, ' ').slice(0, 200);
                if (!title || title.length < 8) continue;
                if (/^(login|kontakt|hilfe|service|warenkorb|menu|filter|sortier)/i.test(title)) continue;
                const card = a.closest('[class*="product"], [class*="card"], li, article, div');
                let price = '';
                if (card) {
                    const m2 = card.textContent.match(/(\\d{1,3}(?:[.,]\\d{3})*(?:[.,]\\d{2})?)\\s*€/);
                    if (m2) price = m2[1].trim() + ' €';
                }
                const fullUrl = href.startsWith('http') ? href : ('https://www.computeruniverse.net' + href);
                out[id] = {title, price, url: fullUrl};
            }
            return out;
        }"""
    )


def scrape_url(page, url: str) -> dict[str, dict]:
    print(f"-> {url}", file=sys.stderr, flush=True)
    page.goto(url, timeout=90000, wait_until="domcontentloaded")
    try:
        page.wait_for_function(
            "!/Just a moment|Sichere Verbindung|Nur einen Moment/.test(document.title)",
            timeout=45000,
        )
    except Exception:
        print(f"WARN: CF wait timed out title={page.title()!r}", file=sys.stderr)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    time.sleep(2)
    items = extract_products(page)
    print(f"   title={page.title()!r}  -> {len(items)} products", file=sys.stderr, flush=True)
    return items


def tg_send(token: str, chat_id: str, text: str) -> None:
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={
                "chat_id": chat_id, "text": text,
                "parse_mode": "HTML", "disable_web_page_preview": "false",
            },
            timeout=15,
        )
        if r.status_code != 200:
            print(f"tg http {r.status_code}: {r.text[:200]}", file=sys.stderr)
    except Exception as e:
        print(f"tg send err: {e}", file=sys.stderr)


def main() -> int:
    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat = env.get("TG_CHAT_ID", "")
    if not (token and chat):
        print(f"ERR: TELEGRAM_BOT_TOKEN / TG_CHAT_ID not in {ENV_FILE} or environ", file=sys.stderr)
        return 1

    CFG.mkdir(parents=True, exist_ok=True)
    seen = json.loads(STATE.read_text()) if STATE.exists() else {}
    initial = not seen

    current: dict[str, dict[str, dict]] = {}
    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            locale="de-DE", timezone_id="Europe/Berlin",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 "
                "(KHTML, like Gecko) Version/16.6 Safari/605.1.15"
            ),
            viewport={"width": 1366, "height": 900},
        )
        page = ctx.new_page()
        for kind, url in URLS.items():
            try:
                current[kind] = scrape_url(page, url)
            except Exception as e:
                print(f"ERR {kind}: {e}", file=sys.stderr)
                current[kind] = seen.get(kind, {})
        browser.close()

    total = sum(len(v) for v in current.values())
    if total == 0 and not initial:
        print("ERR: zero products on both URLs — keeping previous state", file=sys.stderr)
        return 2

    new_count = 0
    for kind, items in current.items():
        old_ids = set(seen.get(kind, {}).keys())
        new_ids = set(items.keys()) - old_ids
        for pid in sorted(new_ids):
            p_ = items[pid]
            new_count += 1
            if initial:
                continue
            msg = (
                f"{ICON.get(kind, '🆕')} <b>Новая конфигурация на CU ({kind})</b>\n\n"
                f"{p_['title']}\n"
                f"💰 {p_['price'] or 'цены нет'}\n\n"
                f'<a href="{p_["url"]}">Открыть на ComputerUniverse</a>'
            )
            tg_send(token, chat, msg)
            print(f"NEW {kind}: id={pid} title={p_['title'][:80]!r}", flush=True)

    STATE.write_text(json.dumps(current, ensure_ascii=False, indent=2))
    print(
        f"summary: sizes={ {k: len(v) for k, v in current.items()} } new={new_count} initial={initial}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
