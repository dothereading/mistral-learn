"""Tool definitions (JSON schemas) and implementations."""

import json
import os
import re
from datetime import datetime

import requests

from agent.memory import (
    list_source_files,
    load_skill,
    read_source,
    save_source,
    update_student_profile,
)
from db.srs import add_review_item, get_due_reviews, log_review

# ---------------------------------------------------------------------------
# Tool JSON schemas for Mistral function calling
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_due_reviews",
            "description": (
                "Get review items (vocabulary and grammar patterns) due for spaced "
                "repetition. Call at session start, when entering Knowledge Review mode, "
                "and periodically during other modes to weave review in naturally."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max items to return (default 10)",
                    },
                    "item_type": {
                        "type": "string",
                        "description": "Filter by type: 'vocab', 'grammar', or omit for both",
                        "enum": ["vocab", "grammar"],
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_review",
            "description": (
                "Log a spaced repetition review after testing the student on a "
                "vocabulary word or grammar pattern. Rating: 1=forgot, 2=hard, "
                "3=good, 4=easy."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "integer",
                        "description": "ID of the review item",
                    },
                    "rating": {
                        "type": "integer",
                        "description": "Student performance: 1=forgot, 2=hard, 3=good, 4=easy",
                    },
                },
                "required": ["item_id", "rating"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_review_item",
            "description": (
                "Add a new vocabulary word or grammar pattern to the student's spaced "
                "repetition deck. Call whenever you introduce a new word/phrase or teach "
                "a new grammar pattern. The student doesn't see this — tracking is invisible."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_type": {
                        "type": "string",
                        "description": "'vocab' for words/phrases, 'grammar' for grammar patterns",
                        "enum": ["vocab", "grammar"],
                    },
                    "word": {
                        "type": "string",
                        "description": "For vocab: the word or phrase in target language",
                    },
                    "translation": {
                        "type": "string",
                        "description": "For vocab: translation in student's native language",
                    },
                    "pattern_name": {
                        "type": "string",
                        "description": "For grammar: short name like 'ser vs estar'",
                    },
                    "pattern_description": {
                        "type": "string",
                        "description": "For grammar: brief explanation of the rule or pattern",
                    },
                    "context": {
                        "type": "string",
                        "description": "Example sentence where the word/pattern was used",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category like 'food', 'greetings', 'verb-conjugation'",
                    },
                },
                "required": ["item_type", "context"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_youtube",
            "description": (
                "Search YouTube for a video and extract its transcript. Use to find "
                "authentic native content related to student interests."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "language": {
                        "type": "string",
                        "description": "Language code for transcript, e.g., 'es'",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_wikipedia",
            "description": (
                "Look up a topic on Wikipedia. Can retrieve articles in the target "
                "language for reading comprehension."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Topic to look up"},
                    "language": {
                        "type": "string",
                        "description": "Wikipedia language code, e.g., 'es' for Spanish Wikipedia",
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_definition",
            "description": "Look up a word's definition, pronunciation, and usage examples.",
            "parameters": {
                "type": "object",
                "properties": {
                    "word": {"type": "string", "description": "Word to look up"},
                    "language": {"type": "string", "description": "Language code"},
                },
                "required": ["word"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_source",
            "description": (
                "Fetch content from a URL and save it as a .txt file in sources/ "
                "for future lesson material."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch content from"},
                    "title": {
                        "type": "string",
                        "description": "Short descriptive title for the saved file",
                    },
                    "language": {
                        "type": "string",
                        "description": "Language of the content, e.g., 'es'",
                    },
                },
                "required": ["url", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_sources",
            "description": "List available source files in the sources/ folder.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_source",
            "description": "Read a saved source file from the sources/ folder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Filename to read from sources/ folder",
                    },
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_skill",
            "description": (
                "Read a skill file to load specialized teaching knowledge. "
                "Call when you need specific pedagogical or language knowledge."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_path": {
                        "type": "string",
                        "description": "Path to skill file, e.g., 'language-acquisition/SKILL.md'",
                    },
                },
                "required": ["skill_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_student_profile",
            "description": (
                "Update the student's profile with new observations. Call when you "
                "learn something new about the student's level, interests, or patterns. "
                "Pass only the fields you want to set or change."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "description": "Target language, e.g. 'Spanish', 'French'",
                    },
                    "variant": {
                        "type": "string",
                        "description": "Regional variant, e.g. 'Spain', 'Mexico', 'Brazil'",
                    },
                    "level": {
                        "type": "string",
                        "description": "CEFR level, e.g. 'A1', 'B2', 'C1'",
                    },
                    "goals": {
                        "type": "string",
                        "description": "Learning goals, e.g. 'Daily life in Spain'",
                    },
                },
            },
        },
    },
    # --- Self-extending meta-tools ---
    {
        "type": "function",
        "function": {
            "name": "propose_tool",
            "description": (
                "Propose building a new custom tool. Describe what it does and what "
                "parameters it needs. This does NOT build the tool — it stores the "
                "proposal so the student can review and confirm before building."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Snake_case tool name, e.g. 'fetch_news'",
                    },
                    "description": {
                        "type": "string",
                        "description": "What the tool does (shown in tool list)",
                    },
                    "parameters_schema": {
                        "type": "object",
                        "description": "JSON Schema for the tool's parameters",
                    },
                    "credentials_needed": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "API key names this tool requires, e.g. ['NEWS_API_KEY']",
                    },
                    "implementation_notes": {
                        "type": "string",
                        "description": "Notes on how to implement the tool",
                    },
                },
                "required": ["name", "description", "parameters_schema"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_tool",
            "description": (
                "Build and save a previously proposed custom tool. Call ONLY after "
                "the student has confirmed the proposal."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Tool name (must match the pending proposal)",
                    },
                    "code": {
                        "type": "string",
                        "description": (
                            "Full Python source code with a `def execute(args, agent) -> str` "
                            "function. Must be self-contained."
                        ),
                    },
                },
                "required": ["name", "code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "store_credential",
            "description": (
                "Store an API key or credential the student provides. "
                "Saved locally and never sent to the LLM."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key_name": {
                        "type": "string",
                        "description": "Credential key, e.g. 'NEWS_API_KEY'",
                    },
                    "key_value": {
                        "type": "string",
                        "description": "The credential value",
                    },
                },
                "required": ["key_name", "key_value"],
            },
        },
    },
]

# Speak text tool — only added if ElevenLabs is configured
SPEAK_TEXT_TOOL = {
    "type": "function",
    "function": {
        "name": "speak_text",
        "description": (
            "Generate audio speech of text using ElevenLabs. Use for pronunciation "
            "demonstrations, reading content aloud, or conversational practice."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to speak aloud"},
                "language": {
                    "type": "string",
                    "description": "Language code for pronunciation, e.g., 'es'",
                },
            },
            "required": ["text"],
        },
    },
}


def get_available_tools() -> list[dict]:
    """Return tool schemas, including speak_text only if ElevenLabs is configured."""
    from custom_tools import get_custom_schemas

    tools = list(TOOLS)
    if os.getenv("ELEVENLABS_API_KEY"):
        tools.append(SPEAK_TEXT_TOOL)
    tools.extend(get_custom_schemas())
    return tools


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def execute_tool(name: str, arguments: str, agent) -> str:
    """Dispatch a tool call and return the result as a string."""
    args = json.loads(arguments) if isinstance(arguments, str) else arguments

    try:
        match name:
            case "get_due_reviews":
                items = get_due_reviews(
                    agent.db,
                    limit=args.get("limit", 10),
                    item_type=args.get("item_type"),
                )
                if not items:
                    return "No items due for review right now."
                return json.dumps(items, default=str)

            case "log_review":
                updated = log_review(agent.db, args["item_id"], args["rating"])
                return f"Review logged. Next review due: {updated['due_date']}"

            case "add_review_item":
                # Determine language from agent's student profile or default
                language = args.get("language") or agent.target_language or "es"
                item = add_review_item(
                    agent.db,
                    item_type=args["item_type"],
                    language=language,
                    word=args.get("word"),
                    translation=args.get("translation"),
                    pattern_name=args.get("pattern_name"),
                    pattern_description=args.get("pattern_description"),
                    context=args.get("context"),
                    category=args.get("category"),
                )
                label = item.get("word") or item.get("pattern_name")
                return f"Added to review deck: {label} (id={item['id']})"

            case "search_youtube":
                return _search_youtube(args["query"], args.get("language"))

            case "lookup_wikipedia":
                return _lookup_wikipedia(args["topic"], args.get("language"))

            case "lookup_definition":
                return _lookup_definition(args["word"], args.get("language"))

            case "add_source":
                return _add_source(args["url"], args["title"], args.get("language"))

            case "list_sources":
                files = list_source_files()
                if not files:
                    return "No source files saved yet."
                return "\n".join(files)

            case "read_source":
                content = read_source(args["filename"])
                if content is None:
                    return f"File not found: {args['filename']}"
                return content

            case "read_skill":
                content = load_skill(args["skill_path"])
                if content is None:
                    return f"Skill not found: {args['skill_path']}"
                return content

            case "update_student_profile":
                fields = {k: v for k, v in args.items() if v is not None}
                updated = update_student_profile(fields)
                return f"Student profile updated.\n\nCurrent profile:\n{json.dumps(updated)}"

            case "speak_text":
                return _speak_text(args["text"], args.get("language"), agent)

            case "propose_tool":
                return _propose_tool(args, agent)

            case "save_tool":
                return _save_tool(args, agent)

            case "store_credential":
                return _store_credential(args)

            case _:
                from custom_tools import execute_custom_tool

                result = execute_custom_tool(name, args, agent)
                if result is not None:
                    return result
                return f"Unknown tool: {name}"

    except Exception as e:
        return f"Error in {name}: {e}"


# ---------------------------------------------------------------------------
# Content tool implementations
# ---------------------------------------------------------------------------


def _search_youtube(query: str, language: str | None = None) -> str:
    """Search YouTube and extract transcript."""
    try:
        import scrapetube
        from youtube_transcript_api import YouTubeTranscriptApi

        # Get real video IDs from YouTube search
        video_ids = []
        for video in scrapetube.get_search(query, limit=5):
            video_ids.append(video["videoId"])

        if not video_ids:
            return "No YouTube videos found for that query."

        # Try each video for a transcript
        for vid in video_ids:
            try:
                languages = [language] if language else ["en"]
                transcript = YouTubeTranscriptApi().fetch(vid, languages=languages)
                text = " ".join(entry.text for entry in transcript)
                # Truncate to ~800 words
                words = text.split()
                if len(words) > 800:
                    text = " ".join(words[:800]) + "..."
                return (
                    f"Video: https://youtube.com/watch?v={vid}\n\n"
                    f"Transcript ({len(words)} words):\n{text}"
                )
            except Exception:
                continue

        return "Found videos but couldn't extract transcripts. Try a different query."

    except ImportError:
        return "scrapetube and/or youtube-transcript-api not installed."
    except Exception as e:
        return f"YouTube search error: {e}"


def _lookup_wikipedia(topic: str, language: str | None = None) -> str:
    """Look up a topic on Wikipedia."""
    try:
        import wikipediaapi

        lang = language or "en"
        wiki = wikipediaapi.Wikipedia(
            user_agent="InContextAgent/1.0 (language-learning-tutor)",
            language=lang,
        )
        page = wiki.page(topic)
        if not page.exists():
            return f"No Wikipedia article found for '{topic}' in '{lang}'."

        # Get summary + first section content
        text = page.summary
        if len(text.split()) < 200:
            # Add more content from sections
            for section in page.sections[:3]:
                text += f"\n\n## {section.title}\n{section.text}"
                if len(text.split()) > 500:
                    break

        # Truncate
        words = text.split()
        if len(words) > 600:
            text = " ".join(words[:600]) + "..."

        return f"# {page.title}\n\n{text}"

    except ImportError:
        return "wikipedia-api not installed."
    except Exception as e:
        return f"Wikipedia lookup error: {e}"


def _lookup_definition(word: str, language: str | None = None) -> str:
    """Look up a word definition via Free Dictionary API."""
    lang = language or "en"
    url = f"https://api.dictionaryapi.dev/api/v2/entries/{lang}/{requests.utils.quote(word)}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return f"No definition found for '{word}' in '{lang}'."

        data = resp.json()
        if not data:
            return f"No definition found for '{word}'."

        entry = data[0]
        result_parts = [f"**{entry.get('word', word)}**"]

        # Phonetics
        for p in entry.get("phonetics", []):
            if p.get("text"):
                result_parts.append(f"Pronunciation: {p['text']}")
                break

        # Meanings
        for meaning in entry.get("meanings", [])[:3]:
            pos = meaning.get("partOfSpeech", "")
            result_parts.append(f"\n_{pos}_")
            for defn in meaning.get("definitions", [])[:2]:
                result_parts.append(f"- {defn['definition']}")
                if defn.get("example"):
                    result_parts.append(f'  Example: "{defn["example"]}"')

        return "\n".join(result_parts)

    except Exception as e:
        return f"Dictionary lookup error: {e}"


def _extract_youtube_id(url: str) -> str | None:
    """Extract video ID from a YouTube URL, or return None."""
    m = re.match(
        r"(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})",
        url,
    )
    return m.group(1) if m else None


def _add_source(url: str, title: str, language: str | None = None) -> str:
    """Fetch a URL and save as a source file."""
    try:
        # YouTube URLs: extract transcript instead of scraping HTML
        yt_id = _extract_youtube_id(url)
        if yt_id:
            from youtube_transcript_api import YouTubeTranscriptApi

            langs = [language] if language else ["es", "en"]
            transcript = YouTubeTranscriptApi().fetch(yt_id, languages=langs)
            text = " ".join(entry.text for entry in transcript)
            words = text.split()
            if len(words) > 2000:
                text = " ".join(words[:2000]) + "..."

            safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "-").lower()
            filename = f"{safe_title}.txt"
            header = (
                f"---\n"
                f"title: {title}\n"
                f"url: https://youtube.com/watch?v={yt_id}\n"
                f"language: {language or 'unknown'}\n"
                f"fetched: {datetime.now().isoformat()}\n"
                f"---\n\n"
            )
            save_source(filename, header + text)

            word_count = len(words)
            preview = " ".join(words[:100]) + "..."
            return (
                f"Saved as sources/{filename} ({word_count} words, YouTube transcript).\n\n"
                f"Preview:\n{preview}"
            )

        resp = requests.get(url, timeout=15, headers={"User-Agent": "InContextAgent/1.0"})
        resp.raise_for_status()

        # Extract main article text from HTML
        text = resp.text
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(text, "html.parser")

            # Remove noisy elements
            for tag in soup(
                ["script", "style", "nav", "header", "footer", "aside",
                 "noscript", "iframe", "form", "button", "svg"]
            ):
                tag.decompose()

            # Remove Wikipedia-specific cruft
            for sel in [
                ".mw-editsection", ".reference", ".reflist", ".refbegin",
                ".navbox", ".sidebar", ".infobox", ".metadata", ".mbox-small",
                ".noprint", ".catlinks", ".mw-jump-link", "#toc",
                ".toc", "#mw-navigation", "#footer", ".mw-indicators",
                ".external", ".mw-authority-control", ".portal-bar",
            ]:
                for el in soup.select(sel):
                    el.decompose()

            # Prefer <article> or main content div; fall back to <body>
            main = (
                soup.find("article")
                or soup.find("div", id="mw-content-text")
                or soup.find("div", {"role": "main"})
                or soup.find("main")
                or soup.body
                or soup
            )

            # Collect only paragraph and heading text
            parts = []
            for el in main.find_all(["p", "h1", "h2", "h3", "h4", "li"]):
                t = el.get_text(separator=" ", strip=True)
                if t and len(t) > 20:
                    parts.append(t)
            text = "\n\n".join(parts) if parts else main.get_text(separator="\n", strip=True)

            # Collapse blank lines
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
        except ImportError:
            # Fallback: basic regex HTML stripping
            text = re.sub(r"<[^>]+>", "", text)
            text = re.sub(r"\s+", " ", text).strip()

        # Build the source file
        safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "-").lower()
        filename = f"{safe_title}.txt"

        header = (
            f"---\n"
            f"title: {title}\n"
            f"url: {url}\n"
            f"language: {language or 'unknown'}\n"
            f"fetched: {datetime.now().isoformat()}\n"
            f"---\n\n"
        )
        content = header + text

        save_source(filename, content)

        word_count = len(text.split())
        preview = " ".join(text.split()[:100]) + "..."

        return (
            f"Saved as sources/{filename} ({word_count} words).\n\n"
            f"Preview:\n{preview}"
        )

    except Exception as e:
        return f"Error fetching source: {e}"


def _speak_text(text: str, language: str | None, agent) -> str:
    """Generate speech via ElevenLabs."""
    try:
        from voice.elevenlabs import generate_speech
        audio_path = generate_speech(text, language or "en")
        agent.audio_output = audio_path
        return f"Audio generated: {audio_path}"
    except ImportError:
        return "ElevenLabs voice module not available."
    except Exception as e:
        return f"Speech generation error: {e}"


# ---------------------------------------------------------------------------
# Self-extending tool implementations
# ---------------------------------------------------------------------------


def _propose_tool(args: dict, agent) -> str:
    """Store a tool proposal on the agent for user confirmation."""
    proposal = {
        "name": args["name"],
        "description": args["description"],
        "parameters_schema": args.get("parameters_schema", {"type": "object", "properties": {}}),
        "credentials_needed": args.get("credentials_needed", []),
        "implementation_notes": args.get("implementation_notes", ""),
    }
    agent._pending_tool_proposal = proposal

    creds = proposal["credentials_needed"]
    creds_line = f"\nCredentials needed: {', '.join(creds)}" if creds else ""

    params = proposal["parameters_schema"].get("properties", {})
    params_line = ", ".join(params.keys()) if params else "none"

    return (
        f"Tool proposal: **{proposal['name']}**\n"
        f"Description: {proposal['description']}\n"
        f"Parameters: {params_line}{creds_line}\n\n"
        f"[Ask the student to confirm]"
    )


def _save_tool(args: dict, agent) -> str:
    """Build and save a tool after user confirmation."""
    from custom_tools import _save_and_register_tool

    proposal = getattr(agent, "_pending_tool_proposal", None)
    if proposal is None:
        return "No pending tool proposal. Call propose_tool first."

    if proposal["name"] != args["name"]:
        return (
            f"Name mismatch: proposal is for `{proposal['name']}` "
            f"but save_tool was called with `{args['name']}`."
        )

    result = _save_and_register_tool(proposal, args["code"])
    agent._pending_tool_proposal = None
    return result


def _store_credential(args: dict) -> str:
    """Store a credential in the local credential file."""
    from custom_tools import save_credential

    save_credential(args["key_name"], args["key_value"])
    return f"Credential `{args['key_name']}` saved."
