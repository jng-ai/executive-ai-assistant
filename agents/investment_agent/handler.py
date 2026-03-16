"""
Investment Agent — Wall Street-style research with real market data.

Data sources:
- yfinance (free, real stock data)
- Brave Search (news + analyst commentary)
"""

import os
import time
import requests
from core.llm import chat

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


def search_news(query: str) -> list:
    api_key = os.environ.get("BRAVE_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            params={"q": query, "count": 5},
            timeout=12,
        )
        resp.raise_for_status()
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "description": r.get("description", "")}
            for r in resp.json().get("web", {}).get("results", [])
        ]
    except Exception:
        return []


def handle(message: str) -> str:
    msg_lower = message.lower()

    # Check if asking about a specific ticker
    words = message.upper().split()
    tickers = [w.strip("$?,!.") for w in words if 2 <= len(w.strip("$?,!.")) <= 5 and w.strip("$?,!.").isalpha()]

    if tickers and not any(kw in msg_lower for kw in ["scan", "ideas", "opportunities", "watchlist"]):
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

        context = f"Give me a quick status update on Justin's watchlist:\n{stock_data}"
        return chat(SYSTEM, context, max_tokens=800)

    # General scan — search for opportunities
    all_news = []
    for q in SEARCH_QUERIES[:2]:
        all_news.extend(search_news(q))
        time.sleep(0.3)

    news_context = "\n\n".join(
        f"TITLE: {r['title']}\nURL: {r['url']}\nSUMMARY: {r['description']}"
        for r in all_news[:15]
    )

    prompt = (
        f"User request: {message}\n\n"
        f"Market news and signals:\n{news_context}\n\n"
        "Identify the top 2-3 investment opportunities or insights."
    )
    return chat(SYSTEM, prompt, max_tokens=800)
