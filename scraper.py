import asyncio
import os
import re
import subprocess
import sys
from datetime import datetime
from playwright.async_api import async_playwright
import json
import streamlit as st

WATCHLISTS = {
                "Financial Services": "https://monitor.distill.io/#/w/8a348b54-3cd7-4c25-bd77-6a428257a05d/list/error/",
                "Gambling Compliance": "https://monitor.distill.io/#/w/1abfcc1f-96b7-4cb0-aaa6-b9b7cf15ed7c/list/error/",
                "Payments Compliance": "https://monitor.distill.io/#/w/0068e396-3cbc-4d11-83d0-52afac26b560/list/error/",
}


def _ensure_browser():
                """Always run playwright install chromium - it is idempotent and fast if already installed."""
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    check=False,
                    capture_output=True,
                )


def classify_error(snippet: str) -> tuple:
                s = snippet.strip()
                if "Preview will be available soon after this task is run" in s:
                                    return ("Monitor Not Yet Run", "This monitor hasn't completed its first check yet. It will resolve automatically once Distill runs it.", False)
                                if re.search(r"ERR_NAME_NOT_RESOLVED|ERR_CONNECTION_REFUSED|ERR_TUNNEL_CONNECTION_FAILED", s):
                                                    return ("DNS / Connection Error", "Distill cannot reach the website - the domain may be down, renamed or blocked.", True)
                                                if re.search(r"ERR_SSL|SSL_ERROR|certificate", s, re.I):
                                                                    return ("SSL Certificate Error", "The website's SSL certificate is invalid or expired. The site owner needs to renew it.", True)
                                                                if re.search(r"403|Forbidden|Access Denied|unauthorized", s, re.I):
                                                                                    return ("Access Denied (403)", "Distill is being blocked from accessing this page - it may require a login or has blocked automated requests.", True)
                                                                                if re.search(r"404|Not Found|Page not found", s, re.I):
                                                                                                    return ("Page Not Found (404)", "The monitored URL no longer exists. Update the monitor URL to the new location.", True)
                                                                                                if re.search(r"50[0-9]|Internal Server Error|Bad Gateway|Service Unavailable|timeout", s, re.I):
                                                                                                                    return ("Server Error / Timeout", "The target website returned a server error or timed out. Usually temporary - if it persists the source may be down.", False)
                                                                                                                if re.search(r"No existen registros|Bient\u00f4t disponible|not available|coming soon", s, re.I):
                                                                                                                                    return ("No Content / Coming Soon", "The page currently shows no content or a placeholder. Will self-resolve when content is published.", False)
                                                                                                                                if len(s) > 30:
                                                                                                                                                    return ("Content Change Detected", "Distill detected a change on this page. Review the snippet to confirm if it's a new regulatory update.", True)
                                                                                                                                                return ("Unknown / Empty Response", "Distill received an empty or unrecognisable response. Check whether the source URL is still valid.", True)


async def _scrape_one(browser, name: str, url: str, session_state: dict) -> list:
                context = await browser.new_context(storage_state=session_state)
    page = await context.new_page()
    rows_data = []
    try:
                        await page.goto(url, wait_until="networkidle", timeout=60000)
                        await page.wait_for_selector(".xitem.xfade", timeout=30000)

        prev_count = 0
        for _ in range(80):
                                count = await page.eval_on_selector_all(".xitem.xfade", "els => els.length")
                                if count == prev_count:
                                                            break
                                                        prev_count = count
            await page.evaluate("""() => {
                            const list = document.querySelector('.flex-1.flex.flex-column.gap-2.items-stretch');
                                            if (list) list.scrollTop += 2000;
                                                            else window.scrollBy(0, 2000);
                                                                        }""")
            await asyncio.sleep(0.4)

        rows_data = await page.eval_on_selector_all(".xitem.xfade", """els => els.map(row => {
                    const tds = row.querySelectorAll('td');
                                if (tds.length < 6) return null;
                                            const titleTd = tds[2];
                                                        const snippetTd = tds[3];
                                                                    const freqTd = tds[4];
                                                                                const dateTd = tds[5];
                                                                                            const statusTd = tds[7];
                                                                                                        const titleLink = titleTd ? titleTd.querySelector('a') : null;
                                                                                                                    const title = titleLink ? titleLink.innerText.trim() : '';
                                                                                                                                const tagEl = snippetTd ? snippetTd.querySelector('.badge') : null;
                                                                                                                                            const tag = tagEl ? tagEl.innerText.trim() : '';
                                                                                                                                                        const fullSnippet = snippetTd ? snippetTd.innerText.trim().replace(tag, '').trim() : '';
                                                                                                                                                                    return {
                                                                                                                                                                                    title: title.substring(0, 120),
                                                                                                                                                                                                    jurisdiction: tag,
                                                                                                                                                                                                                    snippet: fullSnippet.substring(0, 400),
                                                                                                                                                                                                                                    freq: freqTd ? freqTd.innerText.trim() : '',
                                                                                                                                                                                                                                                    last_checked: dateTd ? dateTd.innerText.trim() : '',
                                                                                                                                                                                                                                                                    monitor_status: statusTd ? statusTd.innerText.trim() : '',
                                                                                                                                                                                                                                                                                };
                                                                                                                                                                                                                                                                                        }).filter(Boolean)""")

except Exception as exc:
        print(f"[scraper] Error scraping {name}: {exc}")
finally:
        await context.close()

    enriched = []
    for r in rows_data:
                        etype, explanation, fixable = classify_error(r["snippet"])
        enriched.append({
                                **r,
                                "area": name,
                                "error_type": etype,
                                "explanation": explanation,
                                "fixable": fixable,
                                "scraped_at": datetime.utcnow().isoformat(timespec="seconds"),
        })
    return enriched


async def scrape_all_errors(session_state: dict) -> list:
                _ensure_browser()
    async with async_playwright() as pw:
                        browser = await pw.chromium.launch(
                                                headless=True,
                                                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
                        )
        tasks = [_scrape_one(browser, name, url, session_state) for name, url in WATCHLISTS.items()]
        results = await asyncio.gather(*tasks)
        await browser.close()
    combined = []
    for r in results:
                        combined.extend(r)
    return combined


def run_scrape() -> list:
                session_json = st.secrets["distill"]["session"]
    session_state = json.loads(session_json)

    # Streamlit runs its own event loop; we must create a fresh loop in a
    # background thread to avoid "This event loop is already running" errors.
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(asyncio.run, scrape_all_errors(session_state))
        return future.result(timeout=300)
        return future.result(timeout=300)
