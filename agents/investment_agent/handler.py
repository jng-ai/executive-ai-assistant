"""
Investment Agent — Wall Street-style research with real market data.

Data sources:
- yfinance (free, real stock data)
- Tavily (news + analyst commentary)
"""

import time
import json
import logging
import datetime
from pathlib import Path
from core.llm import chat
from core.search import search, format_results

logger = logging.getLogger(__name__)

DATA_DIR      = Path(__file__).parent.parent.parent / "data"
DCA_STATE_FILE = DATA_DIR / "dca_alert_state.json"

# Target ETFs for DCA recommendations
DCA_ETFS = ["SPY", "QQQ", "VTI", "VEA"]

SYSTEM = """You are Justin Ngai's personal Wall Street research analyst.

Justin's investment profile:
- Risk tolerance: moderate
- Sectors of interest: healthcare AI, biotech, small-cap value, real estate adjacent
- Style: long-term value investing with clear catalysts
- Dislikes: pure speculation, meme stocks, companies burning cash with no path to profit

When analyzing stocks or opportunities, format output as:

*[Company Name (TICKER)]*
📊 Price: $X  |  52w: $X–$X  |  P/E: X
📈 Thesis: [1-2 sentence case]
⚡ Catalyst: [what could drive the move]
⚠️ Risk: [main downside]
✅ Action: BUY / WATCH / PASS
🔥 Urgency: HIGH / MEDIUM / LOW

Keep it phone-friendly and actionable."""

WATCHLIST = ["UNH", "AGIO", "ACAD", "VEEV", "IIPR", "HIMS"]  # Justin's default watchlist


def _origin_portfolio_context() -> str:
    """Pull live Origin Financial portfolio + equity data as context string."""
    try:
        from integrations.origin.scraper import get_investment_context
        return get_investment_context()
    except Exception:
        return ""

SEARCH_QUERIES = [
    "undervalued healthcare AI biotech stocks 2026 strong fundamentals",
    "small cap value stocks healthcare sector catalyst 2026",
    "hedge fund 13F top healthcare buys Q1 2026",
]


def get_stock_data(ticker: str) -> dict:
    """Fetch real stock data from Yahoo Finance (free, no API key needed)."""
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="5d")
        current_price = hist["Close"].iloc[-1] if not hist.empty else None

        return {
            "ticker": ticker,
            "name": info.get("longName", ticker),
            "price": round(current_price, 2) if current_price else "N/A",
            "52w_high": info.get("fiftyTwoWeekHigh", "N/A"),
            "52w_low": info.get("fiftyTwoWeekLow", "N/A"),
            "pe_ratio": round(info.get("trailingPE", 0), 1) if info.get("trailingPE") else "N/A",
            "market_cap": info.get("marketCap", "N/A"),
            "sector": info.get("sector", "N/A"),
            "summary": info.get("longBusinessSummary", "")[:300],
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


# Financial/tax/econ acronyms that look like tickers but are NOT — never look up as stocks
_FINANCE_TERMS = {
    "SALT", "ROTH", "MAGI", "FICA", "COLA", "FDIC", "SIPC", "HELOC", "QSBS",
    "BOLI", "COLI", "SEPP", "UBTI", "NIIT", "AMT", "QBI", "RMD", "MRD",
    "RSU", "ISO", "NSO", "ESPP", "ESOP", "NUA", "CRUT", "CRAT", "GRAT",
    "ILIT", "SLAT", "IDGT", "QTIP", "GRAT", "SPAC", "SPV", "SPE", "NAV",
    "AUM", "TER", "MER", "OER", "YTM", "YTC", "YTW", "DTC", "ACH", "WIRE",
    "TIPS", "TBIL", "TBILLS", "ZIRP", "QE", "QT", "FFR", "FOMC", "CPI",
    "PPI", "PCE", "NFP", "ISM", "PMI", "GDP", "GNP", "EBIT", "EBITDA",
    "FCF", "EPS", "BPS", "DPS", "ROE", "ROA", "ROIC", "DCF", "LBO", "MBO",
    "IPO", "SPO", "PIPE", "DRIP", "DCA", "LIFO", "FIFO", "HIFO", "VLOOKUP",
    "REIT", "MLP", "BDC", "CEF", "ETN", "ETP", "ABS", "MBS", "CDO", "CLO",
    "CDS", "IRS", "SEC", "FINRA", "CFTC", "OCC", "FDIC", "NCUA", "HMO", "PPO",
    "HSA", "FSA", "HRA", "COBRA", "ACA", "CHIP", "SNAP", "SSI", "SSDI",
}

# Common English words that match the ticker pattern (2-5 alpha chars) — never treat as tickers
_COMMON_WORDS = {
    "A", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "HE", "IF", "IN", "IS",
    "IT", "ME", "MY", "NO", "OF", "OK", "ON", "OR", "SO", "TO", "UP", "US",
    "WE", "AM", "ARE", "BUT", "CAN", "DID", "FOR", "FROM", "GET", "GOT",
    "HAD", "HAS", "HIM", "HIS", "HOW", "ITS", "LET", "NOT", "NOW", "OFF",
    "OUT", "OWN", "PUT", "RAN", "RUN", "SAW", "SAY", "SHE", "THE", "TOO",
    "TWO", "USE", "WAS", "WAY", "WHO", "WHY", "WILL", "WITH", "YOU", "YOUR",
    "ALSO", "BACK", "BEEN", "BEST", "BOTH", "CALL", "CAME", "DOES", "DONE",
    "EACH", "EVEN", "FIND", "GAVE", "GIVE", "GOOD", "HAVE", "HELP", "HERE",
    "HIGH", "JUST", "KEEP", "KNOW", "LAST", "LIKE", "LOOK", "MADE", "MAKE",
    "MANY", "MUCH", "MUST", "NEED", "NEXT", "ONLY", "OVER", "SAID", "SAME",
    "SHOW", "SOME", "SUCH", "TAKE", "THAN", "THAT", "THEM", "THEN", "THEY",
    "THIS", "TIME", "TOLD", "TOOK", "TURN", "USED", "VERY", "WANT", "WELL",
    "WENT", "WERE", "WHAT", "WHEN", "WORK", "YEAR", "ABOUT", "AFTER", "AGAIN",
    "COULD", "EVERY", "FIRST", "FOUND", "GOING", "GREAT", "LARGE", "MIGHT",
    "OTHER", "PLACE", "RIGHT", "SMALL", "STILL", "THEIR", "THERE", "THESE",
    "THINK", "THREE", "UNDER", "USING", "WHICH", "WHILE", "WOULD", "WRITE",
    # domain-specific words that look like tickers
    "BASED", "DAILY", "FAST", "GIVE", "IDEA", "LIVE", "MOVE", "OPEN",
    "PASS", "PLAN", "RATE", "REAL", "SCAN", "SELL", "SHOW", "SIDE",
    "STOP", "TERM", "TIPS", "TRADE", "WAIT", "WATCH", "HOLD", "CASH",
    "FUND", "GAIN", "LOSS", "NEWS", "RISK", "SAVE", "GOAL", "LONG",
    "SHORT", "MARKET", "STOCK", "PRICE", "SHARE", "VALUE", "GROWTH",
}


def _get_flagged_ideas() -> list[dict]:
    """Load investment ideas flagged by the finance board."""
    try:
        from pathlib import Path
        flags_file = Path(__file__).parent.parent.parent / "data" / "finance_investment_flags.json"
        if not flags_file.exists():
            return []
        import json
        flags = json.loads(flags_file.read_text())
        return [f for f in flags if f.get("status") == "pending_review"]
    except Exception:
        return []


def _mark_flags_reviewed(tickers: list[str]) -> None:
    """Mark flagged ideas as reviewed after analysis."""
    try:
        from pathlib import Path
        import json
        flags_file = Path(__file__).parent.parent.parent / "data" / "finance_investment_flags.json"
        if not flags_file.exists():
            return
        flags = json.loads(flags_file.read_text())
        for f in flags:
            if f.get("ticker_or_theme") in tickers:
                f["status"] = "reviewed"
        flags_file.write_text(json.dumps(flags, indent=2))
    except Exception:
        pass


# ── DCA Monitor ──────────────────────────────────────────────────────────────

def _calculate_rsi(closes: list, period: int = 14) -> float | None:
    """Calculate RSI from a list of closing prices."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def _get_market_indicators() -> dict:
    """
    Fetch live market data: VIX, SPY/QQQ/VTI price, drawdown from 52w high,
    day change %, and RSI(14). Returns dict of indicators.
    """
    try:
        import yfinance as yf
    except ImportError:
        return {"error": "yfinance not installed"}

    indicators = {}

    # VIX
    try:
        vix = yf.Ticker("^VIX")
        vix_hist = vix.history(period="5d")
        if not vix_hist.empty:
            indicators["vix"] = round(float(vix_hist["Close"].iloc[-1]), 2)
            if len(vix_hist) >= 2:
                indicators["vix_prev"] = round(float(vix_hist["Close"].iloc[-2]), 2)
                indicators["vix_change"] = round(indicators["vix"] - indicators["vix_prev"], 2)
    except Exception as e:
        logger.warning("VIX fetch failed: %s", e)

    # Broad market ETFs
    for ticker in ["SPY", "QQQ", "VTI"]:
        try:
            t = yf.Ticker(ticker)
            info = t.info
            hist = t.history(period="30d")
            if hist.empty:
                continue

            closes = hist["Close"].tolist()
            current = round(closes[-1], 2)
            prev    = round(closes[-2], 2) if len(closes) >= 2 else current
            high_52w = info.get("fiftyTwoWeekHigh") or max(closes)
            drawdown_pct = round((current - high_52w) / high_52w * 100, 2)  # negative = below high
            day_chg_pct  = round((current - prev) / prev * 100, 2)
            rsi = _calculate_rsi(closes)

            indicators[ticker] = {
                "price":        current,
                "prev_close":   prev,
                "day_chg_pct":  day_chg_pct,
                "high_52w":     round(high_52w, 2),
                "drawdown_pct": drawdown_pct,  # negative number, e.g. -12.3
                "rsi":          rsi,
            }
        except Exception as e:
            logger.warning("%s fetch failed: %s", ticker, e)

    indicators["_fetched_at"] = datetime.datetime.now().isoformat()
    return indicators


def _score_dca_signal(indicators: dict) -> tuple[int, str, str, str]:
    """
    Score market conditions for a DCA opportunity.
    Returns (score, level_emoji, level_name, recommendation).
    """
    score = 0
    reasons = []

    vix = indicators.get("vix", 0)
    spy = indicators.get("SPY", {})
    spy_drawdown = abs(spy.get("drawdown_pct", 0))  # positive = % below 52w high
    spy_rsi      = spy.get("rsi")
    spy_day_chg  = spy.get("day_chg_pct", 0)

    # VIX component (0–40 pts)
    if vix >= 40:
        score += 40; reasons.append(f"VIX {vix:.1f} — extreme panic (≥40)")
    elif vix >= 35:
        score += 32; reasons.append(f"VIX {vix:.1f} — very high fear (≥35)")
    elif vix >= 30:
        score += 24; reasons.append(f"VIX {vix:.1f} — elevated fear (≥30)")
    elif vix >= 25:
        score += 16; reasons.append(f"VIX {vix:.1f} — above normal (≥25)")
    elif vix >= 20:
        score += 8;  reasons.append(f"VIX {vix:.1f} — slightly elevated (≥20)")

    # Drawdown from 52w high (0–40 pts)
    if spy_drawdown >= 20:
        score += 40; reasons.append(f"SPY {spy_drawdown:.1f}% below 52w high — bear market territory")
    elif spy_drawdown >= 15:
        score += 30; reasons.append(f"SPY {spy_drawdown:.1f}% below 52w high — correction deepening")
    elif spy_drawdown >= 10:
        score += 20; reasons.append(f"SPY {spy_drawdown:.1f}% below 52w high — correction territory")
    elif spy_drawdown >= 5:
        score += 10; reasons.append(f"SPY {spy_drawdown:.1f}% below 52w high — pullback")
    elif spy_drawdown >= 3:
        score += 5;  reasons.append(f"SPY {spy_drawdown:.1f}% below 52w high — minor dip")

    # RSI component (0–20 pts)
    if spy_rsi is not None:
        if spy_rsi < 30:
            score += 20; reasons.append(f"SPY RSI {spy_rsi} — oversold (< 30)")
        elif spy_rsi < 35:
            score += 12; reasons.append(f"SPY RSI {spy_rsi} — approaching oversold")
        elif spy_rsi < 40:
            score += 6;  reasons.append(f"SPY RSI {spy_rsi} — weakening momentum")

    # Sharp single-day drop bonus
    if spy_day_chg <= -3:
        score += 10; reasons.append(f"SPY down {spy_day_chg:.1f}% today — sharp single-day drop")
    elif spy_day_chg <= -2:
        score += 5;  reasons.append(f"SPY down {spy_day_chg:.1f}% today")

    # Determine level
    if score >= 70:
        level_emoji = "🔴"
        level_name  = "STRONG BUY"
        rec = (
            "Deploy *full monthly DCA allocation + reserve cash*. "
            "Scale into SPY/VTI/QQQ over 1–2 weeks. "
            "This is a high-conviction entry — VIX panic + significant drawdown historically precedes strong recoveries."
        )
    elif score >= 50:
        level_emoji = "🟠"
        level_name  = "DCA SIGNAL"
        rec = (
            "Deploy *50% of your monthly DCA allocation now* into SPY/VTI. "
            "Hold remaining 50% to average in over next 2–3 weeks if weakness continues."
        )
    elif score >= 25:
        level_emoji = "🟡"
        level_name  = "WATCH"
        rec = (
            "Consider deploying *25% of monthly allocation* as a starter position. "
            "Set alerts for VIX ≥ 30 or SPY drawdown ≥ 10% for larger deployment."
        )
    else:
        level_emoji = "🟢"
        level_name  = "NORMAL"
        rec = "Market within normal range. Stick to your scheduled DCA. No action needed."

    return score, level_emoji, level_name, rec, reasons


def _load_dca_state() -> dict:
    if DCA_STATE_FILE.exists():
        try:
            return json.loads(DCA_STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_dca_state(state: dict):
    DATA_DIR.mkdir(exist_ok=True)
    DCA_STATE_FILE.write_text(json.dumps(state, indent=2))


def _format_dca_report(indicators: dict, score: int, emoji: str,
                        level: str, rec: str, reasons: list) -> str:
    """Format a phone-friendly DCA signal report."""
    spy  = indicators.get("SPY", {})
    qqq  = indicators.get("QQQ", {})
    vti  = indicators.get("VTI", {})
    vix  = indicators.get("vix", "?")
    vix_chg = indicators.get("vix_change", 0)

    vix_arrow = "📈" if vix_chg > 0 else "📉" if vix_chg < 0 else "➡️"

    lines = [
        f"{emoji} *DCA SIGNAL: {level}* (score {score}/100)\n",
        f"📊 *Market Snapshot*",
        f"• VIX: {vix} {vix_arrow} ({'+' if vix_chg >= 0 else ''}{vix_chg:.1f} vs yesterday)",
        f"• SPY: ${spy.get('price','?')} | {spy.get('day_chg_pct',0):+.1f}% today | "
        f"{spy.get('drawdown_pct',0):.1f}% from 52w high | RSI {spy.get('rsi','?')}",
        f"• QQQ: ${qqq.get('price','?')} | {qqq.get('day_chg_pct',0):+.1f}% today | "
        f"{qqq.get('drawdown_pct',0):.1f}% from 52w high",
        f"• VTI: ${vti.get('price','?')} | {vti.get('day_chg_pct',0):+.1f}% today",
        f"\n📋 *Why this signal:*",
    ]
    for r in reasons:
        lines.append(f"  • {r}")

    lines += [
        f"\n💡 *Recommendation:*",
        rec,
        f"\n🎯 *Target ETFs:* SPY (S&P 500) · VTI (Total Market) · QQQ (Nasdaq)",
        f"_Score methodology: VIX level (40pts) + drawdown from 52w high (40pts) + RSI (20pts)_",
    ]
    return "\n".join(lines)


def run_vix_dca_check(force: bool = False) -> str:
    """
    Check market conditions for a DCA opportunity.
    Returns alert string if signal ≥ WATCH, empty string if market is normal.
    Won't re-alert for the same level on the same day (dedup) unless force=True.
    """
    indicators = _get_market_indicators()
    if "error" in indicators:
        logger.error("DCA check: %s", indicators["error"])
        return ""

    result = _score_dca_signal(indicators)
    score, emoji, level, rec, reasons = result

    # Skip if normal
    if level == "NORMAL" and not force:
        logger.info("DCA check: market normal (score %d) — no alert", score)
        return ""

    # Dedup — don't repeat same level same day
    today = datetime.date.today().isoformat()
    state = _load_dca_state()
    if not force and state.get("last_alert_date") == today and state.get("last_level") == level:
        logger.info("DCA check: already alerted %s today — skipping", level)
        return ""

    # Save state
    _save_dca_state({
        "last_alert_date": today,
        "last_level": level,
        "last_score": score,
        "last_vix": indicators.get("vix"),
        "_updated": datetime.datetime.now().isoformat(),
    })

    return _format_dca_report(indicators, score, emoji, level, rec, reasons)


_COMPANY_TO_TICKER = {
    "micron": "MU", "nvidia": "NVDA", "apple": "AAPL", "amazon": "AMZN",
    "google": "GOOGL", "alphabet": "GOOGL", "meta": "META", "microsoft": "MSFT",
    "tesla": "TSLA", "netflix": "NFLX", "palantir": "PLTR", "coinbase": "COIN",
    "berkshire": "BRK-B", "jpmorgan": "JPM", "goldman": "GS", "morgan stanley": "MS",
    "unitedhealth": "UNH", "eli lilly": "LLY", "abbvie": "ABBV", "pfizer": "PFE",
    "moderna": "MRNA", "johnson": "JNJ", "merck": "MRK", "bristol": "BMY",
    "intuitive surgical": "ISRG", "veeva": "VEEV", "iqvia": "IQV",
    "blackrock": "BLK", "vanguard": "N/A", "fidelity": "N/A",
}


def _search_holding_in_origin(name_or_ticker: str) -> str | None:
    """Search Origin investment text for a company name or ticker. Returns matching line or None."""
    try:
        from integrations.origin.scraper import load_snapshot
        snap = load_snapshot()
        if not snap:
            return None
        invest_text = snap.get("investments_text", "") + "\n" + snap.get("equity_text", "")
        name_lower = name_or_ticker.lower()
        for line in invest_text.split("\n"):
            if name_lower in line.lower():
                return line.strip()
        return None
    except Exception:
        return None


def handle(message: str) -> str:
    msg_lower = message.lower()

    # ── DCA signal check ──────────────────────────────────────────────────────
    if any(kw in msg_lower for kw in ["dca signal", "dca check", "buy the dip", "should i dca",
                                       "market dip", "vix check", "vix alert", "market signal",
                                       "dca alert", "is it a good time to buy", "broad market"]):
        result = run_vix_dca_check(force=True)
        return result or "🟢 *DCA Check: NORMAL*\n\nMarket is within normal range — no elevated signal. Stick to your scheduled DCA."

    # ── Explain/define mode — financial terms, concepts, not ticker lookup ────
    explain_triggers = ["explain", "what is", "what's", "what are", "define", "tell me about",
                        "what does", "meaning of", "how does", "how do"]
    if any(msg_lower.startswith(t) or f" {t} " in msg_lower for t in explain_triggers):
        # Only skip if there's no obvious ticker intent alongside (e.g. "explain why NVDA dropped")
        has_ticker_intent = any(kw in msg_lower for kw in ["dropped", "rallied", "earnings", "price", "buy", "sell"])
        if not has_ticker_intent:
            from agents.finance_agent.handler import SYSTEM as FINANCE_SYSTEM, JUSTIN_CONTEXT
            return chat(
                f"You are Justin's financial board advisor (JP Morgan + Jane Street). "
                f"Explain financial, tax, and investment terms clearly and concisely. "
                f"Relate them to Justin's situation when relevant.\n\n{JUSTIN_CONTEXT}",
                message,
                max_tokens=600,
            )

    # ── Finance board flagged ideas ────────────────────────────────────────────
    if any(kw in msg_lower for kw in ["flagged ideas", "finance flags", "board flags",
                                       "what did finance flag", "pending ideas"]):
        flags = _get_flagged_ideas()
        if not flags:
            return "📌 No pending investment ideas flagged by the finance board."
        lines = ["📌 *Finance Board — Flagged Investment Ideas*\n"]
        tickers = []
        for f in flags:
            conv = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(f.get("conviction", ""), "•")
            lines.append(f"{conv} **{f['ticker_or_theme']}** — {f.get('rationale', '')}")
            lines.append(f"   Flagged: {f.get('flagged_date', '?')} | Conviction: {f.get('conviction', '?')}")
            tickers.append(f.get("ticker_or_theme", ""))
        lines.append("\n_Say the ticker name for a full analysis._")
        _mark_flags_reviewed(tickers)
        return "\n".join(lines)

    # ── "Do I have / do I own X" — check Origin holdings ─────────────────────
    holding_triggers = ["do i have", "do i own", "am i holding", "am i in", "is it in my",
                        "do i hold", "check my holding", "in my portfolio"]
    if any(t in msg_lower for t in holding_triggers):
        origin_ctx = _origin_portfolio_context()
        # Also check raw snapshot text for the specific name
        for company, ticker in _COMPANY_TO_TICKER.items():
            if company in msg_lower or ticker.lower() in msg_lower:
                hit = _search_holding_in_origin(company) or _search_holding_in_origin(ticker)
                if hit:
                    context = (
                        f"User asked: {message}\n\n"
                        f"Found in Origin portfolio data: '{hit}'\n\n"
                        f"Full portfolio context:\n{origin_ctx}"
                    )
                    return chat(SYSTEM, context + "\nConfirm if Justin holds this position and give a brief current analysis.", max_tokens=500)
                else:
                    context = (
                        f"User asked: {message}\n\n"
                        f"Searched Origin portfolio data — '{company.title()}' ({ticker}) not found in investment text.\n\n"
                        f"Portfolio context:\n{origin_ctx}"
                    )
                    return chat(SYSTEM, context + "\nTell Justin clearly whether you can confirm this holding, and note if Origin data may be incomplete.", max_tokens=400)
        # Generic holding check with full origin context
        if origin_ctx:
            return chat(SYSTEM, f"User asked: {message}\n\nOrigin portfolio data:\n{origin_ctx}\nAnswer based on the actual holdings shown.", max_tokens=600)

    # ── Portfolio / holdings overview ─────────────────────────────────────────
    if any(kw in msg_lower for kw in ["origin", "my portfolio", "my holdings", "my investments",
                                       "portfolio update", "portfolio review", "what do i own",
                                       "what am i invested in"]):
        origin_ctx = _origin_portfolio_context()
        if origin_ctx:
            prompt = (
                f"User request: {message}\n\n"
                f"Justin's actual Origin Financial portfolio data:\n{origin_ctx}\n\n"
                "Give a clear portfolio summary and analysis based on his actual holdings. "
                "Identify allocation gaps, concentration risks, and 1-2 actionable moves."
            )
            return chat(SYSTEM, prompt, max_tokens=900)

    # ── Check if asking about a specific ticker ────────────────────────────────
    # Map company names to tickers first
    resolved_tickers = []
    for company, ticker in _COMPANY_TO_TICKER.items():
        if company in msg_lower and ticker != "N/A":
            resolved_tickers.append(ticker)

    words = message.upper().split()
    detected = [
        w.strip("$?,!.") for w in words
        if 2 <= len(w.strip("$?,!.")) <= 5
        and w.strip("$?,!.").isalpha()
        and w.strip("$?,!.") not in _COMMON_WORDS
        and w.strip("$?,!.") not in _FINANCE_TERMS
    ]
    tickers = list(dict.fromkeys(resolved_tickers + detected))  # resolved first, deduplicated

    if tickers and not any(kw in msg_lower for kw in ["scan", "ideas", "opportunities", "watchlist", "portfolio"]):
        # Analyze specific ticker(s)
        results = []
        for ticker in tickers[:3]:
            data = get_stock_data(ticker)
            if "error" not in data:
                results.append(data)

        if results:
            context = f"Analyze these stocks for Justin:\n{results}\n\nUser question: {message}"
            return chat(SYSTEM, context, max_tokens=700)

    # Watchlist check
    if "watchlist" in msg_lower or "portfolio" in msg_lower:
        stock_data = []
        for ticker in WATCHLIST:
            data = get_stock_data(ticker)
            if "error" not in data:
                stock_data.append(data)
            time.sleep(0.2)

        origin_ctx = _origin_portfolio_context()
        context = (
            f"Give me a quick status update on Justin's watchlist:\n{stock_data}"
            + (f"\n\nJustin's actual Origin Financial portfolio data:\n{origin_ctx}" if origin_ctx else "")
        )
        return chat(SYSTEM, context, max_tokens=900)

    # General scan — search for opportunities
    all_news = []
    for q in SEARCH_QUERIES[:2]:
        all_news.extend(search(q, max_results=5))
        time.sleep(0.3)

    news_context = format_results(all_news[:15])
    origin_ctx = _origin_portfolio_context()

    prompt = (
        f"User request: {message}\n\n"
        f"Market news and signals:\n{news_context}\n\n"
        + (f"Justin's actual Origin Financial portfolio data:\n{origin_ctx}\n\n" if origin_ctx else "")
        + "Identify the top 2-3 investment opportunities or insights. "
          "If Origin portfolio data is present, cross-reference Justin's actual holdings and allocation."
    )
    return chat(SYSTEM, prompt, max_tokens=900)
