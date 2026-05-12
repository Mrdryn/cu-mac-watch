#!/usr/bin/env python3
"""Scrape ComputerUniverse search pages for Mac Studio / Mac mini.

Compares against state.json — when a new SKU appears, posts a Telegram message.
Runs on GitHub Actions (residential-looking IP passes CF challenge).
"""
from __future__ import annotations
import json
import os
import re
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
STATE = Path("state.json")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TG_CHAT_ID", "")
ICON = {"mac-studio": "🖥", "mac-mini": "🍎"}


def extract_products(page) -> dict[str, dict]:
    """Return {product_id -> {title, price, url}}. Extracts via DOM heuristics.

    CU's search result cards have data-product-id and link to /de/<slug>.html ; the
    final numeric in the slug is the article number — we use that as a stable id.
    """
    # Strategy: collect all <a> elements that link to product pages, dedup by article id
    items = page.evaluate(
        """() => {
            const out = {};
            const anchors = document.querySelectorAll('a[href*="/de/"]');
            for (const a of anchors) {
                const href = a.getAttribute('href') || '';
                // Article pages typically look like /de/<slug>-<number>.html or /de/something/<id>
                const m = href.match(/\\/de\\/[a-zA-Z0-9-]+-(\\d{6,})\\.html/) ||
                          href.match(/\\/de\\/[a-zA-Z0-9-]+\\/(\\d{6,})/);
                if (!m) continue;
                const id = m[1];
                if (out[id]) continue;
                // Title — try aria-label, then visible text content
                let title = (a.getAttribute('aria-label') || a.textContent || '').trim();
                title = title.replace(/\\s+/g, ' ').slice(0, 200);
                if (!title) continue;
                // Skip obvious non-product anchors (categories, login, etc.)
                if (title.length < 8) continue;
                if (/^(login|kontakt|hilfe|service|warenkorb)/i.test(title)) continue;
                // Price — look at the closest card container for a € pattern
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
    return items


def scrape_url(page, url: str) -> dict[str, dict]:
    print(f"-> {url}", file=sys.stderr, flush=True)
    page.goto(url, timeout=90000, wait_until="domcontentloaded")
    # Wait up to 45s for CF challenge to clear
    try:
        page.wait_for_function(
            "!/Just a moment|Sichere Verbindung|Nur einen Moment/.test(document.title)",
            timeout=45000,
        )
    except Exception as e:
        print(f"WARN: CF wait timed out — title={page.title()!r}", file=sys.stderr)
    # Give product cards time to render
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    time.sleep(2)
    items = extract_products(page)
    print(f"   -> {len(items)} products", file=sys.stderr, flush=True)
    return items


def tg_send(text: str) -> None:
    if not (TG_TOKEN and TG_CHAT):
        print(f"(no telegram secrets, would send): {text[:200]}", file=sys.stderr)
        return
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={
                "chat_id": TG_CHAT,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": "false",
            },
            timeout=15,
        )
        if r.status_code != 200:
            print(f"tg http {r.status_code}: {r.text[:200]}", file=sys.stderr)
    except Exception as e:
        print(f"tg send err: {e}", file=sys.stderr)


def main() -> int:
    seen = json.loads(STATE.read_text()) if STATE.exists() else {}
    initial = not seen  # first run: don't spam, just baseline
    current: dict[str, dict[str, dict]] = {}

    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            locale="de-DE",
            timezone_id="Europe/Berlin",
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

    # Guard: if we got zero products on BOTH kinds — something's broken, don't overwrite state.
    total = sum(len(v) for v in current.values())
    if total == 0 and not initial:
        print("ERR: zero products extracted on both URLs — skipping state update", file=sys.stderr)
        return 2

    # Diff + notify
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
            tg_send(msg)
            print(f"NEW {kind}: id={pid} title={p_['title'][:80]!r}", flush=True)

    # Save state
    STATE.write_text(json.dumps(current, ensure_ascii=False, indent=2))
    print(
        f"summary: kinds={list(current.keys())} sizes={ {k: len(v) for k, v in current.items()} } "
        f"new={new_count} initial={initial}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
