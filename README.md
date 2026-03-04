<img width="621" height="157" alt="Screenshot 2026-03-04 at 16 32 48" src="https://github.com/user-attachments/assets/2919254e-4097-4fdb-8333-5a5e8a6a1709" />

A personal language tutor agent that acts like a real tutor — not a flashcard app. It generates fresh content around your interests, teaches vocabulary and grammar in context, and runs spaced repetition invisibly in the background.

Works with any model via [OpenRouter](https://openrouter.ai/) (default) or directly with [Mistral AI](https://mistral.ai/).

## Study Modes

- **Content-based learning** — generates reading passages from topics, URLs, YouTube transcripts, or Wikipedia articles in the target language
- **Spaced repetition (FSRS)** — vocabulary and grammar are tracked automatically; review is woven into conversation
- **Language Learning Q&A** — ask about language learning theory, methods, and strategies; the agent references acquisition research and Wikipedia for deeper exploration
- **Create your own** - tell the agent how you want to study

## Features

- **Dynamic difficulty** — adapts to the student's level; texts can be simplified on the fly
- **Extensible tools** — YouTube search, Wikipedia lookup, dictionary definitions, source management, and a plugin system for custom tools
- **Voice support** — optional ElevenLabs TTS for pronunciation
- **Any language** — works with any language the model can generate

## How It Works

### Tools

The agent has ~12 built-in tools that it calls during conversation:

- **Spaced repetition** — `get_due_reviews`, `log_review`, `add_review_item` to silently track and schedule vocabulary/grammar
- **Content discovery** — `search_youtube`, `lookup_wikipedia`, `lookup_definition` to find lesson material
- **Source management** — `add_source`, `list_sources`, `read_source` to fetch and save URLs/transcripts as reusable lesson content
- **Student profile** — `update_student_profile` to record language, level, and goals
- **Audio** — `speak_text` for ElevenLabs TTS (when configured)

The agent can also extend itself: `propose_tool` and `save_tool` let the agent suggest new custom tools at runtime. Custom tools live in `custom_tools/` as a folder with a `manifest.json` (schema) and `tool.py` (implementation), and are hot-loaded without restart.

### Memory

**SQLite + FSRS** — Vocabulary and grammar items are stored in a SQLite database with full [FSRS](https://github.com/open-spaced-repetition/fsrs4anki) scheduling (stability, difficulty, due dates, lapse tracking). The student never sees the SRS system — it runs invisibly so conversation feels natural, not mechanical.

**File-based config** — Student profile (`memory/user.yaml`) stores language, CEFR level, and goals. Session logs (`memory/sessions/`) are appended daily as markdown. Saved sources (`sources/`) form a personal library of lesson material with YAML frontmatter.

### Skills

Skills are domain-specific teaching knowledge stored as markdown files in `skills/`. The agent loads them on demand — not at startup — when they'd improve a lesson. Current skills include:

- **Language acquisition** — Krashen's comprehensible input, acquisition vs. learning, spaced repetition principles, session design
- **Teaching methods** — Socratic questioning, scaffolding, error correction strategies, activity sequencing
- **Spanish** — grammar sequence, ser/estar, preterite/imperfect, common mistakes, pronunciation, cultural notes

Skills are easy to add or edit since they're just markdown files.

## Getting Started

### Prerequisites

- Python 3.13+
- An [OpenRouter API key](https://openrouter.ai/) (default) or a [Mistral API key](https://console.mistral.ai/)
- (Optional) An [ElevenLabs API key](https://elevenlabs.io/) for voice

### Setup

```bash
git clone <repo-url> && cd incontext-agent

# Install dependencies
pip install -e .

# Configure environment
cp .env.example .env
# Edit .env — add your OPENROUTER_API_KEY (or set PROVIDER=mistral and add MISTRAL_API_KEY)
```

### Run

```bash
python interfaces/cli.py
```

On first launch the agent will onboard you — ask your target language, level, and interests — then you're ready to go.
