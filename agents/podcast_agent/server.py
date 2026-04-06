"""
Podcast Agent — HTTP Server
Serves the RSS feed and audio files over a local HTTP server.
Runs on a background thread so it doesn't block the Telegram bot.

Access from any device on the same network:
  RSS feed:  http://<your-mac-ip>:8765/feed.xml
  Dashboard: http://<your-mac-ip>:8765/

For external access (phone on cell, podcast apps outside home WiFi):
  Option A: Tailscale — install on Mac + phone, use Tailscale IP
  Option B: Cloudflare Tunnel — `cloudflared tunnel --url http://localhost:8765`
"""

import http.server
import threading
import logging
import os
import json
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "podcast"
PORT = int(os.getenv("PODCAST_PORT", 8765))


class PodcastHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        logger.debug(f"Podcast server: {format % args}")

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")

        if path == "" or path == "/":
            self._serve_dashboard()
        elif path == "/feed.xml":
            self._serve_file(DATA_DIR / "feed.xml", "application/rss+xml")
        elif path.startswith("/audio/"):
            filename = path.replace("/audio/", "")
            self._serve_file(DATA_DIR / "audio" / filename, "audio/mpeg")
        elif path == "/episodes":
            self._serve_episodes_json()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")

    def _serve_file(self, file_path: Path, content_type: str):
        if not file_path.exists():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"File not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with open(file_path, "rb") as f:
            self.wfile.write(f.read())

    def _serve_episodes_json(self):
        episodes_file = DATA_DIR / "episodes.json"
        if not episodes_file.exists():
            data = b"[]"
        else:
            data = episodes_file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def _serve_dashboard(self):
        episodes_file = DATA_DIR / "episodes.json"
        episodes = []
        if episodes_file.exists():
            with open(episodes_file) as f:
                episodes = json.load(f)

        rows = ""
        for ep in episodes:
            audio_url = f"/audio/{ep['audio_filename']}"
            rows += f"""
            <tr>
              <td>{ep['date']}</td>
              <td>{ep['title']}</td>
              <td><audio controls src="{audio_url}" style="width:300px"></audio></td>
              <td><a href="{audio_url}" download>⬇ Download</a></td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>The Justin Brief — Episode Archive</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            max-width: 960px; margin: 40px auto; padding: 0 20px; background: #f8f9fa; }}
    h1 {{ color: #1a1a2e; }}
    .subtitle {{ color: #666; margin-top: -10px; margin-bottom: 30px; }}
    .rss-link {{ background: #f4821e; color: white; padding: 8px 16px;
                 border-radius: 6px; text-decoration: none; font-weight: bold; }}
    table {{ width: 100%; border-collapse: collapse; background: white;
             border-radius: 10px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,.08); }}
    th {{ background: #1a1a2e; color: white; padding: 12px 16px; text-align: left; }}
    td {{ padding: 12px 16px; border-bottom: 1px solid #eee; vertical-align: middle; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #f0f4ff; }}
    .empty {{ text-align: center; padding: 40px; color: #999; }}
  </style>
</head>
<body>
  <h1>🎙 The Justin Brief</h1>
  <p class="subtitle">Your daily personal intelligence podcast</p>
  <p>
    <a href="/feed.xml" class="rss-link">📡 Subscribe via RSS</a>
    &nbsp;&nbsp;<small style="color:#666">Copy this feed URL into Overcast, Pocket Casts, or Apple Podcasts</small>
  </p>
  <br>
  <table>
    <thead>
      <tr><th>Date</th><th>Episode</th><th>Listen</th><th></th></tr>
    </thead>
    <tbody>
      {'<tr><td colspan="4" class="empty">No episodes yet</td></tr>' if not rows else rows}
    </tbody>
  </table>
  <p style="color:#aaa; font-size:12px; margin-top:20px">
    Feed URL: <code>http://YOUR_IP:{PORT}/feed.xml</code>
  </p>
</body>
</html>"""

        data = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _start_cloudflare_tunnel(port: int):
    """
    Launch a Cloudflare Quick Tunnel in a background thread.
    Requires `cloudflared` to be installed: brew install cloudflared
    Logs the public HTTPS URL so you can add it to PODCAST_HOST in .env
    for a persistent URL, use a named tunnel instead.
    """
    import subprocess, re as _re

    def _run():
        try:
            proc = subprocess.Popen(
                ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            for line in proc.stdout:
                line = line.strip()
                m = _re.search(r"https://[a-z0-9\-]+\.trycloudflare\.com", line)
                if m:
                    url = m.group(0)
                    logger.info(f"☁️  Cloudflare Tunnel active: {url}")
                    logger.info(f"    RSS feed: {url}/feed.xml")
                    logger.info(f"    Add to .env: PODCAST_HOST={url}")
                    break  # found the URL, keep proc running but stop scanning
            proc.wait()
        except FileNotFoundError:
            logger.info("cloudflared not found — skipping tunnel (install: brew install cloudflared)")
        except Exception as e:
            logger.warning(f"Cloudflare tunnel error: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def start_server():
    """Start the podcast HTTP server in a daemon background thread. Fails silently if port in use."""
    try:
        server = http.server.HTTPServer(("0.0.0.0", PORT), PodcastHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info(f"Podcast server running on port {PORT} → http://localhost:{PORT}")

        # If no static host is configured, auto-start a Cloudflare tunnel for external access
        if not os.getenv("PODCAST_HOST"):
            _start_cloudflare_tunnel(PORT)

        return server
    except OSError as e:
        logger.warning(f"Podcast server could not bind to port {PORT} ({e}) — skipping")
        return None
