"""
Infusion Agent — wraps the existing infusion-agent at ../infusion-agent/agent.py
Handles consulting questions, lead intelligence, and speaking opportunity analysis.
"""

import os
import sys
from pathlib import Path
from anthropic import Anthropic

# Pull in the system prompt from the existing standalone agent
INFUSION_SYSTEM = """You are the personal intelligence and advisory agent for Justin Ngai,
an independent Hospital Infusion Operations consultant.

JUSTIN'S PROFILE:
- Specialty: Hospital Infusion Operations Consulting
- Expertise: Chair utilization, 340B compliance, prior auth, revenue cycle, EHR workflow
- Goal: Expand client base nationally through quiet, targeted outreach
- Seeking: Paid speaking opportunities at healthcare conferences
- CRITICAL: Justin cannot be publicly visible as a consultant — he has a full-time job.

YOUR ROLES:
1. LEAD INTELLIGENCE — identify hospitals needing infusion ops help
2. SPEAKING OPPORTUNITY FINDER — identify CFP deadlines
3. OPERATIONAL ADVISOR — answer ops questions with benchmarks
4. PROPOSAL WRITER — help draft SOWs, gap assessments, recommendation memos

Keep answers concise for a mobile interface. Flag HIGH/MEDIUM/LOW priority."""


def handle(message: str) -> str:
    """Answer an infusion consulting question."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        system=INFUSION_SYSTEM,
        messages=[{"role": "user", "content": message}],
    )
    return resp.content[0].text
