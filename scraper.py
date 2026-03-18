import asyncio
import re
from datetime import datetime
from playwright.async_api import async_playwright

WATCHLISTS = {
    "Financial Services": "https://monitor.distill.io/#/w/8a348b54-3cd7-4c25-bd77-6a428257a05d/list/error/",
    "Gambling Compliance": "https://monitor.distill.io/#/w/1abfcc1f-96b7-4cb0-aaa6-b9b7cf15ed7c/list/error/",
    "Payments Compliance": "https://monitor.distill.io/#/w/0068e396-3cbc-4d11-83d0-52afac26b560/list/error/",
}

# ── Error classification ──────────────────────────────────────────────────────

def classify_error(snippet: str) -> tuple[str, str, bool]:
    """
    Returns (error_type_label, plain_english_explanation, is_fixable)
    """
    s = snippet.strip()

    if "Preview will be available soon after this task is run" in s:
        return (
            "Monitor Not Yet Run",
            "This monitor was recently added or reset and hasn't completed its first check yet. "
            "It will resolve automatically once Distill runs it.",
            False,  # self-resolving
        )
    if re.search(r"ERR_NAME_NOT_RESOLVED|ERR_CONNECTION_REFUSED|ERR_TUNNEL_CONNECTION_FAILED", s):
        return (
            "DNS / Connection Error",
            "Distill cannot reach the website — the domain may be down, renamed or blocked.",
            True,
        )
    if re.search(r"ERR_SSL|SSL_ERROR|certificate", s, re.I):
        return (
            "SSL Certificate Error",
            "The website's SSL certificate is invalid or expired. The site owner needs to renew it.",
            True,
        )
    if re.search(r"403|Forbidden|Access Denied|unauthorized", s, re.I):
        return (
            "Access Denied (403)",
            "Distill is being blocked from accessing the page — the site may require a login "
            "or has blocked automated requests.",
            True,
        )
    if re.search(r"404|Not Found|Page not found", s, re.I):
        return (
            "Page Not Found (404)",
            "The monitored URL no longer exists. The page may have moved or been deleted. "
            "Update the monitor URL to the new location.",
            True,
        )
    if re.search(r"50[0-9]|Internal Server Error|Bad Gateway|Service Unavailable|timeout", s, re.I):
        return (
            "Server Error / Timeout",
            "The target website returned a server error or timed out. This is usually temporary — "
            "if it persists for more than a day the source website may be down.",
            False,
        )
    if re.search(r"No existen registros|Bientôt disponible|not available|coming soon", s, re.I):
        return (
            "No Content / Coming Soon",
            "The page currently shows no content or a 'coming soon' placeholder. "
            "The monitor will self-resolve when the page publishes content.",
            False,
        )
    if len(s) > 30:
        return (
            "Content Change Detected",
            "Distill detected a change on this page since the last check. "
            "Review the snippet to confirm whether it represents a new regulatory update.",
            True,
        )
    return (
        "Unknown / Empty Response",
        "Distill received an empty or unrecognisable response from the page. "
        "Check whether the source URL is still valid.",
        True,
    )


# ── Playwright scraper ────────────────────────────────────────────────────────

async def _scrape_one(browser, name: str, url: str) -> list[dict]:
    """Open one watchlist error page, scroll to load all rows, extract data."""
    context = await browser.new_context(
        storage_state=None,  # Uses the default profile with cookies already set
    )
    page = await context.new_page()

    rows_data = []
    try:
        await page.goto(url, wait_until="networkidle", timeout=60_000)
        # Wait for the item list to appear
        await page.wait_for_selector(".xitem.xfade", timeout=30_000)

        # Scroll the virtual list to load all rows
        prev_count = 0
        for _ in range(80):  # max 80 scroll steps
            count = await page.eval_on_selector_all(".xitem.xfade", "els => els.length")
            if count == prev_count:
                break
            prev_count = count
            await page.evaluate(
                """() => {
                    const list = document.querySelector('.flex-1.flex.flex-column.gap-2.items-stretch');
                    if (list) list.scrollTop += 2000;
                    else window.scrollBy(0, 2000);
                }"""
            )
            await asyncio.sleep(0.4)

        # Extract all rows
        rows_data = await page.eval_on_selector_all(
            ".xitem.xfade",
            """els => els.map(row => {
                const tds = row.querySelectorAll('td');
                if (tds.length < 6) return null;

                const titleTd   = tds[2];
                const snippetTd = tds[3];
                const freqTd    = tds[4];
                const dateTd    = tds[5];
                const statusTd  = tds[7];

                const titleLink = titleTd ? titleTd.querySelector('a') : null;
                const title     = titleLink ? titleLink.innerText.trim() : '';
                const sourceUrl = titleLink ? (titleLink.getAttribute('href') || '') : '';

                const tagEl = snippetTd ? snippetTd.querySelector('.badge') : null;
                const tag   = tagEl ? tagEl.innerText.trim() : '';

                const fullSnippet = snippetTd
                    ? snippetTd.innerText.trim().replace(tag, '').trim()
                    : '';

                return {
                    title:         title.substring(0, 120),
                    jurisdiction:  tag,
                    source_url:    sourceUrl.substring(0, 200),
                    snippet:       fullSnippet.substring(0, 400),
                    freq:          freqTd    ? freqTd.innerText.trim()    : '',
                    last_checked:  dateTd    ? dateTd.innerText.trim()    : '',
                    monitor_status: statusTd ? statusTd.innerText.trim()  : '',
                };
            }).filter(Boolean)"""
        )

    except Exception as exc:
        print(f"[scraper] Error scraping {name}: {exc}")
    finally:
        await context.close()

    # Enrich with Python-side classification
    enriched = []
    for r in rows_data:
        etype, explanation, fixable = classify_error(r["snippet"])
        enriched.append(
            {
                **r,
                "area": name,
                "error_type": etype,
                "explanation": explanation,
                "fixable": fixable,
                "scraped_at": datetime.utcnow().isoformat(timespec="seconds"),
            }
        )
    return enriched


async def scrape_all_errors(chromium_user_data_dir: str | None = None) -> list[dict]:
    """Scrape all three watchlists concurrently and return combined list."""
    async with async_playwright() as pw:
        # Launch with persistent context so existing Distill login cookies are used
        if chromium_user_data_dir:
            browser = await pw.chromium.launch_persistent_context(
                chromium_user_data_dir,
                headless=True,
                args=["--no-sandbox"],
            )
            tasks = [
                _scrape_one_persistent(browser, name, url)
                for name, url in WATCHLISTS.items()
            ]
            results = await asyncio.gather(*tasks)
            await browser.close()
        else:
            browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
            tasks = [
                _scrape_one(browser, name, url)
                for name, url in WATCHLISTS.items()
            ]
            results = await asyncio.gather(*tasks)
            await browser.close()

    combined = []
    for r in results:
        combined.extend(r)
    return combined


async def _scrape_one_persistent(context, name: str, url: str) -> list[dict]:
    """Variant that works with a persistent browser context (shared cookies)."""
    page = await context.new_page()
    rows_data = []
    try:
        await page.goto(url, wait_until="networkidle", timeout=60_000)
        await page.wait_for_selector(".xitem.xfade", timeout=30_000)

        prev_count = 0
        for _ in range(80):
            count = await page.eval_on_selector_all(".xitem.xfade", "els => els.length")
            if count == prev_count:
                break
            prev_count = count
            await page.evaluate(
                """() => {
                    const list = document.querySelector('.flex-1.flex.flex-column.gap-2.items-stretch');
                    if (list) list.scrollTop += 2000;
                    else window.scrollBy(0, 2000);
                }"""
            )
            await asyncio.sleep(0.4)

        rows_data = await page.eval_on_selector_all(
            ".xitem.xfade",
            """els => els.map(row => {
                const tds = row.querySelectorAll('td');
                if (tds.length < 6) return null;
                const titleTd   = tds[2];
                const snippetTd = tds[3];
                const freqTd    = tds[4];
                const dateTd    = tds[5];
                const statusTd  = tds[7];
                const titleLink = titleTd ? titleTd.querySelector('a') : null;
                const title     = titleLink ? titleLink.innerText.trim() : '';
                const sourceUrl = titleLink ? (titleLink.getAttribute('href') || '') : '';
                const tagEl     = snippetTd ? snippetTd.querySelector('.badge') : null;
                const tag       = tagEl ? tagEl.innerText.trim() : '';
                const fullSnippet = snippetTd
                    ? snippetTd.innerText.trim().replace(tag, '').trim() : '';
                return {
                    title: title.substring(0, 120),
                    jurisdiction: tag,
                    source_url: sourceUrl.substring(0, 200),
                    snippet: fullSnippet.substring(0, 400),
                    freq: freqTd    ? freqTd.innerText.trim()    : '',
                    last_checked:  dateTd    ? dateTd.innerText.trim()    : '',
                    monitor_status: statusTd ? statusTd.innerText.trim()  : '',
                };
            }).filter(Boolean)"""
        )
    except Exception as exc:
        print(f"[scraper] Error scraping {name}: {exc}")
    finally:
        await page.close()

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


def run_scrape(user_data_dir: str | None = None) -> list[dict]:
    """Synchronous wrapper — call this from Streamlit."""
    return asyncio.run(scrape_all_errors(user_data_dir))
