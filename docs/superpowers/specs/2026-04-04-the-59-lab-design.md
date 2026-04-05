# The 5–9 Lab — Design Spec
**Date:** 2026-04-04
**Slogan:** Testing new hobbies, one NYC night at a time.
**URL:** the59lab.vercel.app
**Repo:** Separate from executive-ai-assistant

---

## Overview

A public community web app for discovering, sharing, and tracking NYC events — focused on expanding horizons through low-cost activities. Justin's site, shareable with friends and the broader NYC community. Designed to start with a friend group and scale.

---

## Architecture

| Layer | Service | Cost |
|---|---|---|
| Frontend + API routes | Next.js 14 (App Router) + Tailwind CSS | Free |
| Hosting | Vercel | Free |
| Auth | Clerk (magic link, 10k MAU free tier) | Free |
| Events database | Notion (shared with exec agent) | Free |
| User profiles + RSVPs | Notion | Free |
| Email notifications | Resend (3,000 emails/month free) | Free |
| Event scraping | OpenGraph + JSON-LD in Vercel API routes | Free |
| Caching | Next.js ISR (`revalidate: 300`) | Free |

**Exec agent integration:** Notion is the shared state layer. The exec agent reads/writes Notion independently. The website reads the same Notion DB. No direct HTTP calls between Vercel and the local exec agent.

---

## Required Environment Variables



```
NOTION_TOKEN=
NOTION_EVENTS_DB_ID=        # existing — from exec agent bootstrap
NOTION_USERS_DB_ID=         # new — created by 59lab bootstrap script
NOTION_ATTENDEES_DB_ID=     # new — created by 59lab bootstrap script
CLERK_PUBLISHABLE_KEY=
CLERK_SECRET_KEY=
RESEND_API_KEY=
RESEND_AUDIENCE_ID=
JUSTIN_CLERK_ID=             # used for Stats tab Justin-scoped queries
CRON_SECRET=                 # Vercel cron auth header value
```

---

## Pages & Navigation

### Header (all pages)
- Logo: **The 5–9 Lab 🧪** + slogan
- CTA button top-right: **"Join the 5–9 Lab"** → opens signup modal (shown when logged out)
- If logged in: avatar/name + logout link instead of CTA

### Tabs
Three tabs on the main page:
1. **🗓 Events** (default)
2. **📊 Stats**
3. **🔗 Submit**

---

## Tab: Events

**Category filter pills** across the top:
All · Food & Drink · Music · Fitness · Art · Comedy · Social · Dating · Outdoors · Learning

**Event cards — timeline style:**
- Large date badge (day + month)
- Event name
- Venue · Price display (see Price Rendering below) · Time
- Full address with 📍
- Badge: `Justin's Going ✓` (green) — shown when event's Notion status is `Going` AND the submitting write came from the exec agent (identified via `JUSTIN_CLERK_ID` env var matching the RSVP user)
- Badge: `🔗 Community Pick` (grey) — shown when event `Source` field is `Community`
- `👥 Marcus, Sarah + 1 going` — names from Attendees DB (Guest Name or Clerk profile name)
- **"I'm in! 🙋"** button → RSVP modal

**Price rendering rules:**
- Extract the highest numeric value from the price string via regex (`/\d+(\.\d+)?/g`)
- If highest value > 80: show `💸 High cost` warning badge
- If string is `"Free"` or `"0"` or empty: show `Free`
- If unparseable: show raw string, no warning badge

**Event cards are cached via ISR (`revalidate: 300` — 5 min TTL).** Forced revalidation triggered on new RSVP or submission via `revalidatePath('/api/events')`.

**RSVP modal:**
- Pre-filled name + email if previously stored in localStorage (`59lab_name`, `59lab_email`)
- On submit:
  1. Creates Attendees DB record: `Guest Name`, `Guest Email`, `Event` (relation), `RSVP Date`, `Attended: false`, `User: null`
  2. If user is logged in via Clerk: sets `User` relation instead of guest fields
  3. Stores name + email in localStorage for future pre-fill
  4. If logged in: activity log updated immediately

**Guest RSVP → account merge:** On first Clerk login, the post-login redirect handler (`/api/auth/post-login`) queries Attendees DB for all records where `Guest Email` matches the new user's email and `User` is null. Each matched record is updated to set the `User` relation and clear `Guest Email`/`Guest Name`. If any individual update fails, it is logged and retried on next login — partial failure does not block the session.

---

## Tab: Stats

**Data scope:** All attended/RSVP counts are filtered to the current calendar year (`RSVP Date >= Jan 1, YYYY`). Prior years remain visible in the activity log (labelled with their year) but don't count toward the current goal. Year is determined server-side from `new Date().getFullYear()`.

**Heatmap:** Each cell = one week of the year. Intensity = count of Attendees records where `Attended = true` AND `RSVP Date` falls in that week. Blue gradient: 0 = `#1e293b`, 1 = `#0369a1`, 2+ = `#38bdf8`.

**Activity log rows:** Each row sourced from Attendees DB, most recent first.
- `Attended = true` → green left bar, label "Attended — {event name}", date, category
- `Attended = false`, future event → blue left bar, label "RSVP'd — {event name}", date, category
- `Attended = false`, past event → grey left bar, label "Went? — {event name}" (prompts user to mark attended)

### Not logged in
- Justin's 2026 goal progress bar (Attendees records where `User = JUSTIN_CLERK_ID` AND `Attended = true` AND current year)
- Justin's category explorer grid (10 categories, green = attended ≥1 event in that category this year)
- Justin's activity heatmap by week (events attended per week, darker = more)
- Justin's activity log (all Attendees records for Justin, most recent first)
- Prompt at bottom: "Want to track your own NYC journey?" → **Join the 5–9 Lab**

### Logged in
- **Your** 2026 goal progress bar (same query scoped to current user's Clerk ID)
- Inline **"edit"** button next to goal number → number input (min 1, max 365). Saved to Notion Users DB on blur or Enter. Optimistic UI: update displayed immediately, revert on Notion write failure with a toast error. No debounce — save fires once on blur/Enter only.
- **Your** category explorer grid
- **Your** activity log (color-coded: green = attended, blue = RSVP'd upcoming)
- Collapsible at bottom: `"📊 See Justin's 2026 progress"` — collapsed by default, shows Justin's progress bar only

---

## Tab: Submit

1. Paste any event URL (any site)
2. Click **Fetch Event →** → Vercel API route fetches URL, extracts OpenGraph tags + JSON-LD
3. Read-only preview shown:
   - Event name
   - Date & Time
   - Location (📍 full address)
   - Price
   - Original link (↗)
4. **"✏️ Edit details"** → inline edit mode. All five fields are editable: name (required, max 120 chars), date/time (required, free text stored as-is), price (optional, free text max 20 chars), address (optional, max 200 chars), category (required, dropdown from fixed list). Submit is disabled until name + date are filled.
5. **"Submit to Community ✓"** → saves to Notion Events DB:
   - Status: `Submitted`
   - Source: `Community`
   - RSVP Link: original URL
6. Event appears on Events tab within 5 min (ISR revalidation on submit)
7. "Can't scrape? Fill in the details manually." → blank edit form

**Scraping strategy (Vercel only — no Playwright fallback in v1):**
- `fetch(url)` with a 10s timeout
- Parse `og:title`, `og:description`, `article:published_time`, JSON-LD `Event` schema
- Date/time normalization: parse with `date-fns` or `dayjs`; store as ISO 8601 in Notion Date field. If timezone is absent, assume America/New_York. If date cannot be parsed, store as empty string and require user to fill in edit mode.
- If title/date/location cannot be extracted: show blank edit form with a note "We couldn't read this page — fill in the details below"
- No exec agent scraping fallback in v1 (out of scope — keeps architecture clean)

---

## "Join the 5–9 Lab" Modal

Two distinct flows combined in one modal:

**Step 1 — Email capture (always):**
- Name field
- Email field
- Notification preferences:
  - ✅ When Justin marks Going on an event
  - ✅ New community event submissions
  - ☐ Weekly digest of upcoming events
- On submit:
  1. Add contact to Resend audience with tags: `notify_going`, `notify_submissions`, `notify_digest` based on checked boxes
  2. Create stub Notion Users record: `Name`, `Email`, `Goal: 12`, `Joined: today`, `Clerk ID: null`
  3. Save notification preferences to Users DB: `Notify Going (bool)`, `Notify Submissions (bool)`, `Notify Digest (bool)`
  4. Send Clerk magic link email via Resend

**Step 2 — Account activation (optional, async):**
- User receives magic link email
- On click: Clerk session created, post-login handler fires (`/api/auth/post-login`):
  1. Find existing stub Users DB record by email → update `Clerk ID`
  2. Run guest RSVP backfill
  3. If Users record not found (edge case): create new one
- User redirected to Stats tab showing their profile
- First login screen (Clerk-rendered): name pre-populated from stub record; goal pre-populated as 12. User can edit both. On confirm: Users DB updated. **No redundant name entry** — the join modal name is pre-filled.

If user ignores the magic link: they remain as an email subscriber only (stub Users record, no Clerk ID). They still receive notifications. They can request a new magic link at any time via the "Join the 5–9 Lab" modal.

---

## Auth (Clerk — magic link)

- No passwords. Enter email → magic link → logged in.
- Session stored in Clerk-managed cookie.
- First login: prompted to confirm name and set annual goal (default: 12 events)
- On each login: guest RSVP backfill runs if any unlinked records found

---

## Notion Data Model

### Events DB (existing, shared with exec agent)
No schema changes except one addition. Key fields used by website:
`Name`, `Date`, `End Time`, `Venue`, `Address`, `Category`, `Price`, `Source`, `RSVP Link`, `Status`, `Cal Event ID`

New field added: `Notified` (Checkbox, default false) — set to true by the notify-going cron after sending the Resend batch for that event.

`Friends Going` field on Events DB is **deprecated for the website** — the website reads attendee names from the Attendees DB instead. The exec agent may still write to `Friends Going` for its own Telegram notifications; the website ignores it.

### Users DB (new)
| Field | Type | Notes |
|---|---|---|
| Name | Title | |
| Email | Email | |
| Clerk ID | Text | null until magic link activated |
| Goal | Number | default 12 |
| Joined | Date | |
| Notify Going | Checkbox | |
| Notify Submissions | Checkbox | |
| Notify Digest | Checkbox | |

### Attendees DB (new)
| Field | Type | Notes |
|---|---|---|
| Event | Relation → Events | |
| User | Relation → Users | null for guest RSVPs |
| Guest Name | Text | populated when User is null |
| Guest Email | Text | populated when User is null |
| RSVP Date | Date | |
| Attended | Checkbox | default false; updated by exec agent or user |

---

## "Justin's Going ✓" Badge Logic

The badge is shown on an event card when:
- The event's Notion `Status` field equals `Going`

This is set exclusively by the exec agent (never by the website). No Clerk ID lookup needed at render time — `Status = Going` is sufficient. The `JUSTIN_CLERK_ID` env var is used only for the Stats tab to scope Justin's personal progress queries.

---

## Email Notifications (Resend)

| Trigger | Resend tag filter | Content |
|---|---|---|
| Justin marks Going (exec agent → Notion → webhook) | `notify_going` | Event name, date, location, "I'm in!" deep link |
| New community submission approved | `notify_submissions` | Event name + site link |
| Weekly digest (cron, Monday 8 AM ET) | `notify_digest` | Upcoming events that week |

**Trigger mechanism for "Justin Going":** The exec agent updates Notion status to `Going`. A Vercel cron job (`/api/cron/notify-going`) runs every 15 minutes, checks for events where `Status = Going` AND `Notified = false`, sends Resend batch to `notify_going` audience tag, marks `Notified = true` on each event.

**Cron security:** All cron routes (`/api/cron/*`) check the `Authorization: Bearer $CRON_SECRET` header. Vercel sets this automatically when using `vercel.json` cron config with the `CRON_SECRET` env var. Requests without a valid token return 401.

**Weekly digest content:** Monday 8 AM ET cron queries Events DB for events with `Date` in the next 7 days and `Status` in `[Going, Interested, Submitted]`. Email lists: event name, date, neighborhood, price, RSVP link. Subject: "This week in The 5–9 Lab 🧪".

---

## Caching Strategy

- Events list: ISR `revalidate: 300` (5 min)
- Stats (Justin's): ISR `revalidate: 300`
- Stats (user's): no cache — fetched server-side per request with Clerk session
- Force revalidation: `revalidatePath('/')` called after RSVP submit and event submit

**RSVP optimistic UI:** After a successful RSVP POST, the client immediately appends the submitted name to the card's attendee list in local React state without waiting for ISR revalidation. The server-side revalidation runs in the background and catches up within 300s. This means two users RSVPing simultaneously may briefly see stale counts, but the eventual consistent state is correct.

---

## XSS Protection

- All Notion-sourced string fields rendered via React JSX (escaped by default)
- `dangerouslySetInnerHTML` is banned for all Notion content
- Event descriptions are plain text only in the Notion DB (no rich text rendering)
- RSVP link URLs validated: must start with `https://` before rendering as `<a href>`

---

## Out of Scope (v1)

- Playwright auto-registration (stays in exec agent, triggered via Telegram)
- Exec agent Playwright scraping fallback for submitted events
- Comments or event reviews
- DMs between users
- Mobile app
- Payment / ticketing
- Notion `Friends Going` field sync (website uses Attendees DB; exec agent manages its own field)
