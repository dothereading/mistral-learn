"""ElevenLabs text-to-speech integration."""

import os
import tempfile

from elevenlabs.client import ElevenLabs

import config

_client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)

# Hardcoded Spanish voice for demo
_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # ElevenLabs "George" multilingual
_MODEL_ID = "eleven_multilingual_v2"


def generate_speech(text: str, language: str | None = None) -> str:
    """Generate speech audio, save to a temp file, return the path."""
    audio = _client.text_to_speech.convert(
        text=text,
        voice_id=_VOICE_ID,
        model_id=_MODEL_ID,
        output_format="mp3_44100_128",
    )

    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    for chunk in audio:
        tmp.write(chunk)
    tmp.close()
    return tmp.name
