"""
Investment Agent — Wall Street-style research with real market data.

Data sources:
- yfinance (free, real stock data)
- Tavily (news + analyst commentary)
"""

import time
from core.llm import chat
from core.search import search, format_results

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


def handle(message: str) -> str:
    msg_lower = message.lower()

    # Origin-specific portfolio request — skip ticker detection, go straight to Origin data
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

    # Check if asking about a specific ticker
    words = message.upper().split()
    tickers = [
        w.strip("$?,!.") for w in words
        if 2 <= len(w.strip("$?,!.")) <= 5
        and w.strip("$?,!.").isalpha()
        and w.strip("$?,!.") not in _COMMON_WORDS
    ]

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
