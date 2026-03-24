"""
Dashboard — /dashboard command for the Executive AI Assistant.

Main hub shows all agents with live status. Tap an agent to drill into
its mini-dashboard. Back button returns to the hub.

All status reads come from local data files — no LLM calls, so it's fast.
"""

import json
import datetime
from pathlib import Path
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

DATA_DIR = Path(__file__).parent.parent.parent / "data"

# ── Agent registry — order controls dashboard layout ─────────────────────────

AGENTS = [
    {"key": "health",    "emoji": "💪", "label": "Health"},
    {"key": "finance",   "emoji": "💰", "label": "Finance"},
    {"key": "market",    "emoji": "📈", "label": "Market"},
    {"key": "calendar",  "emoji": "📅", "label": "Calendar"},
    {"key": "email",     "emoji": "📧", "label": "Email"},
    {"key": "social",    "emoji": "🎉", "label": "Social"},
    {"key": "travel",    "emoji": "✈️",  "label": "Travel"},
    {"key": "mortgage",  "emoji": "🏠", "label": "Mortgage Notes"},
    {"key": "infusion",  "emoji": "🏥", "label": "Infusion"},
    {"key": "followup",  "emoji": "🔔", "label": "Follow-ups"},
    {"key": "bonus",     "emoji": "🎯", "label": "Bonus Alerts"},
]


# ── Data helpers ──────────────────────────────────────────────────────────────

def _load_json(path: Path) -> list | dict:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return []


def _days_ago(iso: str) -> str:
    """Return human-readable 'X days ago' or 'today' from ISO date string."""
    try:
        d = datetime.date.fromisoformat(iso[:10])
        delta = (datetime.date.today() - d).days
        if delta == 0:
            return "today"
        elif delta == 1:
            return "yesterday"
        else:
            return f"{delta}d ago"
    except Exception:
        return "—"


def _et_now() -> datetime.datetime:
    et = datetime.timezone(datetime.timedelta(hours=-5))
    return datetime.datetime.now(tz=et)


# ── Per-agent status (one-liner for main hub) ─────────────────────────────────

def _health_oneliner() -> str:
    logs = _load_json(DATA_DIR / "health.json")
    if not isinstance(logs, list) or not logs:
        return "No data yet"
    today = datetime.date.today().isoformat()
    today_logs = [l for l in logs if l.get("date", "")[:10] == today]
    meals = sum(1 for l in today_logs if l.get("metric") == "meal")
    weights = [l for l in logs if l.get("metric") == "weight"]
    last_weight = weights[-1].get("value", "—") if weights else "—"
    return f"{meals} meals logged today · last weight {last_weight} lbs"


def _finance_oneliner() -> str:
    profile = _load_json(DATA_DIR / "financial_profile.json")
    if isinstance(profile, dict) and profile.get("last_updated"):
        return f"Profile updated {_days_ago(profile['last_updated'])}"
    bonuses = _load_json(DATA_DIR / "bonus_alerts_sent.json")
    if isinstance(bonuses, dict) and bonuses.get("last_scan"):
        return f"Bonus scan {_days_ago(bonuses['last_scan'])}"
    return "Ready"


def _market_oneliner() -> str:
    et = _et_now()
    hour, minute = et.hour, et.minute
    weekday = et.weekday()
    if weekday >= 5:
        return "Markets closed (weekend)"
    if hour < 9 or (hour == 9 and minute < 30):
        return f"Pre-market · opens 9:30 AM ET"
    elif (hour == 9 and minute >= 30) or (10 <= hour < 16):
        return "Market open · ask for analysis"
    else:
        return "After-hours · ask for recap"


def _calendar_oneliner() -> str:
    try:
        from integrations.google.calendar_client import get_todays_events
        from integrations.google.auth import is_configured
        if not is_configured():
            return "Not connected"
        events = get_todays_events()
        if events:
            next_evt = events[0]
            name = next_evt.get("summary", "Untitled")[:30]
            return f"{len(events)} event(s) today · next: {name}"
        return "No events today"
    except Exception:
        return "Ask me about your calendar"


def _email_oneliner() -> str:
    try:
        from integrations.google.gmail_client import list_unread
        from integrations.google.auth import is_configured
        if not is_configured():
            return "Not connected"
        emails = list_unread(max_results=1)
        # The API doesn't expose a count directly — use a rough check
        all_emails = list_unread(max_results=50)
        count = len(all_emails)
        return f"{count}+ unread emails" if count == 50 else f"{count} unread emails"
    except Exception:
        return "Ask me about your email"


def _social_oneliner() -> str:
    return "Ask for NYC events · Tue/Fri auto-scan"


def _travel_oneliner() -> str:
    try:
        from agents.travel_agent.handler import get_status
        s = get_status()
        if not s["live"]:
            return "Ask about award flights or travel deals"
        parts = []
        if s["steals"]:
            parts.append(f"🔥 {s['steals']} steal{'s' if s['steals'] > 1 else ''}")
        if s["alerts"]:
            parts.append(f"🔔 {s['alerts']} deal{'s' if s['alerts'] > 1 else ''}")
        if s["awards"]:
            parts.append(f"✨ {s['awards']} award")
        if not parts:
            return "No deals this scan · Mon/Wed/Fri 8AM"
        last = _days_ago(s["last_updated"][:10]) if s.get("last_updated") else "recently"
        return ", ".join(parts) + f" · scanned {last}"
    except Exception:
        return "Ask about award flights or travel deals"


def _mortgage_oneliner() -> str:
    return "Ask to scan Paperstac for notes"


def _infusion_oneliner() -> str:
    return "Hospital infusion ops intel · ask anything"


def _followup_oneliner() -> str:
    try:
        from core.followups import list_all_pending
        pending = list_all_pending()
        if not pending:
            return "No pending follow-ups"
        overdue = [f for f in pending if f.get("due_date", "") <= datetime.date.today().isoformat()]
        return f"{len(pending)} pending · {len(overdue)} due today"
    except Exception:
        return "No pending follow-ups"


def _bonus_oneliner() -> str:
    data = _load_json(DATA_DIR / "bonus_alerts_sent.json")
    if isinstance(data, dict) and data.get("last_scan"):
        return f"Last scan {_days_ago(data['last_scan'])} · 8 AM daily"
    return "Daily scan at 8 AM ET"


_ONELINERS = {
    "health":   _health_oneliner,
    "finance":  _finance_oneliner,
    "market":   _market_oneliner,
    "calendar": _calendar_oneliner,
    "email":    _email_oneliner,
    "social":   _social_oneliner,
    "travel":   _travel_oneliner,
    "mortgage": _mortgage_oneliner,
    "infusion": _infusion_oneliner,
    "followup": _followup_oneliner,
    "bonus":    _bonus_oneliner,
}


# ── Per-agent deep dashboard ───────────────────────────────────────────────────

def _health_dashboard() -> str:
    logs = _load_json(DATA_DIR / "health.json")
    if not isinstance(logs, list):
        logs = []

    today = datetime.date.today().isoformat()
    today_logs = [l for l in logs if l.get("date", "")[:10] == today]

    meals = [l for l in today_logs if l.get("metric") == "meal"]
    workouts = [l for l in today_logs if l.get("metric") == "workout"]

    # Last 7 days
    week_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    week_logs = [l for l in logs if l.get("date", "")[:10] >= week_ago]
    week_workouts = [l for l in week_logs if l.get("metric") == "workout"]

    # Last weight
    weights = [l for l in logs if l.get("metric") == "weight"]
    last_weight = f"{weights[-1].get('value', '—')} lbs ({_days_ago(weights[-1].get('date', '')[:10])})" if weights else "—"

    # Last sleep
    sleeps = [l for l in logs if l.get("metric") == "sleep"]
    last_sleep = f"{sleeps[-1].get('value', '—')}h ({_days_ago(sleeps[-1].get('date', '')[:10])})" if sleeps else "—"

    lines = [
        "💪 *Health Dashboard*\n",
        f"⚖️ Weight: {last_weight}  _(goal: 165 lbs)_",
        f"😴 Sleep: {last_sleep}  _(goal: 7.5h)_",
        f"🏋️ Workouts this week: {len(week_workouts)}/4",
        "",
        f"*Today ({today})*",
        f"• Meals logged: {len(meals)}",
        f"• Workout: {'✅ ' + week_workouts[-1].get('value','done')[:40] if workouts else '❌ none yet'}",
        "",
        "_Send a food photo or type 'weight 174' to log_",
    ]
    return "\n".join(lines)


def _finance_dashboard() -> str:
    profile = _load_json(DATA_DIR / "financial_profile.json")
    budget = _load_json(DATA_DIR / "budget_log.json")

    lines = ["💰 *Finance Dashboard*\n"]

    if isinstance(profile, dict) and profile:
        net_worth = profile.get("net_worth") or profile.get("estimated_net_worth", "—")
        updated = profile.get("last_updated", "")
        lines.append(f"📊 Net worth snapshot: {net_worth}")
        if updated:
            lines.append(f"   _(updated {_days_ago(updated)})_")
        lines.append("")

    if isinstance(budget, list) and budget:
        recent = budget[-5:]
        lines.append("*Recent budget logs:*")
        for entry in reversed(recent):
            amt = entry.get("amount", "")
            cat = entry.get("category", "")
            note = entry.get("note", "")[:30]
            date = _days_ago(entry.get("date", "")[:10])
            lines.append(f"• ${amt} {cat} — {note} ({date})")
        lines.append("")

    lines += [
        "*Quick actions:*",
        "• 'Best CC bonuses' → current elevated offers",
        "• 'Check Amex eligibility' → re-eligibility rules",
        "• 'Tax strategy' → optimization ideas",
        "• 'Side hustle ideas' → passive income scan",
        "",
        "_Bonus alert scan runs daily at 8 AM ET_",
    ]
    return "\n".join(lines)


def _market_dashboard() -> str:
    et = _et_now()
    lines = [
        "📈 *Market Dashboard*\n",
        f"🕐 ET time: {et.strftime('%I:%M %p %a')}",
    ]
    hour, minute, weekday = et.hour, et.minute, et.weekday()
    if weekday >= 5:
        session = "🔴 Closed (weekend)"
    elif hour < 9 or (hour == 9 and minute < 30):
        session = f"🟡 Pre-market (opens 9:30 AM)"
    elif (hour == 9 and minute >= 30) or (10 <= hour < 16):
        session = "🟢 Market open"
    else:
        session = "🟠 After-hours"
    lines.append(f"📡 Session: {session}")
    lines += [
        "",
        "*Quick actions:*",
        "• 'AAPL analysis' → single stock deep dive",
        "• 'Market briefing' → macro + sector rotation",
        "• 'Trade ideas' → actionable setups",
        "• 'Crypto update' → BTC/ETH/alts",
        "",
        "_JP Morgan style analysis · time-context aware_",
    ]
    return "\n".join(lines)


def _calendar_dashboard() -> str:
    lines = ["📅 *Calendar Dashboard*\n"]
    try:
        from integrations.google.calendar_client import list_events
        from integrations.google.auth import is_configured
        if not is_configured():
            return "📅 *Calendar Dashboard*\n\n_Google Calendar not connected._"
        events = list_events(days_ahead=7)
        if events:
            lines.append(f"*Next 7 days ({len(events)} events):*")
            for e in events[:6]:
                name = e.get("summary", "Untitled")[:35]
                start = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", "")
                if "T" in start:
                    dt = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
                    label = dt.strftime("%a %b %-d %-I:%M %p")
                else:
                    label = start
                lines.append(f"• {label} — {name}")
        else:
            lines.append("_No events in the next 7 days_")
    except Exception as e:
        lines.append(f"_Couldn't load calendar: {e}_")
    lines += ["", "_Send an event photo to auto-add · or type 'schedule...'_"]
    return "\n".join(lines)


def _email_dashboard() -> str:
    lines = ["📧 *Email Dashboard*\n"]
    try:
        from integrations.google.gmail_client import list_unread
        from integrations.google.auth import is_configured
        if not is_configured():
            return "📧 *Email Dashboard*\n\n_Gmail not connected._"
        emails = list_unread(max_results=50)
        count = len(emails)
        label = f"{count}+" if count == 50 else str(count)
        lines.append(f"📬 Unread emails: *{label}*")
        if emails:
            lines.append("")
            lines.append("*Recent unread:*")
            for msg in emails[:4]:
                sender = msg.get("from", "Unknown")[:25]
                subject = msg.get("subject", "(no subject)")[:35]
                lines.append(f"• {sender} — {subject}")
    except Exception as e:
        lines.append(f"_Could not fetch emails: {e}_")
    lines += [
        "",
        "*Quick actions:*",
        "• 'Show urgent emails' → triaged digest",
        "• 'Draft email to [name] about [topic]' → AI draft",
        "• 'Send email to...' → compose + send",
        "",
        "_Morning digest at 7:50 AM · EOD summary at 6 PM_",
    ]
    return "\n".join(lines)


def _social_dashboard() -> str:
    return (
        "🎉 *Social / NYC Events Dashboard*\n\n"
        "Auto-scan runs:\n"
        "• 🔔 Tuesdays 9 AM — alert-only (hot events)\n"
        "• 📋 Fridays 9 AM — full weekly roundup\n\n"
        "*Quick actions:*\n"
        "• 'NYC events this weekend' → on-demand scan\n"
        "• 'Networking events in finance' → targeted search\n"
        "• 'What's happening this week' → full roundup\n\n"
        "_Sources: Luma, Eventbrite, Meetup, X, Instagram_"
    )


def _travel_dashboard() -> str:
    lines = ["✈️ *Travel Dashboard*\n"]
    try:
        from agents.travel_agent.handler import get_status
        s = get_status()

        if s["live"]:
            last = _days_ago(s["last_updated"][:10]) if s.get("last_updated") else "recently"
            lines.append(f"🔄 Last scan: {last} · Mon/Wed/Fri 8AM EST")
            lines.append(f"Routes: EWR/JFK → Tokyo, Seoul, Bangkok, London, Paris, Rome, Cancun, Dubai")
            lines.append("")

            if s["steals"] or s["alerts"] or s["awards"]:
                summary_parts = []
                if s["steals"]: summary_parts.append(f"🔥 {s['steals']} steal{'s' if s['steals']>1 else ''}")
                if s["alerts"]: summary_parts.append(f"🔔 {s['alerts']} deal{'s' if s['alerts']>1 else ''}")
                if s["awards"]: summary_parts.append(f"✨ {s['awards']} award")
                if s["below"]:  summary_parts.append(f"— {s['below']} below threshold")
                lines.append("*Current scan results:* " + " · ".join(summary_parts))
                lines.append("")

                top_deals = s["deals"][:5]
                if top_deals:
                    lines.append("*Top deals:*")
                    for d in top_deals:
                        badge = "🔥" if d.get("priority") == "steal" else "🔔" if d.get("priority") == "alert" else "✨"
                        route = d.get("route", "?")
                        price = d.get("price", "?")
                        meta  = (d.get("meta") or "")[:40]
                        pct   = f" ({d.get('pctUnder',0)}% under)" if d.get("pctUnder", 0) > 0 else ""
                        lines.append(f"{badge} {route} — {price}{pct}")
                        if meta:
                            lines.append(f"   _{meta}_")
                lines.append("")
            else:
                lines.append("_No deals meeting thresholds this scan_")
                lines.append("")
        else:
            lines.append("_Live data unavailable — flight-tracker may be setting up_")
            lines.append("")
    except Exception as e:
        lines.append(f"_Could not load live data: {e}_")
        lines.append("")

    lines += [
        "*Quick actions:*",
        "• 'Flight deals' → current scan summary",
        "• 'Award flights to Tokyo' → miles/points search",
        "• 'Best use of Chase points' → redemption strategy",
        "• 'Transfer bonus Chase to United' → check transfer deals",
        "• Send a flight screenshot → deal evaluation",
        "",
        "_Tracker: github.com/jng-ai/flight-tracker_",
        "_Programs: Alaska · AAdvantage · Amex MR · Chase UR · Cathay · United_",
    ]
    return "\n".join(lines)


def _mortgage_dashboard() -> str:
    return (
        "🏠 *Mortgage Notes Dashboard*\n\n"
        "*Quick actions:*\n"
        "• 'Scan Paperstac' → scrape performing/first-lien notes\n"
        "• 'Show me notes under $50k UPB' → filtered scan\n"
        "• 'Underwrite [address]' → quick note analysis\n\n"
        "_Playwright scraper · Paperstac login required_\n"
        "_Filters: performing notes · first lien only_"
    )


def _infusion_dashboard() -> str:
    return (
        "🏥 *Infusion Consulting Dashboard*\n\n"
        "*Quick actions:*\n"
        "• Ask about infusion center operations\n"
        "• 'Consulting leads in [city]' → hospital pipeline\n"
        "• Send a data table or report → analysis\n"
        "• 'Speaking opportunities' → conference/webinar leads\n\n"
        "_Quiet from employer · infusion ops intel_"
    )


def _followup_dashboard() -> str:
    lines = ["🔔 *Follow-ups Dashboard*\n"]
    try:
        from core.followups import list_all_pending
        pending = list_all_pending()
        today = datetime.date.today().isoformat()
        if not pending:
            lines.append("_No pending follow-ups_ ✅")
        else:
            overdue = [f for f in pending if f.get("due_date", "") <= today]
            upcoming = [f for f in pending if f.get("due_date", "") > today]
            if overdue:
                lines.append(f"*⚠️ Due today/overdue ({len(overdue)}):*")
                for f in overdue[:5]:
                    lines.append(f"• #{f['id']} {f.get('contact','?')} — {f.get('context','')[:40]}")
                lines.append("")
            if upcoming:
                lines.append(f"*📅 Upcoming ({len(upcoming)}):*")
                for f in upcoming[:5]:
                    due = f.get("due_date", "")[:10]
                    lines.append(f"• #{f['id']} {due} · {f.get('contact','?')} — {f.get('context','')[:35]}")
    except Exception as e:
        lines.append(f"_Error loading follow-ups: {e}_")
    lines += ["", "_'Follow up with X in 3 days' to schedule_"]
    return "\n".join(lines)


def _bonus_dashboard() -> str:
    lines = ["🎯 *Bonus Alerts Dashboard*\n"]
    data = _load_json(DATA_DIR / "bonus_alerts_sent.json")
    if isinstance(data, dict):
        last_scan = data.get("last_scan", "")
        if last_scan:
            lines.append(f"🔍 Last scan: {_days_ago(last_scan)}")
        alerts_today = data.get("alerts_sent_today", 0)
        if alerts_today:
            lines.append(f"🚨 Alerts sent today: {alerts_today}")
    lines += [
        "",
        "*Sources:* Doctor of Credit · Frequent Miler · r/churning",
        "",
        "*Quick actions:*",
        "• 'Force bonus scan' → run now",
        "• 'Best bank bonuses' → current elevated offers",
        "• 'Check Amex elevated offer' → specific card scan",
        "",
        "_Auto-scan daily at 8 AM ET · alerts only when elevated_",
    ]
    return "\n".join(lines)


_DASHBOARDS = {
    "health":   _health_dashboard,
    "finance":  _finance_dashboard,
    "market":   _market_dashboard,
    "calendar": _calendar_dashboard,
    "email":    _email_dashboard,
    "social":   _social_dashboard,
    "travel":   _travel_dashboard,
    "mortgage": _mortgage_dashboard,
    "infusion": _infusion_dashboard,
    "followup": _followup_dashboard,
    "bonus":    _bonus_dashboard,
}


# ── Keyboard builders ─────────────────────────────────────────────────────────

def build_main_keyboard() -> InlineKeyboardMarkup:
    """2-column grid of agent buttons."""
    buttons = []
    row = []
    for agent in AGENTS:
        btn = InlineKeyboardButton(
            f"{agent['emoji']} {agent['label']}",
            callback_data=f"dash:{agent['key']}"
        )
        row.append(btn)
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def build_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("← Back to Dashboard", callback_data="dash:__main__")
    ]])


# ── Public API ────────────────────────────────────────────────────────────────

def build_main_dashboard() -> tuple[str, InlineKeyboardMarkup]:
    """Returns (text, keyboard) for the main hub."""
    lines = ["*Executive AI Dashboard* 🤖\n"]
    for agent in AGENTS:
        key = agent["key"]
        emoji = agent["emoji"]
        label = agent["label"]
        try:
            status = _ONELINERS[key]()
        except Exception:
            status = "—"
        lines.append(f"{emoji} *{label}* — {status}")

    lines.append("\n_Tap an agent to drill in_")
    return "\n".join(lines), build_main_keyboard()


def build_agent_dashboard(agent_key: str) -> tuple[str, InlineKeyboardMarkup]:
    """Returns (text, keyboard) for a specific agent's dashboard."""
    fn = _DASHBOARDS.get(agent_key)
    if fn:
        try:
            text = fn()
        except Exception as e:
            text = f"⚠️ Couldn't load dashboard: {e}"
    else:
        text = f"⚠️ Unknown agent: {agent_key}"
    return text, build_back_keyboard()
