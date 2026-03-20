"""
Paperstac Scraper — authenticated listing fetcher.

Uses Playwright (headless Chromium) to log into paperstac.com with
Justin's credentials and extract performing first lien note listings
that match his buying criteria.

Env vars required:
  PAPERSTAC_EMAIL    — Paperstac account email
  PAPERSTAC_PASSWORD — Paperstac account password
"""

import os
import asyncio
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

NON_JUDICIAL_STATES = {
    "TX", "GA", "FL", "NC", "TN", "AZ", "CO", "MI", "VA", "MO",
    "WA", "OR", "NV", "AL", "AR", "CA", "ID", "MN", "MS", "MT",
    "NE", "NH", "NM", "OK", "SD", "UT", "WY"
}

LOGIN_URL    = "https://paperstac.com/login"
LISTINGS_URL = "https://paperstac.com/marketplace"


def is_configured() -> bool:
    return bool(os.getenv("PAPERSTAC_EMAIL") and os.getenv("PAPERSTAC_PASSWORD"))


async def _scrape_async() -> list[dict]:
    """Login and extract listings using headless Chromium."""
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout

    email    = os.getenv("PAPERSTAC_EMAIL", "")
    password = os.getenv("PAPERSTAC_PASSWORD", "")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        try:
            # ── Login ──────────────────────────────────────────────────────────
            logger.info("Paperstac: navigating to login page")
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            # Fill credentials
            await page.fill('input[type="email"], input[name="email"]', email)
            await page.wait_for_timeout(500)
            await page.fill('input[type="password"], input[name="password"]', password)
            await page.wait_for_timeout(500)
            await page.click('button[type="submit"]')

            # Wait for URL to change away from login page (SPA navigation)
            try:
                await page.wait_for_url(
                    lambda url: "login" not in url and "signin" not in url,
                    timeout=15000
                )
            except Exception:
                pass  # proceed and check URL manually

            # Give React time to settle
            await page.wait_for_timeout(3000)
            current_url = page.url
            logger.info(f"Paperstac: after login URL = {current_url}")

            # Check we're no longer on the login page
            if "login" in current_url or "signin" in current_url:
                logger.error("Paperstac: still on login page — credentials may be wrong")
                return []

            logger.info("Paperstac: logged in successfully")

            # ── Navigate to marketplace with filters ───────────────────────────
            for listings_url in [
                "https://paperstac.com/marketplace?noteType=performing&lienPosition=first",
                "https://paperstac.com/marketplace",
                "https://paperstac.com/listings",
            ]:
                await page.goto(listings_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(5000)  # let React render without waiting for networkidle
                if page.url and "login" not in page.url:
                    logger.info(f"Paperstac: on listings page {page.url}")
                    break

            # Scroll to load more listings
            for _ in range(3):
                await page.keyboard.press("End")
                await page.wait_for_timeout(1500)

            # ── Extract listing data ───────────────────────────────────────────
            raw_listings = await page.evaluate("""() => {
                const deals = [];

                // Try different selectors Paperstac may use for listing cards
                const cards = document.querySelectorAll(
                    '[class*="listing"], [class*="NoteCard"], [class*="note-card"], ' +
                    '[data-testid*="listing"], article[class*="note"], .listing-card'
                );

                cards.forEach(card => {
                    const text = card.innerText || '';
                    const link = card.querySelector('a');
                    deals.push({
                        text: text.substring(0, 500),
                        url: link ? link.href : '',
                        html: card.innerHTML.substring(0, 1000),
                    });
                });

                // Fallback: grab all text from the page if no cards found
                if (deals.length === 0) {
                    return [{
                        text: document.body.innerText.substring(0, 8000),
                        url: window.location.href,
                        html: '',
                        fallback: true,
                    }];
                }

                return deals;
            }""")

            logger.info(f"Paperstac: extracted {len(raw_listings)} raw items")
            return raw_listings

        except PWTimeout as e:
            logger.error(f"Paperstac timeout: {e}")
            return []
        except Exception as e:
            logger.error(f"Paperstac scrape error: {e}")
            return []
        finally:
            await browser.close()


def _parse_deal(item: dict) -> Optional[dict]:
    """
    Parse a raw scraped item into a structured deal dict.
    Returns None if not a valid deal.
    """
    text = item.get("text", "") + " " + item.get("html", "")
    url  = item.get("url", "")

    # Extract UPB
    upb_match = re.search(
        r'(?:UPB|unpaid.{0,5}balance)[:\s]*\$?([\d,]+)',
        text, re.IGNORECASE
    )
    if not upb_match:
        upb_match = re.search(r'\$\s*([\d,]{5,})', text)
    if not upb_match:
        return None

    try:
        upb = float(upb_match.group(1).replace(",", ""))
    except ValueError:
        return None

    if upb > 120_000:  # filter out too-large notes (allow slight buffer)
        return None

    # Extract ask price
    ask_match = re.search(
        r'(?:ask(?:ing)?|price|listed.{0,5}at)[:\s]*\$?([\d,]+)',
        text, re.IGNORECASE
    )
    ask = None
    if ask_match:
        try:
            ask = float(ask_match.group(1).replace(",", ""))
        except ValueError:
            pass

    # Extract state (2-letter abbreviation near property/state keywords)
    state_match = re.search(
        r'(?:state|property|location)[:\s]*([A-Z]{2})\b',
        text, re.IGNORECASE
    )
    if not state_match:
        # Fallback: find any 2-letter state code in text
        for state in NON_JUDICIAL_STATES:
            if re.search(r'\b' + state + r'\b', text):
                state_match = type('M', (), {'group': lambda s, n: state})()
                break

    state = state_match.group(1).upper() if state_match else "UNKNOWN"

    # Filter to non-judicial states only
    if state not in NON_JUDICIAL_STATES and state != "UNKNOWN":
        return None

    # Calculate discount if ask is available
    discount = None
    if ask and upb and ask < upb:
        discount = round((upb - ask) / upb * 100, 1)
        if discount < 15:  # too small a discount
            return None

    return {
        "upb":      upb,
        "ask":      ask,
        "state":    state,
        "discount": discount,
        "url":      url,
        "raw_text": text[:300],
    }


def scrape_listings() -> list[dict]:
    """
    Synchronous entry point — runs the async scraper and returns
    a list of parsed deal dicts matching Justin's criteria.
    """
    try:
        raw = asyncio.run(_scrape_async())
    except Exception as e:
        logger.error(f"Paperstac asyncio error: {e}")
        return []

    deals = []
    for item in raw:
        parsed = _parse_deal(item)
        if parsed:
            deals.append(parsed)

    # Sort by discount descending
    deals.sort(key=lambda d: d.get("discount") or 0, reverse=True)
    return deals[:15]  # top 15 matches


def format_deals(deals: list[dict]) -> str:
    """Format parsed deals into Telegram-ready markdown."""
    if not deals:
        return (
            "🔍 *Paperstac Scan — No Matching Deals Today*\n\n"
            "Checked live listings — nothing currently meeting:\n"
            "• Performing first lien\n"
            "• UPB < $100k\n"
            "• 20%+ discount\n"
            "• Non-judicial state\n\n"
            "Try again tomorrow or browse directly: paperstac.com/marketplace"
        )

    lines = [f"🏦 *Paperstac Live Scan — {len(deals)} Match{'es' if len(deals) != 1 else ''}*\n"]
    for d in deals:
        upb_str  = f"${d['upb']:,.0f}"
        ask_str  = f"${d['ask']:,.0f}" if d['ask'] else "TBD"
        disc_str = f"{d['discount']:.0f}% discount" if d['discount'] else "—"
        state    = d['state']
        link     = d['url'] or "paperstac.com/marketplace"

        lines.append(
            f"🏠 *{state} | UPB: {upb_str} | Ask: {ask_str}*\n"
            f"📊 {disc_str} | First Lien Performing\n"
            f"📍 {state} — Non-Judicial ✓\n"
            f"🔗 {link}\n"
        )

    lines.append("\n_Reply `underwrite [details]` to analyze any deal_")
    return "\n".join(lines)
