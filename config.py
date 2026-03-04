import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Provider selection: "openrouter" (default) or "mistral"
# ---------------------------------------------------------------------------
PROVIDER = os.getenv("PROVIDER", "openrouter").lower()

# Per-provider settings
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-3-flash-preview")

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

# ---------------------------------------------------------------------------
# Unified exports based on selected provider
# ---------------------------------------------------------------------------
if PROVIDER == "mistral":
    API_KEY = MISTRAL_API_KEY
    MODEL = MISTRAL_MODEL
    BASE_URL = "https://api.mistral.ai/v1"
else:
    API_KEY = OPENROUTER_API_KEY
    MODEL = OPENROUTER_MODEL
    BASE_URL = "https://openrouter.ai/api/v1"

if not API_KEY:
    key_name = "MISTRAL_API_KEY" if PROVIDER == "mistral" else "OPENROUTER_API_KEY"
    raise ValueError(f"{key_name} is not set. Copy .env.example to .env and add your key.")
