# inContext Agent

A personal language tutor agent powered by [Mistral AI](https://mistral.ai/). It acts like a real tutor — not a flashcard app — by generating fresh content around your interests, teaching vocabulary and grammar in context, and running spaced repetition invisibly in the background.

## Architecture

```
agent/          → Core agent loop, dynamic prompt builder, tool definitions, file-based memory
db/             → SQLite + FSRS spaced repetition scheduler
soul/           → SOUL.md — personality, teaching philosophy, interaction rules
skills/         → Modular SKILL.md files loaded on demand (language acquisition, teaching methods, etc.)
memory/         → Student profile (USER.md), session logs — all human-readable markdown
sources/        → Reference material (articles, transcripts) for content generation
custom_tools/   → Self-extending tool system — drop in a folder with manifest.json + tool.py
interfaces/     → CLI (Rich) and Web (Gradio) frontends
voice/          → ElevenLabs TTS integration
```

The agent uses Mistral's **Chat Completions API** with client-side tool dispatch. The system prompt is rebuilt every turn with current student state, due reviews, and available sources.

## Features

- **Content-based learning** — generates reading passages from topics, URLs, YouTube transcripts, or Wikipedia articles in the target language
- **Spaced repetition (FSRS)** — vocabulary and grammar are tracked automatically; review is woven into conversation
- **Comprehension & vocabulary quizzes** — multiple-choice questions generated from content the student just read
- **Dynamic difficulty** — adapts to the student's level; texts can be simplified on the fly
- **File-based memory** — student profile, session history, and skills stored as readable markdown files
- **Extensible tools** — YouTube search, Wikipedia lookup, dictionary definitions, source management, and a plugin system for custom tools
- **Voice support** — optional ElevenLabs TTS for pronunciation
- **Any language** — works with any language Mistral can generate

## Getting Started

### Prerequisites

- Python 3.13+
- A [Mistral API key](https://console.mistral.ai/)
- (Optional) An [ElevenLabs API key](https://elevenlabs.io/) for voice

### Setup

```bash
git clone <repo-url> && cd incontext-agent

# Install dependencies
pip install -e .

# Configure environment
cp .env.example .env
# Edit .env and add your MISTRAL_API_KEY (and optionally ELEVENLABS_API_KEY)
```

### Run

**CLI** (terminal with Rich formatting):

```bash
python interfaces/cli.py
```

On first launch the agent will onboard you — ask your target language, level, and interests — then you're ready to go.
