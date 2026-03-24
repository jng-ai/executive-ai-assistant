"""
Web Dashboard Server — FastAPI app serving the executive AI dashboard.
Runs in a background thread alongside the Telegram bot.

Access: http://localhost:8080  (or via Cloudflare Tunnel for remote access)
"""

import os
import json
import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

DATA_DIR   = Path(__file__).parent.parent.parent / "data"
STATIC_DIR = Path(__file__).parent / "static"

WATCHLIST = ["UNH", "AGIO", "ACAD", "VEEV", "IIPR", "HIMS"]

# 5-minute yfinance cache shared by /api/market and /api/investment
_yf_cache: dict = {}
_YF_TTL = 300  # seconds

app = FastAPI(title="Executive AI Dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Generic helpers ────────────────────────────────────────────────────────────

def _load(path: Path):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return [] if not str(path).endswith("profile.json") else {}


def _days_ago(iso: str) -> str:
    try:
        d = datetime.date.fromisoformat(iso[:10])
        delta = (datetime.date.today() - d).days
        if delta == 0:  return "today"
        if delta == 1:  return "yesterday"
        return f"{delta}d ago"
    except Exception:
        return "—"


def _et_now() -> datetime.datetime:
    et = datetime.timezone(datetime.timedelta(hours=-5))
    return datetime.datetime.now(tz=et)


# ── yfinance helpers ───────────────────────────────────────────────────────────

def _yf_fetch() -> dict:
    """Batch-fetch WATCHLIST via yfinance; cached for 5 min."""
    now = datetime.datetime.now()
    if _yf_cache.get("ts") and (now - _yf_cache["ts"]).total_seconds() < _YF_TTL:
        return _yf_cache.get("data", {})
    try:
        import yfinance as yf
        stocks = []
        for sym in WATCHLIST:
            try:
                t   = yf.Ticker(sym)
                fi  = t.fast_info
                price       = fi.last_price
                prev_close  = fi.previous_close
                change_pct  = round((price - prev_close) / prev_close * 100, 2) if prev_close else None
                week52_high = fi.fifty_two_week_high
                week52_low  = fi.fifty_two_week_low
                pos_pct     = None
                if week52_high and week52_low and week52_high > week52_low:
                    pos_pct = round((price - week52_low) / (week52_high - week52_low) * 100, 1)
                stocks.append({
                    "ticker":      sym,
                    "price":       round(price, 2) if price else None,
                    "change_pct":  change_pct,
                    "prev_close":  round(prev_close, 2) if prev_close else None,
                    "week52_high": round(week52_high, 2) if week52_high else None,
                    "week52_low":  round(week52_low,  2) if week52_low  else None,
                    "pos_pct":     pos_pct,  # % position within 52w range
                })
            except Exception:
                stocks.append({"ticker": sym, "price": None, "change_pct": None})
        result = {"stocks": stocks, "fetched_at": now.isoformat()}
        _yf_cache["ts"]   = now
        _yf_cache["data"] = result
        return result
    except Exception as e:
        return {"stocks": [], "error": str(e)}


# ── Email urgency ──────────────────────────────────────────────────────────────

_URGENT_KWORDS  = ["urgent", "asap", "deadline", "action required", "invoice due",
                   "overdue", "critical", "immediately", "time sensitive", "expires today"]
_REPLY_KWORDS   = ["?", "follow up", "following up", "checking in", "reminder",
                   "please review", "your feedback", "let me know", "please confirm",
                   "can you", "could you", "would you"]
_FYI_SENDERS    = ["noreply", "no-reply", "newsletter", "notification", "donotreply",
                   "updates@", "hello@", "info@", "digest@", "subscriptions@"]

def _email_urgency(subject: str, snippet: str, sender: str) -> int:
    """Return 2=urgent 🔴, 1=needs reply 🟡, 0=FYI ⚪"""
    text = f"{subject} {snippet}".lower()
    from_low = sender.lower()
    if any(k in from_low for k in _FYI_SENDERS):
        return 0
    if any(k in text for k in _URGENT_KWORDS):
        return 2
    if any(k in text for k in _REPLY_KWORDS):
        return 1
    return 0


# ── Summary endpoint ───────────────────────────────────────────────────────────

@app.get("/api/summary")
async def api_summary():
    """All agent statuses in one call — main dashboard poll."""
    et = _et_now()
    return JSONResponse({
        "server_time": et.strftime("%a %b %-d, %-I:%M %p ET"),
        "agents": {
            "health":     _health_status(),
            "finance":    _finance_status(),
            "market":     _market_status(),
            "calendar":   _calendar_status(),
            "email":      _email_status(),
            "travel":     _travel_status(),
            "followup":   _followup_status(),
            "bonus":      _bonus_status(),
            "social":     _social_status(),
            "mortgage":   _mortgage_status(),
            "infusion":   _infusion_status(),
            "investment": _investment_status(),
        }
    })


# ── Detail endpoints ───────────────────────────────────────────────────────────

@app.get("/api/health")
async def api_health():
    logs = _load(DATA_DIR / "health.json")
    if not isinstance(logs, list): logs = []

    today    = datetime.date.today().isoformat()
    week_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    days14   = (datetime.date.today() - datetime.timedelta(days=14)).isoformat()

    today_logs  = [l for l in logs if l.get("date","")[:10] == today]
    week_logs   = [l for l in logs if l.get("date","")[:10] >= week_ago]
    meals       = [l for l in today_logs if l.get("metric") == "meal"]
    workouts_wk = [l for l in week_logs   if l.get("metric") == "workout"]
    weights     = sorted([l for l in logs if l.get("metric") == "weight"],
                         key=lambda x: x.get("date",""))
    sleeps      = sorted([l for l in logs if l.get("metric") == "sleep"],
                         key=lambda x: x.get("date",""))
    recent_logs = sorted(logs, key=lambda x: x.get("date",""), reverse=True)[:20]

    # 14-day weight history
    weight_history = [
        {"date": l["date"][:10], "value": l["value"]}
        for l in weights if l.get("date","")[:10] >= days14
    ]
    # 7-day sleep history
    sleep_history = [
        {"date": l["date"][:10], "value": l["value"]}
        for l in sleeps if l.get("date","")[:10] >= week_ago
    ]
    # 7-day workout dots
    workout_dates = {l["date"][:10] for l in week_logs if l.get("metric") == "workout"}
    workout_week_grid = []
    for i in range(6, -1, -1):
        d = (datetime.date.today() - datetime.timedelta(days=i)).isoformat()
        workout_week_grid.append({"date": d, "done": d in workout_dates})

    return JSONResponse({
        "last_weight":      {"value": weights[-1].get("value","—"), "date": _days_ago(weights[-1]["date"][:10])} if weights else None,
        "last_sleep":       {"value": sleeps[-1].get("value","—"),  "date": _days_ago(sleeps[-1]["date"][:10])}  if sleeps else None,
        "meals_today":      len(meals),
        "workouts_week":    len(workouts_wk),
        "workout_goal":     4,
        "targets":          {"weight": 165, "protein": 150, "calories": 1900, "sleep": 7.5},
        "weight_history":   weight_history,
        "sleep_history":    sleep_history,
        "workout_week_grid":workout_week_grid,
        "recent_logs":      recent_logs,
    })


@app.get("/api/finance")
async def api_finance():
    profile    = _load(DATA_DIR / "financial_profile.json")
    budget     = _load(DATA_DIR / "budget_log.json")
    bonuses    = _load(DATA_DIR / "bonus_alerts_sent.json")
    side_hustle = _load(DATA_DIR / "side_hustle_ideas.json")
    if not isinstance(budget, list):     budget = []
    if not isinstance(side_hustle, list): side_hustle = []

    # Budget by category (current month)
    this_month = datetime.date.today().isoformat()[:7]
    month_budget = [b for b in budget if b.get("date","")[:7] == this_month]
    by_cat: dict = {}
    for b in month_budget:
        cat = b.get("category", "Other")
        by_cat[cat] = round(by_cat.get(cat, 0) + float(b.get("amount", 0)), 2)

    last_offers = bonuses.get("last_offers", []) if isinstance(bonuses, dict) else []

    return JSONResponse({
        "profile_updated":   _days_ago(profile.get("last_updated","")[:10]) if isinstance(profile, dict) else "—",
        "net_worth":         profile.get("net_worth") or profile.get("estimated_net_worth","—") if isinstance(profile, dict) else "—",
        "last_bonus_scan":   _days_ago(bonuses.get("last_scan","")[:10]) if isinstance(bonuses, dict) else "—",
        "recent_budget":     budget[-10:] if budget else [],
        "budget_by_category":by_cat,
        "last_offers":       last_offers,
        "side_hustles":      side_hustle[:5],
    })


@app.get("/api/market")
async def api_market():
    et = _et_now()
    h, m, wd = et.hour, et.minute, et.weekday()
    if wd >= 5:
        session, color = "Closed — Weekend", "gray"
    elif h < 9 or (h == 9 and m < 30):
        session, color = "Pre-Market", "yellow"
    elif (h == 9 and m >= 30) or (10 <= h < 16):
        session, color = "Market Open", "green"
    else:
        session, color = "After-Hours", "orange"

    # Next open time
    next_open = None
    if color == "gray":
        days_to_mon = (7 - wd) % 7
        if days_to_mon == 0: days_to_mon = 7
        next_open = (datetime.date.today() + datetime.timedelta(days=days_to_mon)).isoformat() + " 9:30 AM ET"
    elif color in ("gray", "orange"):
        next_open = "Tomorrow 9:30 AM ET"

    yf_data = _yf_fetch()
    return JSONResponse({
        "session":    session,
        "color":      color,
        "time_et":    et.strftime("%-I:%M %p ET"),
        "next_open":  next_open,
        "stocks":     yf_data.get("stocks", []),
        "fetched_at": yf_data.get("fetched_at"),
        "error":      yf_data.get("error"),
    })


@app.get("/api/investment")
async def api_investment():
    yf_data = _yf_fetch()
    stocks  = yf_data.get("stocks", [])
    up   = sum(1 for s in stocks if (s.get("change_pct") or 0) >= 0)
    down = sum(1 for s in stocks if (s.get("change_pct") or 0) < 0)
    best = max(stocks, key=lambda s: s.get("change_pct") or -999, default=None)
    return JSONResponse({
        "stocks":      stocks,
        "watchlist":   WATCHLIST,
        "up":          up,
        "down":        down,
        "best_mover":  best,
        "fetched_at":  yf_data.get("fetched_at"),
        "error":       yf_data.get("error"),
    })


@app.get("/api/bonus")
async def api_bonus():
    bonuses = _load(DATA_DIR / "bonus_alerts_sent.json")
    if not isinstance(bonuses, dict):
        bonuses = {}
    return JSONResponse({
        "last_scan":   bonuses.get("last_scan"),
        "last_count":  bonuses.get("last_count", 0),
        "last_alert":  bonuses.get("last_alert"),
        "last_offers": bonuses.get("last_offers", []),
    })


@app.get("/api/social")
async def api_social():
    cache = _load(DATA_DIR / "social_cache.json")
    if isinstance(cache, dict) and cache.get("events"):
        return JSONResponse(cache)
    return JSONResponse({"events": [], "cached_at": None, "note": "Run a social scan via Telegram or action button"})


@app.get("/api/mortgage")
async def api_mortgage():
    cache = _load(DATA_DIR / "mortgage_cache.json")
    if isinstance(cache, dict) and cache.get("listings"):
        return JSONResponse(cache)
    return JSONResponse({"listings": [], "last_scan": None, "note": "Run a Paperstac scan via Telegram"})


@app.get("/api/travel")
async def api_travel():
    try:
        from agents.travel_agent.handler import get_status
        return JSONResponse(get_status())
    except Exception as e:
        return JSONResponse({"live": False, "error": str(e)})


@app.get("/api/tasks")
async def api_tasks():
    tasks = _load(DATA_DIR / "tasks.json")
    if not isinstance(tasks, list): tasks = []
    open_tasks = [t for t in tasks if t.get("status") == "open"]
    return JSONResponse({"open": open_tasks, "total": len(tasks)})


@app.get("/api/followups")
async def api_followups():
    try:
        from core.followups import list_all_pending
        pending = list_all_pending()
        today   = datetime.date.today().isoformat()
        overdue  = [f for f in pending if f.get("due_date","") <= today]
        upcoming = [f for f in pending if f.get("due_date","") >  today]
        return JSONResponse({"pending": pending, "overdue": overdue, "upcoming": upcoming})
    except Exception:
        return JSONResponse({"pending": [], "overdue": [], "upcoming": []})


@app.get("/api/calendar")
async def api_calendar():
    try:
        from integrations.google.calendar_client import list_events, get_todays_events
        from integrations.google.auth import is_configured
        if not is_configured():
            return JSONResponse({"events": [], "configured": False})
        events = list_events(days_ahead=7)
        today  = datetime.date.today().isoformat()
        tom    = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        today_count = sum(1 for e in events if (e.get("start",{}).get("dateTime","") or e.get("start",{}).get("date",""))[:10] == today)
        tom_count   = sum(1 for e in events if (e.get("start",{}).get("dateTime","") or e.get("start",{}).get("date",""))[:10] == tom)

        # Slim down to useful fields only
        slim = []
        for e in events[:15]:
            slim.append({
                "summary":    e.get("summary", "Untitled"),
                "start":      e.get("start",  {}),
                "end":        e.get("end",    {}),
                "location":   e.get("location",""),
                "html_link":  e.get("htmlLink",""),
                "description":e.get("description","")[:120] if e.get("description") else "",
            })
        return JSONResponse({"events": slim, "configured": True,
                             "today_count": today_count, "tomorrow_count": tom_count})
    except Exception as e:
        return JSONResponse({"events": [], "error": str(e)})


@app.get("/api/email")
async def api_email():
    try:
        from integrations.google.gmail_client import list_unread
        from integrations.google.auth import is_configured

        accounts = []
        total = 0

        for account_key, address in [("primary", "jynpriority@gmail.com"), ("secondary", "jngai5.3@gmail.com")]:
            if not is_configured(account_key):
                continue
            try:
                raw = list_unread(max_results=20, account=account_key)
                enriched = []
                for m in raw:
                    urgency = _email_urgency(m.get("subject",""), m.get("snippet",""), m.get("from",""))
                    enriched.append({**m, "urgency": urgency})
                # Sort: urgent first
                enriched.sort(key=lambda x: -x["urgency"])
                accounts.append({"address": address, "unread": enriched, "count": len(enriched)})
                total += len(enriched)
            except Exception:
                accounts.append({"address": address, "unread": [], "count": 0, "error": True})

        urgent = sum(1 for a in accounts for m in a["unread"] if m.get("urgency") == 2)
        return JSONResponse({"accounts": accounts, "total_count": total, "urgent_count": urgent, "configured": True})
    except Exception as e:
        return JSONResponse({"accounts": [], "total_count": 0, "error": str(e), "configured": False})


# ── Action endpoints ───────────────────────────────────────────────────────────

@app.post("/api/action/{action_name}")
async def api_action(action_name: str):
    """Trigger an agent action from the dashboard."""
    import time
    token = os.environ.get("DASHBOARD_TOKEN")
    # Token check is optional — skip if not configured (localhost-only deployment)

    t0 = time.time()
    try:
        if action_name == "bonus_scan":
            from agents.bonus_alert.handler import run_bonus_scan
            result = await _run_sync(run_bonus_scan, force=True)
        elif action_name == "social_scan":
            from agents.social_agent.handler import run_event_scan
            result = await _run_sync(run_event_scan)
        elif action_name == "mortgage_scan":
            from agents.mortgage_note_agent.handler import handle as mortgage_handle
            result = await _run_sync(mortgage_handle, "scan for deals")
        elif action_name == "briefing":
            from agents.calendar_agent.handler import run_morning_briefing
            result = await _run_sync(run_morning_briefing)
        elif action_name == "ping":
            result = "pong"
        else:
            raise HTTPException(status_code=404, detail=f"Unknown action: {action_name}")

        return JSONResponse({
            "success": True,
            "action": action_name,
            "result": str(result)[:500] if result else "Done",
            "duration_ms": round((time.time() - t0) * 1000),
        })
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "success": False, "action": action_name, "error": str(e),
            "duration_ms": round((time.time() - t0) * 1000),
        })


async def _run_sync(fn, *args, **kwargs):
    """Run a synchronous function in a thread pool so it doesn't block FastAPI."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))


# ── Status helpers (lightweight, no LLM, used by /api/summary) ────────────────

def _health_status():
    logs = _load(DATA_DIR / "health.json")
    if not isinstance(logs, list): logs = []
    today    = datetime.date.today().isoformat()
    week_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    today_logs  = [l for l in logs if l.get("date","")[:10] == today]
    meals       = [l for l in today_logs if l.get("metric") == "meal"]
    workouts_wk = [l for l in logs if l.get("date","")[:10] >= week_ago and l.get("metric") == "workout"]
    weights     = [l for l in logs if l.get("metric") == "weight"]
    return {
        "label":       "Health",
        "icon":        "💪",
        "status":      "ok" if len(workouts_wk) >= 3 else "warn",
        "summary":     f"{len(meals)} meals today · {len(workouts_wk)}/4 workouts",
        "last_weight": f"{weights[-1].get('value','—')} lbs" if weights else "—",
        "weight_goal": "165 lbs",
    }


def _finance_status():
    bonuses = _load(DATA_DIR / "bonus_alerts_sent.json")
    last_scan = bonuses.get("last_scan","") if isinstance(bonuses, dict) else ""
    last_count = bonuses.get("last_count", 0) if isinstance(bonuses, dict) else 0
    summary = f"Last scan {_days_ago(last_scan[:10])}" if last_scan else "Daily scan 8 AM ET"
    if last_count:
        summary += f" · {last_count} offers"
    return {"label": "Finance", "icon": "💰", "status": "ok", "summary": summary}


def _market_status():
    et = _et_now()
    h, m, wd = et.hour, et.minute, et.weekday()
    if wd >= 5:
        session, color = "Closed — Weekend", "gray"
    elif h < 9 or (h == 9 and m < 30):
        session, color = "Pre-Market", "yellow"
    elif (h == 9 and m >= 30) or (10 <= h < 16):
        session, color = "Market Open", "green"
    else:
        session, color = "After-Hours", "orange"
    return {"label": "Market", "icon": "📈", "status": color, "summary": session}


def _calendar_status():
    try:
        from integrations.google.calendar_client import get_todays_events
        from integrations.google.auth import is_configured
        if not is_configured():
            return {"label": "Calendar", "icon": "📅", "status": "gray", "summary": "Not connected"}
        events = get_todays_events()
        if events:
            return {"label": "Calendar", "icon": "📅", "status": "ok",
                    "summary": f"{len(events)} event(s) today",
                    "next": events[0].get("summary","")[:35]}
        return {"label": "Calendar", "icon": "📅", "status": "ok", "summary": "No events today"}
    except Exception:
        return {"label": "Calendar", "icon": "📅", "status": "gray", "summary": "Unavailable"}


def _email_status():
    try:
        from integrations.google.gmail_client import list_unread
        from integrations.google.auth import is_configured
        if not is_configured():
            return {"label": "Email", "icon": "📧", "status": "gray", "summary": "Not connected"}
        # Combine both accounts for status
        total = 0
        urgent = 0
        for acct in ["primary", "secondary"]:
            if is_configured(acct):
                try:
                    emails = list_unread(max_results=30, account=acct)
                    total += len(emails)
                    urgent += sum(1 for e in emails
                                  if _email_urgency(e.get("subject",""), e.get("snippet",""), e.get("from","")) == 2)
                except Exception:
                    pass
        label  = f"{total}+" if total >= 60 else str(total)
        status = "warn" if urgent > 0 else ("ok" if total < 20 else "warn")
        summary = f"{label} unread"
        if urgent:
            summary += f" · {urgent} 🔴 urgent"
        return {"label": "Email", "icon": "📧", "status": status, "summary": summary}
    except Exception:
        return {"label": "Email", "icon": "📧", "status": "gray", "summary": "Unavailable"}


def _travel_status():
    try:
        from agents.travel_agent.handler import get_status
        s = get_status()
        if not s.get("live"):
            return {"label": "Travel", "icon": "✈️", "status": "gray", "summary": "No scan data yet"}
        parts = []
        if s.get("steals"): parts.append(f"🔥 {s['steals']} steal{'s' if s['steals']>1 else ''}")
        if s.get("alerts"): parts.append(f"🔔 {s['alerts']} deal{'s' if s['alerts']>1 else ''}")
        if s.get("awards"): parts.append(f"✨ {s['awards']} award")
        last   = _days_ago(s["last_updated"][:10]) if s.get("last_updated") else "—"
        status = "warn" if s.get("steals") else "ok"
        return {"label": "Travel", "icon": "✈️", "status": status,
                "summary": ", ".join(parts) if parts else "No deals this scan",
                "last_scan": last, "deals": s.get("deals", [])[:4]}
    except Exception:
        return {"label": "Travel", "icon": "✈️", "status": "gray", "summary": "Unavailable"}


def _followup_status():
    try:
        from core.followups import list_all_pending
        pending = list_all_pending()
        today   = datetime.date.today().isoformat()
        overdue = [f for f in pending if f.get("due_date","") <= today]
        status  = "warn" if overdue else "ok"
        summary = f"{len(overdue)} overdue · {len(pending)} total" if pending else "None pending"
        return {"label": "Follow-ups", "icon": "🔔", "status": status, "summary": summary,
                "overdue": overdue[:3]}
    except Exception:
        return {"label": "Follow-ups", "icon": "🔔", "status": "ok", "summary": "None pending"}


def _bonus_status():
    bonuses   = _load(DATA_DIR / "bonus_alerts_sent.json")
    last      = bonuses.get("last_scan","")   if isinstance(bonuses, dict) else ""
    last_count= bonuses.get("last_count", 0)  if isinstance(bonuses, dict) else 0
    summary   = f"Last scan {_days_ago(last[:10])}" if last else "Daily 8 AM ET"
    if last_count:
        summary += f" · {last_count} elevated"
    return {"label": "Bonus Alerts", "icon": "🎯", "status": "ok", "summary": summary}


def _social_status():
    cache = _load(DATA_DIR / "social_cache.json")
    if isinstance(cache, dict) and cache.get("events"):
        count = len(cache["events"])
        cached_at = cache.get("cached_at","")
        return {"label": "Social", "icon": "🎉", "status": "ok",
                "summary": f"{count} events cached · {_days_ago(cached_at[:10]) if cached_at else '—'}"}
    return {"label": "Social", "icon": "🎉", "status": "gray", "summary": "Tue/Fri 9 AM auto-scan"}


def _mortgage_status():
    cache = _load(DATA_DIR / "mortgage_cache.json")
    if isinstance(cache, dict) and cache.get("listings"):
        count = len(cache["listings"])
        strong = sum(1 for l in cache["listings"] if l.get("rating","").upper() == "STRONG")
        return {"label": "Mortgage", "icon": "🏠", "status": "ok",
                "summary": f"{count} listings · {strong} STRONG"}
    return {"label": "Mortgage", "icon": "🏠", "status": "gray", "summary": "Ask to scan Paperstac"}


def _infusion_status():
    return {"label": "Infusion", "icon": "🏥", "status": "ok", "summary": "Ops intel on demand"}


def _investment_status():
    yf = _yf_cache.get("data", {})
    stocks = yf.get("stocks", [])
    if not stocks:
        return {"label": "Invest", "icon": "📊", "status": "gray", "summary": "6 stocks · tap to load"}
    movers = [s for s in stocks if s.get("change_pct") is not None]
    up   = sum(1 for s in movers if s["change_pct"] >= 0)
    down = sum(1 for s in movers if s["change_pct"] < 0)
    best = max(movers, key=lambda s: abs(s["change_pct"]), default=None)
    summary = f"{up} ▲ {down} ▼ today" if movers else "6 stocks · prices loading"
    if best:
        sign = "+" if best["change_pct"] >= 0 else ""
        summary += f" · {best['ticker']} {sign}{best['change_pct']}%"
    return {"label": "Invest", "icon": "📊", "status": "ok", "summary": summary}


# ── Serve frontend ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse((STATIC_DIR / "index.html").read_text())


# ── Runner ─────────────────────────────────────────────────────────────────────

def start(port: int = 8080):
    """Start uvicorn in a background daemon thread."""
    import threading, uvicorn
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    return t
