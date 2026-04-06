"""
Podcast Agent — RSS Feed Manager
Generates and maintains a valid podcast RSS 2.0 feed (Apple Podcasts compatible).
Episodes stored in data/podcast/episodes.json, audio in data/podcast/audio/.
"""

import json
import os
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent
import xml.etree.ElementTree as ET

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "podcast"
EPISODES_FILE = DATA_DIR / "episodes.json"
FEED_FILE = DATA_DIR / "feed.xml"
AUDIO_DIR = DATA_DIR / "audio"

PODCAST_CONFIG = {
    "title": "The Justin Brief",
    "description": (
        "A daily personal intelligence briefing for Justin Ngai — covering personal finance, "
        "credit card strategy, travel hacking, healthcare & infusion ops, tech & AI, "
        "real estate investing, and an educational deep dive. Every weekday morning."
    ),
    "author": "The Justin Brief",
    "email": "justin@justinbrief.local",
    "language": "en-us",
    "category": "Business",
    "subcategory": "Investing",
    "explicit": "false",
    "image_url": "",  # optional: set to a podcast artwork URL
}


def _load_episodes() -> list:
    if EPISODES_FILE.exists():
        with open(EPISODES_FILE) as f:
            return json.load(f)
    return []


def _save_episodes(episodes: list):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(EPISODES_FILE, "w") as f:
        json.dump(episodes, f, indent=2)


def add_episode(
    date_str: str,          # "2026-03-30"
    title: str,             # "The Justin Brief — Monday, March 30, 2026"
    description: str,       # Show notes / segment summary
    audio_filename: str,    # "justin_brief_20260330.mp3"
    script: str = "",       # Full script text (stored for archive)
    duration_seconds: int = 0,
) -> dict:
    """Register a new episode and regenerate the RSS feed."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    audio_path = AUDIO_DIR / audio_filename
    file_size = audio_path.stat().st_size if audio_path.exists() else 0

    episode = {
        "id": hashlib.md5(date_str.encode()).hexdigest()[:8],
        "date": date_str,
        "title": title,
        "description": description,
        "audio_filename": audio_filename,
        "file_size": file_size,
        "duration_seconds": duration_seconds,
        "script": script,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }

    episodes = _load_episodes()
    # Replace if same date exists, otherwise prepend
    episodes = [e for e in episodes if e["date"] != date_str]
    episodes.insert(0, episode)
    _save_episodes(episodes)

    return episode


def build_feed(base_url: str) -> str:
    """
    Generate the RSS XML feed and write to data/podcast/feed.xml.
    base_url: e.g. "http://192.168.1.5:8765" or "https://your-domain.com/podcast"
    Returns the path to the feed file.
    """
    episodes = _load_episodes()
    cfg = PODCAST_CONFIG

    # Namespaces
    ET.register_namespace("itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
    ET.register_namespace("atom", "http://www.w3.org/2005/Atom")

    rss = Element("rss", {
        "version": "2.0",
        "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
        "xmlns:atom": "http://www.w3.org/2005/Atom",
    })

    channel = SubElement(rss, "channel")

    def sub(parent, tag, text=None, **attrs):
        el = SubElement(parent, tag, attrs)
        if text:
            el.text = text
        return el

    sub(channel, "title", cfg["title"])
    sub(channel, "description", cfg["description"])
    sub(channel, "language", cfg["language"])
    sub(channel, "link", base_url)
    sub(channel, "atom:link", href=f"{base_url}/feed.xml",
        rel="self", type="application/rss+xml")

    sub(channel, "itunes:author", cfg["author"])
    sub(channel, "itunes:explicit", cfg["explicit"])

    owner = SubElement(channel, "itunes:owner")
    sub(owner, "itunes:name", cfg["author"])
    sub(owner, "itunes:email", cfg["email"])

    cat = SubElement(channel, "itunes:category", text=cfg["category"])
    if cfg.get("subcategory"):
        SubElement(cat, "itunes:category", text=cfg["subcategory"])

    if cfg.get("image_url"):
        img = SubElement(channel, "itunes:image")
        img.set("href", cfg["image_url"])

    for ep in episodes:
        item = SubElement(channel, "item")
        sub(item, "title", ep["title"])
        sub(item, "description", ep["description"])
        sub(item, "guid", f"{base_url}/episodes/{ep['id']}", isPermaLink="false")

        audio_url = f"{base_url}/audio/{ep['audio_filename']}"
        sub(item, "enclosure",
            url=audio_url,
            length=str(ep.get("file_size", 0)),
            type="audio/mpeg")

        # RFC 2822 pub date
        try:
            pub_dt = datetime.fromisoformat(ep["published_at"])
            pub_str = pub_dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
        except Exception:
            pub_str = ep.get("date", "")
        sub(item, "pubDate", pub_str)

        if ep.get("duration_seconds"):
            mins, secs = divmod(ep["duration_seconds"], 60)
            sub(item, "itunes:duration", f"{mins:02d}:{secs:02d}")

        sub(item, "itunes:explicit", cfg["explicit"])

    tree = ElementTree(rss)
    indent(tree, space="  ")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tree.write(str(FEED_FILE), encoding="unicode", xml_declaration=True)

    return str(FEED_FILE)


def get_episode_list() -> list:
    return _load_episodes()


def get_episode_by_date(date_str: str) -> dict | None:
    for ep in _load_episodes():
        if ep["date"] == date_str:
            return ep
    return None
