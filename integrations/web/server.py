"""
Web Dashboard Server — FastAPI app serving the executive AI dashboard.
Runs in a background thread alongside the Telegram bot.

Access: http://localhost:8080  (or via Cloudflare Tunnel for remote access)
"""

import os
import json
import datetime
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

DATA_DIR = Path(__file__).parent.parent.parent / "data"
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Executive AI Dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load(path: Path):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return [] if not path.name.endswith("profile.json") else {}


def _days_ago(iso: str) -> str:
    try:
        d = datetime.date.fromisoformat(iso[:10])
        delta = (datetime.date.today() - d).days
        if delta == 0: return "today"
        if delta == 1: return "yesterday"
        return f"{delta}d ago"
    except Exception:
        return "—"


def _et_now():
    et = datetime.timezone(datetime.timedelta(hours=-5))
    return datetime.datetime.now(tz=et)


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/summary")
async def api_summary():
    """All agent statuses in one payload — the main dashboard call."""
    et = _et_now()
    return JSONResponse({
        "server_time": et.strftime("%a %b %-d, %-I:%M %p ET"),
        "agents": {
            "health":   _health_status(),
            "finance":  _finance_status(),
            "market":   _market_status(),
            "calendar": _calendar_status(),
            "email":    _email_status(),
            "travel":   _travel_status(),
            "followup": _followup_status(),
            "bonus":    _bonus_status(),
            "social":   _social_status(),
            "mortgage": _mortgage_status(),
            "infusion": _infusion_status(),
        }
    })


@app.get("/api/health")
async def api_health():
    logs = _load(DATA_DIR / "health.json")
    if not isinstance(logs, list): logs = []
    today = datetime.date.today().isoformat()
    week_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()

    today_logs   = [l for l in logs if l.get("date","")[:10] == today]
    week_logs    = [l for l in logs if l.get("date","")[:10] >= week_ago]
    meals        = [l for l in today_logs if l.get("metric") == "meal"]
    workouts_wk  = [l for l in week_logs  if l.get("metric") == "workout"]
    weights      = [l for l in logs if l.get("metric") == "weight"]
    sleeps       = [l for l in logs if l.get("metric") == "sleep"]
    recent_logs  = sorted(logs, key=lambda x: x.get("date",""), reverse=True)[:20]

    return JSONResponse({
        "last_weight":    {"value": weights[-1].get("value","—"), "date": _days_ago(weights[-1].get("date","")[:10])} if weights else None,
        "last_sleep":     {"value": sleeps[-1].get("value","—"),  "date": _days_ago(sleeps[-1].get("date","")[:10])}  if sleeps else None,
        "meals_today":    len(meals),
        "workouts_week":  len(workouts_wk),
        "workout_goal":   4,
        "targets":        {"weight": 165, "protein": 150, "calories": 1900, "sleep": 7.5},
        "recent_logs":    recent_logs,
    })


@app.get("/api/finance")
async def api_finance():
    profile = _load(DATA_DIR / "financial_profile.json")
    budget  = _load(DATA_DIR / "budget_log.json")
    bonuses = _load(DATA_DIR / "bonus_alerts_sent.json")
    if not isinstance(budget, list): budget = []
    return JSONResponse({
        "profile_updated": _days_ago(profile.get("last_updated","")[:10]) if isinstance(profile, dict) else "—",
        "net_worth":       profile.get("net_worth") or profile.get("estimated_net_worth","—") if isinstance(profile, dict) else "—",
        "last_bonus_scan": _days_ago(bonuses.get("last_scan","")[:10]) if isinstance(bonuses, dict) else "—",
        "recent_budget":   budget[-10:] if budget else [],
    })


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
        today = datetime.date.today().isoformat()
        overdue  = [f for f in pending if f.get("due_date","") <= today]
        upcoming = [f for f in pending if f.get("due_date","") > today]
        return JSONResponse({"pending": pending, "overdue": overdue, "upcoming": upcoming})
    except Exception:
        return JSONResponse({"pending": [], "overdue": [], "upcoming": []})


@app.get("/api/calendar")
async def api_calendar():
    try:
        from integrations.google.calendar_client import list_events
        from integrations.google.auth import is_configured
        if not is_configured():
            return JSONResponse({"events": [], "configured": False})
        events = list_events(days_ahead=7)
        return JSONResponse({"events": events[:10], "configured": True})
    except Exception as e:
        return JSONResponse({"events": [], "error": str(e)})


@app.get("/api/email")
async def api_email():
    try:
        from integrations.google.gmail_client import list_unread
        from integrations.google.auth import is_configured
        if not is_configured():
            return JSONResponse({"unread": [], "configured": False})
        emails = list_unread(max_results=20)
        return JSONResponse({"unread": emails, "count": len(emails), "configured": True})
    except Exception as e:
        return JSONResponse({"unread": [], "error": str(e)})


# ── Per-agent status helpers (lightweight, no LLM) ───────────────────────────

def _health_status():
    logs = _load(DATA_DIR / "health.json")
    if not isinstance(logs, list): logs = []
    today = datetime.date.today().isoformat()
    week_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    today_logs  = [l for l in logs if l.get("date","")[:10] == today]
    meals       = [l for l in today_logs if l.get("metric") == "meal"]
    workouts_wk = [l for l in logs if l.get("date","")[:10] >= week_ago and l.get("metric") == "workout"]
    weights     = [l for l in logs if l.get("metric") == "weight"]
    return {
        "label": "Health",
        "icon": "💪",
        "status": "ok" if len(workouts_wk) >= 3 else "warn",
        "summary": f"{len(meals)} meals today · {len(workouts_wk)}/4 workouts this week",
        "last_weight": f"{weights[-1].get('value','—')} lbs" if weights else "—",
        "weight_goal": "165 lbs",
    }


def _finance_status():
    bonuses = _load(DATA_DIR / "bonus_alerts_sent.json")
    profile = _load(DATA_DIR / "financial_profile.json")
    last_scan = bonuses.get("last_scan","") if isinstance(bonuses, dict) else ""
    return {
        "label": "Finance",
        "icon": "💰",
        "status": "ok",
        "summary": f"Bonus scan {_days_ago(last_scan[:10])}" if last_scan else "Daily scan 8 AM ET",
    }


def _market_status():
    et = _et_now()
    h, m, wd = et.hour, et.minute, et.weekday()
    if wd >= 5: session, color = "Closed (weekend)", "gray"
    elif h < 9 or (h == 9 and m < 30): session, color = "Pre-market", "yellow"
    elif (h == 9 and m >= 30) or 10 <= h < 16: session, color = "Market open", "green"
    else: session, color = "After-hours", "orange"
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
                    "summary": f"{len(events)} event(s) today", "next": events[0].get("summary","")[:35]}
        return {"label": "Calendar", "icon": "📅", "status": "ok", "summary": "No events today"}
    except Exception:
        return {"label": "Calendar", "icon": "📅", "status": "gray", "summary": "Unavailable"}


def _email_status():
    try:
        from integrations.google.gmail_client import list_unread
        from integrations.google.auth import is_configured
        if not is_configured():
            return {"label": "Email", "icon": "📧", "status": "gray", "summary": "Not connected"}
        emails = list_unread(max_results=50)
        count = len(emails)
        label = f"{count}+" if count == 50 else str(count)
        status = "warn" if count > 10 else "ok"
        return {"label": "Email", "icon": "📧", "status": status, "summary": f"{label} unread"}
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
        last = _days_ago(s["last_updated"][:10]) if s.get("last_updated") else "—"
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
        today = datetime.date.today().isoformat()
        overdue = [f for f in pending if f.get("due_date","") <= today]
        status = "warn" if overdue else ("ok" if pending else "ok")
        summary = f"{len(overdue)} overdue · {len(pending)} total" if pending else "None pending"
        return {"label": "Follow-ups", "icon": "🔔", "status": status, "summary": summary, "overdue": overdue[:3]}
    except Exception:
        return {"label": "Follow-ups", "icon": "🔔", "status": "ok", "summary": "None pending"}


def _bonus_status():
    bonuses = _load(DATA_DIR / "bonus_alerts_sent.json")
    last = bonuses.get("last_scan","") if isinstance(bonuses, dict) else ""
    return {"label": "Bonus Alerts", "icon": "🎯", "status": "ok",
            "summary": f"Last scan {_days_ago(last[:10])}" if last else "Daily 8 AM ET"}


def _social_status():
    return {"label": "Social", "icon": "🎉", "status": "ok", "summary": "Tue/Fri 9 AM auto-scan"}


def _mortgage_status():
    return {"label": "Mortgage", "icon": "🏠", "status": "ok", "summary": "Ask to scan Paperstac"}


def _infusion_status():
    return {"label": "Infusion", "icon": "🏥", "status": "ok", "summary": "Ops intel on demand"}


# ── Serve frontend ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text())


# ── Runner (called from main thread) ──────────────────────────────────────────

def start(port: int = 8080):
    """Start uvicorn in a background daemon thread."""
    import threading
    import uvicorn

    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return thread
