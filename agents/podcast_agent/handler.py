"""
Podcast Agent — Main Orchestrator
Generates the daily Justin Brief episode and publishes it everywhere.

Flow:
  1. Gather live news (RSS + Tavily)
  2. Generate script segment-by-segment (Groq)
  3. Convert to audio (OpenAI TTS if key present, else edge-tts)
  4. Save to data/podcast/audio/
  5. Register episode + regenerate RSS feed
  6. Send to Telegram (audio file + show notes)
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import sources, script_generator, audio, rss_feed

logger = logging.getLogger(__name__)

AUDIO_DIR = Path(__file__).parent.parent.parent / "data" / "podcast" / "audio"
ET_TZ = ZoneInfo("America/New_York")
PODCAST_PORT = int(os.getenv("PODCAST_PORT", 8765))


def _get_base_url() -> str:
    """Return the base URL for the podcast server."""
    host = os.getenv("PODCAST_HOST", "")
    if host:
        return host.rstrip("/")
    # Try to get local network IP
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return f"http://{local_ip}:{PODCAST_PORT}"
    except Exception:
        return f"http://localhost:{PODCAST_PORT}"


def _estimate_duration(audio_path: str) -> int:
    """Estimate MP3 duration in seconds from file size (rough: ~16KB/s for 128kbps)."""
    try:
        size = os.path.getsize(audio_path)
        return int(size / 16000)
    except Exception:
        return 0


def _build_show_notes(date_str: str, script: str) -> str:
    """Extract segment summaries from script to use as Telegram/RSS show notes."""
    import re
    segments = re.findall(r'\[SEGMENT:\s*([^\]]+)\]\s*(.*?)(?=\[SEGMENT:|$)', script, re.DOTALL)
    notes = []
    segment_icons = {
        "INTRO": "👋",
        "FINANCE AND MARKETS": "📈",
        "HEALTHCARE AND INFUSION OPS": "🏥",
        "TECH AND INNOVATION": "🤖",
        "TRAVEL AND POINTS": "✈️",
        "EDUCATIONAL DEEP DIVE": "📚",
        "OUTRO": "",
    }
    for name, content in segments:
        name = name.strip()
        if name == "OUTRO":
            continue
        icon = segment_icons.get(name, "•")
        # Take first sentence of segment as summary
        first_sentence = content.strip().split(".")[0].strip()[:120]
        if first_sentence:
            notes.append(f"{icon} *{name.title()}*: {first_sentence}...")

    return "\n".join(notes)


async def run_daily_podcast(bot=None, chat_id: str = None):
    """
    Main entry point — called by APScheduler at 8:30 AM ET.
    Can also be called manually for testing.
    """
    now = datetime.now(ET_TZ)
    date_str = now.strftime("%Y-%m-%d")
    date_display = now.strftime("%A, %B %-d, %Y")
    day_of_week = now.strftime("%A")
    filename = f"justin_brief_{now.strftime('%Y%m%d')}.mp3"
    audio_path = str(AUDIO_DIR / filename)
    episode_title = f"The Justin Brief — {date_display}"

    logger.info(f"Starting daily podcast generation for {date_str}")

    if bot and chat_id:
        await bot.send_message(
            chat_id=chat_id,
            text=f"🎙 Generating today's Justin Brief ({date_display})...",
        )

    # 1. Gather news
    logger.info("Gathering news sources...")
    news_data = sources.gather_all()

    # 2. Generate script
    logger.info("Generating podcast script...")
    script = script_generator.generate_script(date_display, day_of_week, news_data)
    clean_text = script_generator.clean_for_tts(script)
    word_count = len(clean_text.split())
    logger.info(f"Script ready: {word_count} words")

    # 3. Generate audio
    logger.info("Generating audio...")
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    audio.generate_audio(clean_text, audio_path)
    duration = _estimate_duration(audio_path)
    file_size_mb = os.path.getsize(audio_path) / 1024 / 1024
    logger.info(f"Audio ready: {file_size_mb:.1f} MB, ~{duration//60}m{duration%60}s")

    # 4. Register episode + rebuild RSS feed
    show_notes = _build_show_notes(date_str, script)
    episode = rss_feed.add_episode(
        date_str=date_str,
        title=episode_title,
        description=show_notes.replace("*", ""),
        audio_filename=filename,
        script=script,
        duration_seconds=duration,
    )
    base_url = _get_base_url()
    rss_feed.build_feed(base_url)
    feed_url = f"{base_url}/feed.xml"
    archive_url = base_url
    logger.info(f"RSS feed updated: {feed_url}")

    # 5. Send to Telegram
    if bot and chat_id:
        telegram_caption = (
            f"🎙 *{episode_title}*\n\n"
            f"{show_notes}\n\n"
            f"📡 [Full Archive & RSS]({archive_url})"
        )
        with open(audio_path, "rb") as f:
            await bot.send_audio(
                chat_id=chat_id,
                audio=f,
                title=episode_title,
                performer="The Justin Brief",
                caption=telegram_caption,
                parse_mode="Markdown",
            )
        logger.info("Episode sent to Telegram")

    return {
        "date": date_str,
        "title": episode_title,
        "audio_path": audio_path,
        "feed_url": feed_url,
        "archive_url": archive_url,
        "word_count": word_count,
        "duration_seconds": duration,
    }


def handle(message: str) -> str:
    """Handle manual trigger from Telegram (e.g. 'generate podcast')."""
    return "Podcast generation triggered — check back in ~2 minutes for today's episode."
