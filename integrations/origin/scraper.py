"""
Origin Financial Scraper — authenticated data extractor.

Uses Playwright (headless Chromium) to log into app.useorigin.com and extract:
- Budget (spent vs target, by category)
- Net worth (total, assets, liabilities)
- Investments (portfolio value, allocation)
- Credit score
- Recent transactions
- Equity / RSU data

Snapshot is saved to data/origin_snapshot.json and consumed by finance_agent
and investment_agent as ground-truth context.

Env vars required:
  ORIGIN_EMAIL    — Origin Financial account email
  ORIGIN_PASSWORD — Origin Financial account password
"""

import os
import json
import asyncio
import logging
import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

LOGIN_URL       = "https://app.useorigin.com/login"
DASHBOARD_URL   = "https://app.useorigin.com/"
SPENDING_URL    = "https://app.useorigin.com/spending/overview"
INVEST_URL      = "https://app.useorigin.com/invest/overview"
EQUITY_URL      = "https://app.useorigin.com/equity"
FORECAST_URL    = "https://app.useorigin.com/forecast"

DATA_DIR        = Path(__file__).parent.parent.parent / "data"
SNAPSHOT_FILE   = DATA_DIR / "origin_snapshot.json"
COOKIES_FILE    = DATA_DIR / "origin_cookies.json"


def is_configured() -> bool:
    return bool(os.getenv("ORIGIN_EMAIL") and os.getenv("ORIGIN_PASSWORD"))


def load_snapshot() -> dict:
    """Load the last saved Origin snapshot. Returns empty dict if not yet scraped."""
    DATA_DIR.mkdir(exist_ok=True)
    if not SNAPSHOT_FILE.exists():
        return {}
    try:
        return json.loads(SNAPSHOT_FILE.read_text())
    except Exception:
        return {}


def save_snapshot(data: dict):
    DATA_DIR.mkdir(exist_ok=True)
    data["_scraped_at"] = datetime.datetime.now().isoformat()
    SNAPSHOT_FILE.write_text(json.dumps(data, indent=2))


def snapshot_age_hours() -> Optional[float]:
    """Return how many hours old the snapshot is, or None if it doesn't exist."""
    snap = load_snapshot()
    ts = snap.get("_scraped_at")
    if not ts:
        return None
    try:
        scraped = datetime.datetime.fromisoformat(ts)
        delta = datetime.datetime.now() - scraped
        return delta.total_seconds() / 3600
    except Exception:
        return None


def save_cookies(cookies: list) -> None:
    """Persist browser cookies to disk for reuse across scrape sessions."""
    DATA_DIR.mkdir(exist_ok=True)
    COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
    logger.info("Origin: %d cookies saved to %s", len(cookies), COOKIES_FILE)


def load_cookies() -> list:
    """Load saved cookies. Returns empty list if not found."""
    if not COOKIES_FILE.exists():
        return []
    try:
        return json.loads(COOKIES_FILE.read_text())
    except Exception:
        return []


def cookies_exist() -> bool:
    return COOKIES_FILE.exists() and bool(load_cookies())


def _is_login_page(text: str) -> bool:
    """Return True if the page text looks like the Origin login page."""
    markers = ["sign in", "sign up", "forgot your password", "sso through employer",
               "don't have an account"]
    text_lower = text.lower()
    return sum(1 for m in markers if m in text_lower) >= 2


async def _scrape_async() -> dict:
    """Login to Origin Financial and extract financial data using headless Chromium."""
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout

    email    = os.getenv("ORIGIN_EMAIL", "")
    password = os.getenv("ORIGIN_PASSWORD", "")

    snapshot = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--window-size=1440,900"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        page = await context.new_page()

        try:
            # ── Login ──────────────────────────────────────────────────────────
            logger.info("Origin: navigating to login page")
            await page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            # Fill email — Origin uses name="username"
            email_input = page.locator("input[name='username']")
            await email_input.wait_for(state="visible", timeout=10000)
            await email_input.click()
            await email_input.fill(email)
            await page.wait_for_timeout(600)

            # Fill password — Origin uses name="current-password"
            password_input = page.locator("input[name='current-password']")
            await password_input.wait_for(state="visible", timeout=10000)
            await password_input.click()
            await password_input.fill(password)
            await page.wait_for_timeout(600)

            # Click the submit button — type="submit" text="Sign in"
            sign_in_btn = page.locator("button[type='submit']").first
            await sign_in_btn.click()

            # Wait for React app to finish auth redirect — poll URL manually
            await page.wait_for_timeout(5000)
            for _ in range(10):
                current = page.url
                if "useorigin.com" in current and "login" not in current:
                    break
                await page.wait_for_timeout(1500)
            else:
                logger.warning("Origin: still on login URL after waiting")

            current_url = page.url
            logger.info("Origin: post-login URL: %s", current_url)

            # Verify we actually got past the login page
            page_text = await page.evaluate("() => document.body.innerText")
            if _is_login_page(page_text):
                snapshot["error"] = "Login failed — still on login page after submit"
                logger.error("Origin: still on login page after login attempt")
                await browser.close()
                return snapshot

            # ── Dashboard — net worth + budget + credit score ──────────────────
            logger.info("Origin: fetching dashboard")
            await page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(4000)

            dashboard_text = await page.evaluate("() => document.body.innerText")
            snapshot["dashboard_text"] = dashboard_text[:4000]
            logger.info("Origin: dashboard captured (%d chars)", len(dashboard_text))

            # ── Spending overview ──────────────────────────────────────────────
            logger.info("Origin: fetching spending overview")
            await page.goto(SPENDING_URL, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(4000)

            spending_text = await page.evaluate("() => document.body.innerText")
            snapshot["spending_text"] = spending_text[:5000]
            logger.info("Origin: spending captured (%d chars)", len(spending_text))

            # ── Investment overview ────────────────────────────────────────────
            logger.info("Origin: fetching investment overview")
            await page.goto(INVEST_URL, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(4000)

            invest_text = await page.evaluate("() => document.body.innerText")
            snapshot["investments_text"] = invest_text[:5000]
            logger.info("Origin: investments captured (%d chars)", len(invest_text))

            # ── Equity / RSU ───────────────────────────────────────────────────
            logger.info("Origin: fetching equity overview")
            await page.goto(EQUITY_URL, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)

            equity_text = await page.evaluate("() => document.body.innerText")
            snapshot["equity_text"] = equity_text[:4000]
            logger.info("Origin: equity captured (%d chars)", len(equity_text))

            # ── Forecast ───────────────────────────────────────────────────────
            logger.info("Origin: fetching forecast")
            await page.goto(FORECAST_URL, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)

            forecast_text = await page.evaluate("() => document.body.innerText")
            snapshot["forecast_text"] = forecast_text[:4000]
            logger.info("Origin: forecast captured (%d chars)", len(forecast_text))

            logger.info("Origin: scrape complete")

        except Exception as e:
            logger.error(f"Origin scrape error: {e}")
            snapshot["error"] = str(e)
        finally:
            await browser.close()

    return snapshot


def scrape() -> dict:
    """Headless login scrape. Unreliable due to bot detection — use scrape_with_cookies() instead."""
    if not is_configured():
        logger.warning("Origin: ORIGIN_EMAIL / ORIGIN_PASSWORD not set — skipping scrape")
        return {}

    try:
        snapshot = asyncio.run(_scrape_async())
        if snapshot and "error" not in snapshot:
            save_snapshot(snapshot)
            logger.info("Origin: snapshot saved to %s", SNAPSHOT_FILE)
        return snapshot
    except Exception as e:
        logger.error(f"Origin scrape failed: {e}")
        return {}


async def _scrape_with_cookies_async() -> dict:
    """
    Headless scrape using saved session cookies — no login required.
    Cookies are populated by refresh_from_chrome() after a successful CDP session.
    Returns {"error": "session_expired"} if cookies are stale and Origin redirects to login.
    """
    from playwright.async_api import async_playwright

    cookies = load_cookies()
    if not cookies:
        return {"error": "no_cookies"}

    snapshot = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        try:
            for key, url in _ORIGIN_PAGES.items():
                await page.goto(url, wait_until="networkidle", timeout=25000)
                await page.wait_for_timeout(3000)
                text = await page.evaluate("() => document.body.innerText")

                # Detect session expiry — Origin redirects to login page
                if _is_login_page(text):
                    logger.warning("Origin: session expired — cookies no longer valid")
                    await browser.close()
                    return {"error": "session_expired"}

                snapshot[key + "_text"] = text[:5000]
                logger.info("Origin cookie-scrape: captured %s (%d chars)", key, len(text))

            save_snapshot(snapshot)
            logger.info("Origin: cookie-based scrape complete")
        except Exception as e:
            logger.error("Origin cookie-scrape error: %s", e)
            snapshot["error"] = str(e)
        finally:
            await browser.close()

    return snapshot


def scrape_with_cookies() -> dict:
    """
    Autonomous scrape using saved session cookies — the primary daily refresh path.
    No credentials or manual login required as long as cookies are valid.
    Returns empty dict + logs a warning if cookies are missing or expired.
    """
    if not cookies_exist():
        logger.info("Origin: no saved cookies — run /origin refresh from Chrome first")
        return {"error": "no_cookies"}

    try:
        return asyncio.run(_scrape_with_cookies_async())
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _scrape_with_cookies_async()).result(timeout=120)
    except Exception as e:
        logger.error("Origin cookie scrape error: %s", e)
        return {"error": str(e)}


_CDP_URL = "http://localhost:9222"

_ORIGIN_PAGES = {
    "dashboard":          "https://app.useorigin.com/?dashboard-tab=overview",
    "spending":           "https://app.useorigin.com/spending/overview",
    "spending_breakdown": "https://app.useorigin.com/spending/breakdown",
    "investments":        "https://app.useorigin.com/invest/overview",
    "equity":             "https://app.useorigin.com/equity",
    "forecast":           "https://app.useorigin.com/forecast",
}


async def _refresh_from_chrome_async() -> dict:
    """
    Read live Origin data from an already-authenticated Chrome session via CDP.
    Chrome must be running with --remote-debugging-port=9222.
    This is the preferred refresh method — no credentials needed.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(_CDP_URL)
        except Exception as e:
            logger.warning("Origin: Chrome CDP not available (%s)", e)
            return {"error": f"Chrome not reachable at {_CDP_URL}: {e}"}

        ctx = browser.contexts[0] if browser.contexts else None
        if not ctx:
            await browser.close()
            return {"error": "no browser context found"}

        # Reuse existing Origin tab if open, otherwise open a new one
        origin_page = None
        for pg in ctx.pages:
            if "useorigin.com" in pg.url:
                origin_page = pg
                break
        if not origin_page:
            origin_page = await ctx.new_page()

        snap = {}
        try:
            for key, url in _ORIGIN_PAGES.items():
                await origin_page.goto(url, wait_until="networkidle", timeout=20000)
                await origin_page.wait_for_timeout(3000)
                text = await origin_page.evaluate("() => document.body.innerText")
                snap[key + "_text"] = text[:5000]
                logger.info("Origin CDP: captured %s (%d chars)", key, len(text))
        except Exception as e:
            logger.error("Origin CDP page scrape error: %s", e)
            snap["error"] = str(e)

        if snap and "error" not in snap:
            save_snapshot(snap)
            # Save cookies before closing browser
            try:
                cookies = await ctx.cookies()
                save_cookies(cookies)
            except Exception as e:
                logger.warning("Origin: could not save cookies: %s", e)
            logger.info("Origin: Chrome CDP refresh complete — snapshot + cookies saved")

        await browser.close()
        return snap


def refresh_from_chrome() -> dict:
    """
    Refresh Origin snapshot from live Chrome session via CDP (port 9222).
    Returns snapshot dict. Empty dict on failure.
    """
    try:
        return asyncio.run(_refresh_from_chrome_async())
    except RuntimeError:
        # Already inside a running event loop (e.g. called from async context)
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(asyncio.run, _refresh_from_chrome_async())
            return fut.result(timeout=120)
    except Exception as e:
        logger.error("Origin Chrome refresh error: %s", e)
        return {}


def get_finance_context() -> str:
    """
    Return a formatted string with Origin budget + spending data
    for injection into the finance agent's system prompt.
    """
    snap = load_snapshot()
    if not snap:
        return ""

    age = snapshot_age_hours()
    age_str = f"{age:.0f}h ago" if age is not None else "unknown"

    lines = [f"\n--- Origin Financial Data (as of {age_str}) ---"]

    if snap.get("dashboard_text"):
        lines.append("\nDashboard summary:")
        # Pull the most relevant lines from dashboard text
        for line in snap["dashboard_text"].split("\n"):
            line = line.strip()
            if line and any(kw in line.lower() for kw in [
                "budget", "spent", "credit", "score", "net worth", "month",
                "transaction", "income", "savings", "$", "march", "april"
            ]):
                lines.append(f"  {line}")

    if snap.get("spending_text"):
        lines.append("\nSpending overview:")
        for line in snap["spending_text"].split("\n")[:40]:
            line = line.strip()
            if line and len(line) > 3:
                lines.append(f"  {line}")

    lines.append("--- End Origin Data ---")
    return "\n".join(lines)


def get_investment_context() -> str:
    """
    Return a formatted string with Origin portfolio + equity data
    for injection into the investment agent's system prompt.
    """
    snap = load_snapshot()
    if not snap:
        return ""

    age = snapshot_age_hours()
    age_str = f"{age:.0f}h ago" if age is not None else "unknown"

    lines = [f"\n--- Origin Portfolio Data (as of {age_str}) ---"]

    if snap.get("investments_text"):
        lines.append("\nInvestment accounts:")
        for line in snap["investments_text"].split("\n")[:50]:
            line = line.strip()
            if line and len(line) > 3:
                lines.append(f"  {line}")

    if snap.get("equity_text"):
        lines.append("\nEquity / RSU:")
        for line in snap["equity_text"].split("\n")[:30]:
            line = line.strip()
            if line and len(line) > 3:
                lines.append(f"  {line}")

    if snap.get("forecast_text"):
        lines.append("\nFinancial forecast:")
        for line in snap["forecast_text"].split("\n")[:20]:
            line = line.strip()
            if line and len(line) > 3:
                lines.append(f"  {line}")

    lines.append("--- End Origin Data ---")
    return "\n".join(lines)


def get_dashboard_status() -> str:
    """One-liner status for the Telegram dashboard."""
    snap = load_snapshot()
    if not snap:
        return "No snapshot yet · run 'origin refresh'"

    age = snapshot_age_hours()
    age_str = f"{age:.0f}h ago" if age is not None else "?"

    # Try to pull budget info from dashboard text
    text = snap.get("dashboard_text", "")
    for line in text.split("\n"):
        if "$" in line and ("budget" in line.lower() or "spent" in line.lower() or "%" in line):
            return f"Synced {age_str} · {line.strip()[:60]}"

    return f"Synced {age_str}"
