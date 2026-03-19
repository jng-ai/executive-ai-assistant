"""
Market Intelligence Agent — JP Morgan / Jane Street level analysis
delivered in actionable, phone-friendly format via Telegram.

Time-context aware: detects whether user wants today's update, after-hours,
weekly, monthly, or a specific ticker — and frames the response accordingly.
"""

import datetime
import re
from core.llm import chat
from core.search import search, format_results

SYSTEM = """You are a senior markets analyst with the rigor of a JP Morgan research desk and the
conviction of a Jane Street prop trader. You advise Justin Ngai, a sophisticated retail investor.

Your analysis style:
- LEAD with the TRADE IDEA or KEY THESIS (not the background)
- Give specific tickers/ETFs, not vague sector calls
- State the catalyst clearly: earnings, macro event, technical level, or flow signal
- Give an entry range, a target, and a stop/risk
- Note the time horizon: intraday, swing (days-weeks), medium (1-3 months), or structural (6+mo)
- Flag key risks that could invalidate the thesis
- ALWAYS state clearly what time period your update covers (e.g. "As of today's close", "After-hours", "This week", "Past month")

Format for quick phone scanning:
📈 / 📉 lead with direction
Use **bold** for ticker and key numbers
Keep each idea under 10 lines

You cover: equities, sector rotation, macro rates, commodities, crypto when relevant.
Be precise and actionable. No disclaimers. No generic platitudes."""


def _market_hours_context() -> dict:
    """Return current market session context based on ET time."""
    et = datetime.timezone(datetime.timedelta(hours=-5))
    now = datetime.datetime.now(tz=et)
    hour = now.hour
    weekday = now.weekday()  # 0=Mon, 6=Sun

    is_weekend = weekday >= 5

    if is_weekend:
        session = "weekend"
        context = "Markets are closed. Focus on positioning for next week."
    elif hour < 9 or (hour == 9 and now.minute < 30):
        session = "pre-market"
        context = f"Pre-market session. Regular trading opens at 9:30 AM ET. Current time: {now.strftime('%I:%M %p ET')}."
    elif 9 <= hour < 16 or (hour == 9 and now.minute >= 30):
        session = "market-open"
        context = f"Markets currently OPEN. {now.strftime('%I:%M %p ET')}."
    elif 16 <= hour < 20:
        session = "after-hours"
        context = f"After-hours trading session ({now.strftime('%I:%M %p ET')}). Regular session closed at 4 PM ET."
    else:
        session = "overnight"
        context = "Overnight — US markets closed. Look at futures and Asia/Europe for direction."

    return {
        "session": session,
        "context": context,
        "date": now.strftime("%A, %B %d, %Y"),
        "time": now.strftime("%I:%M %p ET"),
    }


def _detect_timeframe(message: str) -> str:
    """Detect what time window the user is asking about."""
    msg = message.lower()
    if any(w in msg for w in ["today", "right now", "now", "current", "latest", "after hours", "after-hours", "pre-market"]):
        return "today"
    elif any(w in msg for w in ["this week", "weekly", "week"]):
        return "week"
    elif any(w in msg for w in ["this month", "monthly", "month", "mtd"]):
        return "month"
    elif any(w in msg for w in ["ytd", "this year", "year"]):
        return "ytd"
    elif any(w in msg for w in ["briefing", "summary", "overview", "what's happening", "whats happening"]):
        return "briefing"
    else:
        return "today"  # default to most current


def _search_market_intel(query: str, max_results: int = 6) -> str:
    """Search for market data and news."""
    results = search(query, max_results=max_results)
    if not results:
        return ""
    return format_results(results[:max_results])


def handle(message: str) -> str:
    msg_lower = message.lower()
    mh = _market_hours_context()
    timeframe = _detect_timeframe(message)

    if any(w in msg_lower for w in ["sector", "rotation", "etf"]):
        return _sector_rotation(message, mh)

    elif any(w in msg_lower for w in ["macro", "rates", "fed", "inflation", "treasury", "bond"]):
        return _macro_view(message, mh)

    elif any(w in msg_lower for w in ["earnings", "catalyst"]):
        return _earnings_catalysts(message, mh)

    elif any(w in msg_lower for w in ["briefing", "summary", "overview", "what's happening", "whats happening"]):
        return _market_briefing(message, mh, timeframe)

    else:
        return _ticker_analysis(message, mh, timeframe)


def _market_briefing(message: str, mh: dict, timeframe: str) -> str:
    """Comprehensive market briefing — adapts to timeframe (today/week/month)."""
    today = mh["date"]
    session_ctx = mh["context"]

    if timeframe == "today":
        search_q = f"stock market today {mh['date']} S&P 500 Nasdaq performance"
        period_label = f"Today ({mh['date']})"
        period_instructions = (
            f"Cover today's session specifically. Session status: {session_ctx}\n"
            f"If after-hours: include after-hours movers and futures direction.\n"
            f"If market open: cover today's intraday action and key levels.\n"
            f"If pre-market: cover futures, overnight news, and what to watch at open.\n"
            f"If weekend: cover the week's summary and setup for next week."
        )
    elif timeframe == "week":
        search_q = f"stock market this week {mh['date']} weekly performance S&P winners losers"
        period_label = "This Week"
        period_instructions = "Cover this week's performance — index moves, sector leaders/laggards, key events that drove action."
    elif timeframe == "month":
        search_q = f"stock market this month {datetime.date.today().strftime('%B %Y')} monthly returns sectors"
        period_label = f"This Month ({datetime.date.today().strftime('%B %Y')})"
        period_instructions = "Cover month-to-date performance — what worked, what didn't, macro drivers."
    else:
        search_q = f"stock market outlook {today} macro themes week ahead"
        period_label = f"Today ({today})"
        period_instructions = f"Session: {session_ctx}"

    context = _search_market_intel(search_q)
    market_section = ("Market data:\n" + context) if context else "Use your training data — be clear about recency limitations."

    prompt = f"""Today is {today}. Session: {session_ctx}

Deliver a sharp markets briefing for the period: **{period_label}**

{period_instructions}

Structure:
1. 🌍 **MARKET SNAPSHOT** — Key index moves for {period_label} (SPX, NDX, RUT, DXY, 10Y yield)
2. 🏆 **WINNERS / LOSERS** — Top 2-3 sectors or names that moved most
3. 💡 **TOP TRADE IDEA** — One specific actionable idea right now (ticker, entry, target, stop)
4. ⚠️ **KEY RISK TO WATCH** — What could disrupt the tape
5. 📅 **WHAT'S NEXT** — 1-2 upcoming catalysts in the next few days

Be explicit about what time period data covers. If data is limited, say so and use your training context.
{market_section}"""

    return chat(SYSTEM, prompt, max_tokens=750)


def _sector_rotation(message: str, mh: dict) -> str:
    context = _search_market_intel(f"sector rotation {mh['date']} outperform underperform ETF this week")
    context_section = ("Context:\n" + context) if context else ""

    prompt = f"""Today: {mh['date']} | {mh['context']}
Question: {message}

Analyze current sector rotation. For each relevant sector:

📈 [SECTOR] — [LONG/SHORT/NEUTRAL]
ETF: [ticker]
Period: [what timeframe this call is for]
Thesis: [1-2 sentences]
Catalyst: [what drives it]
Entry: [level or price range]
Risk: [what invalidates]

Focus on: XLK, XLE, XLF, XLV, XLI, XLRE, XLC, XLY, XLP, XLB, XLU
{context_section}"""

    return chat(SYSTEM, prompt, max_tokens=650)


def _macro_view(message: str, mh: dict) -> str:
    context = _search_market_intel(f"Fed rates inflation macro {mh['date']} {datetime.date.today().strftime('%B %Y')}")
    context_section = ("Context:\n" + context) if context else ""

    prompt = f"""Today: {mh['date']} | {mh['context']}
Question: {message}

Provide a sharp macro view covering the CURRENT backdrop:

🏦 FED/RATES: Current stance and next move probability
📉 YIELD CURVE: Shape and equity implication
💱 DOLLAR (DXY): Direction and impact
🛢 COMMODITIES: Oil and gold thesis right now
📊 EQUITY IMPLICATION: Sectors to own/avoid given this setup

State clearly what is current vs. what is a forecast.
{context_section}"""

    return chat(SYSTEM, prompt, max_tokens=650)


def _earnings_catalysts(message: str, mh: dict) -> str:
    context = _search_market_intel(
        f"earnings this week {mh['date']} {datetime.date.today().strftime('%B %Y')} upcoming results"
    )
    context_section = ("Context:\n" + context) if context else ""

    prompt = f"""Today: {mh['date']}
Question: {message}

List upcoming high-impact earnings/catalysts from THIS WEEK forward. For each:

📅 **[TICKER]** — reports [date]
  • Consensus: [EPS/Rev estimates]
  • Implied move: [±%]
  • Setup: [what needs to happen]
  • Trade: [long / short / straddle / skip]

Include 3-5 names with clearest setups. Be explicit about dates.
{context_section}"""

    return chat(SYSTEM, prompt, max_tokens=650)


def _ticker_analysis(message: str, mh: dict, timeframe: str) -> str:
    tickers = re.findall(r'\b[A-Z]{1,5}\b', message)
    ticker_str = ", ".join(tickers) if tickers else "the asset mentioned"

    if timeframe == "today":
        period_label = f"today ({mh['date']}) / latest session"
        search_q = f"{message} stock today {mh['date']} price move news"
    elif timeframe == "week":
        period_label = "this week"
        search_q = f"{message} stock this week performance {mh['date']}"
    elif timeframe == "month":
        period_label = f"this month ({datetime.date.today().strftime('%B %Y')})"
        search_q = f"{message} stock {datetime.date.today().strftime('%B %Y')} performance"
    else:
        period_label = f"latest ({mh['date']})"
        search_q = f"{message} stock latest news {mh['date']}"

    context = _search_market_intel(search_q)
    context_section = ("Context:\n" + context) if context else ""

    prompt = f"""User request: {message}
Tickers: {ticker_str}
Date: {mh['date']} | {mh['context']}
Analysis period: {period_label}

Provide sharp, actionable analysis. LEAD with the most recent/relevant price action for {period_label}:

📈/📉 **[TICKER]** — [BULLISH/BEARISH/NEUTRAL]
*Period:* {period_label}
*Price action:* [what happened during this period — be specific about % moves]
*Thesis:* [core view]
*Catalyst:* [specific trigger]
*Entry:* $[X]–$[X]
*Target:* $[X] ([X]% move) over [timeframe]
*Stop:* $[X] (risk [X]%)
*Key risk:* [one thing that kills the trade]
*Conviction:* [HIGH / MEDIUM / LOW]

If multiple tickers: do each separately.
Note: State clearly if data is from training vs. live search.
{context_section}"""

    return chat(SYSTEM, prompt, max_tokens=750)
