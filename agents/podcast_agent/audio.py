"""
Podcast Agent — Audio Generation
Supports OpenAI TTS (primary, natural-sounding) with edge-tts fallback.
Set OPENAI_API_KEY in .env to enable OpenAI TTS.
"""

import asyncio
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Voice config
OPENAI_VOICE = "onyx"          # deep, warm, natural male — best for podcasts
EDGE_VOICE = "en-US-RogerNeural"   # Lively — more energetic, casual, podcast-style
EDGE_RATE = "+10%"


def generate_audio(text: str, output_path: str) -> str:
    """
    Generate MP3 from text. Uses OpenAI TTS if key available, else edge-tts.
    Returns path to the generated MP3 file.
    """
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        return _generate_openai(text, output_path, openai_key)
    else:
        logger.info("OPENAI_API_KEY not set — falling back to edge-tts")
        return _generate_edge_tts(text, output_path)


def _generate_openai(text: str, output_path: str, api_key: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    # OpenAI TTS has a 4096-char limit per request — chunk if needed
    chunks = _chunk_text(text, max_chars=4000)
    audio_chunks = []

    for i, chunk in enumerate(chunks):
        logger.info(f"Generating audio chunk {i+1}/{len(chunks)} via OpenAI TTS...")
        response = client.audio.speech.create(
            model="tts-1-hd",
            voice=OPENAI_VOICE,
            input=chunk,
            response_format="mp3",
        )
        chunk_path = output_path.replace(".mp3", f"_chunk{i}.mp3")
        response.stream_to_file(chunk_path)
        audio_chunks.append(chunk_path)

    if len(audio_chunks) == 1:
        import shutil
        shutil.move(audio_chunks[0], output_path)
    else:
        _concat_mp3s(audio_chunks, output_path)
        for p in audio_chunks:
            try:
                os.remove(p)
            except Exception:
                pass

    logger.info(f"OpenAI TTS audio saved: {output_path}")
    return output_path


def _generate_edge_tts(text: str, output_path: str) -> str:
    import edge_tts

    async def _run():
        communicate = edge_tts.Communicate(text, EDGE_VOICE, rate=EDGE_RATE)
        await communicate.save(output_path)

    asyncio.run(_run())
    logger.info(f"edge-tts audio saved: {output_path}")
    return output_path


def _chunk_text(text: str, max_chars: int = 4000) -> list[str]:
    """Split text at sentence boundaries to stay under OpenAI's char limit."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    current = ""
    for sentence in text.replace("\n", " ").split(". "):
        candidate = current + sentence + ". "
        if len(candidate) > max_chars and current:
            chunks.append(current.strip())
            current = sentence + ". "
        else:
            current = candidate
    if current.strip():
        chunks.append(current.strip())
    return chunks


def _concat_mp3s(paths: list[str], output_path: str):
    """Concatenate MP3 files using ffmpeg if available, else raw binary concat."""
    try:
        import subprocess
        inputs = " ".join(f"-i {p}" for p in paths)
        filter_complex = "".join(f"[{i}:0]" for i in range(len(paths)))
        cmd = (
            f"ffmpeg -y {inputs} -filter_complex "
            f'"{filter_complex}concat=n={len(paths)}:v=0:a=1[out]" '
            f'-map "[out]" {output_path}'
        )
        subprocess.run(cmd, shell=True, check=True, capture_output=True)
    except Exception:
        # Fallback: raw binary concat (works for MP3 in most cases)
        with open(output_path, "wb") as out:
            for p in paths:
                with open(p, "rb") as f:
                    out.write(f.read())
