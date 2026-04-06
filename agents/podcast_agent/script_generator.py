"""
Podcast Agent — Script Generator
Produces a full spoken-word podcast script using Groq.
Each segment is generated separately to avoid truncation.
"""

import json
import os
from openai import OpenAI


def _podcast_chat(system: str, user: str, max_tokens: int = 1400) -> str:
    """
    Use llama-3.1-8b-instant for podcast generation — separate Groq rate limit
    from the main llama-3.3-70b-versatile used by all other agents.
    This prevents the podcast from burning the shared daily token budget.
    """
    client = OpenAI(
        api_key=os.environ.get("GROQ_API_KEY", ""),
        base_url="https://api.groq.com/openai/v1",
    )
    resp = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content

JUSTIN_CONTEXT = """Justin Ngai: NYP Hospital infusion director, NJ/VA real estate investor, active CC churner, Asia business class travel hacker (Alaska MP, Amex MR, Chase UR), NYC high earner W2+1099+rental."""

STYLE_RULES = """Spoken TO Justin. Casual, enthusiastic, smart friend tone. Contractions always. Natural starters: "Look...", "Here's the thing...", "Honestly,". Opinions. NO bullets. Pure prose. Hit the target word count."""

# Which RSS/search keys are relevant for each segment (keeps prompts small)
SEGMENT_DATA_KEYS = {
    "INTRO":                    [],  # no raw data, just the date
    "FINANCE AND MARKETS":      ["Doctor of Credit", "FrequentMiler", "Bigger Pockets",
                                 "US stock market economy news today",
                                 "real estate investing mortgage rates 2026",
                                 "credit card bonus deals today"],
    "HEALTHCARE AND INFUSION OPS": ["340B drug pricing program news 2026",
                                    "hospital infusion center operations technology 2026"],
    "TECH AND INNOVATION":      ["AI artificial intelligence healthcare scaling 2026",
                                 "tech AI agents innovation news today"],
    "TRAVEL AND POINTS":        ["One Mile at a Time", "FrequentMiler",
                                 "Doctor of Credit"],
    "EDUCATIONAL DEEP DIVE":    ["real estate investing mortgage rates 2026",
                                 "Bigger Pockets"],
    "OUTRO":                    [],
}

SEGMENTS = {
    "INTRO": {
        "words": 180,
        "prompt": """Write the intro (~180 words).
Warm, energetic Monday morning opener. Today's date: {date}.
Tease the 3 biggest stories today in one punchy sentence each — make them sound exciting.
End with "Let's get into it." Feel like the best morning briefing you've ever heard."""
    },
    "FINANCE AND MARKETS": {
        "words": 550,
        "prompt": """Write the Finance & Markets segment (~550 words).
Use the live data provided. Cover:
1. What the Fed rate hold means RIGHT NOW for someone with rental property mortgages
2. The return of 100% bonus depreciation — what it is, why it's back, and the immediate implication for investors
3. NYC ADU program — is it relevant for Justin's NJ condo situation? Be honest.
4. Best credit card plays THIS WEEK from DoC/FrequentMiler — Staples $200 fee-free Mastercards, any expiring transfer bonuses ending March 31, Venmo card triple rewards if relevant
Be specific with numbers. Give him an action or a watch-out at the end."""
    },
    "HEALTHCARE AND INFUSION OPS": {
        "words": 450,
        "prompt": """Write the Healthcare & Infusion Ops segment (~450 words).
Use the live data provided. Cover:
1. The 340B Rebate Model Pilot — HRSA's voluntary program shifting from upfront discounts to rebates. What does this actually mean for a hospital infusion center's cash flow, compliance burden, and drug acquisition strategy? Be specific.
2. Infusion Centers Management Summit — what's being discussed, why it matters
3. One key thing Justin should be watching or doing operationally right now
Frame it as insider intelligence for someone running a high-volume infusion program. Practical and strategic."""
    },
    "TECH AND INNOVATION": {
        "words": 380,
        "prompt": """Write the Tech & Innovation segment (~380 words).
Use the live data provided. Cover:
1. AI in healthcare 2026 — the "scaling safely" challenge. What does proper AI governance actually look like for a hospital ops leader?
2. Where AI agents are starting to create real ROI in healthcare operations specifically — prior auth, scheduling, revenue cycle. What's real vs hype right now?
3. One forward-looking tech trend Justin should be tracking to stay ahead of the curve in his field
Be opinionated. What should he actually pay attention to vs tune out?"""
    },
    "TRAVEL AND POINTS": {
        "words": 330,
        "prompt": """Write the Travel & Points segment (~330 words).
Use the live data provided. Cover:
1. ANA's new 777 routes for IATA summer 2026 — which routes now have the new cabins? Connect directly to Justin's Japan goals and Alaska Mileage Plan strategy
2. Aer Lingus free Starlink WiFi — what this signals industry-wide
3. URGENT: Transfer bonuses and 5x spending bonuses expiring March 31 (tomorrow!) — what should Justin act on TODAY?
4. Amex Platinum changes — Events With Amex removed, Uber VIP replaced. Does this change the value prop for Justin?
Make the urgency real on anything expiring."""
    },
    "EDUCATIONAL DEEP DIVE": {
        "words": 480,
        "prompt": """Write the Educational Deep Dive segment (~480 words).
Topic: "100% Bonus Depreciation Is Back — Here's Your Playbook"
Structure this as a genuinely educational explainer:
1. Quick history: what bonus depreciation is, how it was phased out under TCJA (100% → 80% → 60% → 40%), and why it's fully back in 2026
2. Plain English explanation of how it works — "first-year full expensing" for eligible property
3. What a cost segregation study is and why Justin should seriously consider getting one done on his NJ condo and VA townhouse
4. Three specific action steps for Justin's exact situation — account for the NJ condo (full ownership, can maximize) vs the VA townhouse (partial ownership, different dynamics)
Make this feel like a conversation with a CPA friend who actually knows his situation."""
    },
    "OUTRO": {
        "words": 110,
        "prompt": """Write the outro (~110 words).
Warm, upbeat sign-off. Reference one specific thing from today's episode as the top actionable takeaway.
End naturally — don't say "stay tuned" or "subscribe." Just sign off personally.
Final line: "This has been The Justin Brief. Have a great {day}." """
    },
}


def _build_data_snippet(seg_name: str, news_data: dict) -> str:
    """Return only the news items relevant to this segment, to keep prompt size small."""
    keys = SEGMENT_DATA_KEYS.get(seg_name, [])
    if not keys:
        return ""

    rss_bits, search_bits = [], []
    for k in keys:
        if k in news_data.get("rss", {}):
            for item in news_data["rss"][k][:2]:  # max 2 items per source
                rss_bits.append(f"[{k}] {item['title']}: {item['summary'][:200]}")
        if k in news_data.get("search", {}):
            snippet = news_data["search"][k][:400]
            if snippet:
                search_bits.append(f"[{k}] {snippet}")

    parts = []
    if rss_bits:
        parts.append("NEWS:\n" + "\n".join(rss_bits))
    if search_bits:
        parts.append("SEARCH:\n" + "\n".join(search_bits))
    return "\n\n".join(parts)


def generate_script(date: str, day_of_week: str, news_data: dict) -> str:
    import time

    system = (
        f"You are the scriptwriter for 'The Justin Brief' podcast. {STYLE_RULES} "
        f"Listener: {JUSTIN_CONTEXT} Write ONLY spoken prose for audio."
    )

    full_script_parts = []
    for i, (seg_name, seg) in enumerate(SEGMENTS.items()):
        if i > 0:
            time.sleep(2)

        data_snippet = _build_data_snippet(seg_name, news_data)
        prompt_text = seg["prompt"].format(date=date, day=day_of_week)
        user_msg = (
            f"TODAY: {date}\n\n"
            f"{data_snippet}\n\n"
            f"Write segment [{seg_name}] ~{seg['words']} words:\n{prompt_text}"
        )
        text = _podcast_chat(system, user_msg, max_tokens=1400)
        full_script_parts.append(f"[SEGMENT: {seg_name}]\n{text.strip()}")

    return "\n\n".join(full_script_parts)


def clean_for_tts(script: str) -> str:
    """Strip segment labels, leaving only spoken text."""
    import re
    text = re.sub(r"\[SEGMENT:[^\]]+\]", "", script)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
