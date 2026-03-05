import json
import random
import sys
import os
import threading
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from openai import OpenAI
from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.completion import Completer, Completion
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
import config
from agent.core import TutorAgent
from agent.memory import list_source_files, load_student_profile
from agent.prompts import (
    content_learning_write_prompt,
    content_learning_short_answer_prompt,
    content_learning_simplify_prompt,
    content_learning_improve_prompt,
)

console = Console()

# ---------------------------------------------------------------------------
# Lightweight LLM helper (no agent context, no tools, no history)
# ---------------------------------------------------------------------------
_llm_client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)


def _llm_call(system: str, user: str) -> str:
    """Single-shot LLM call with just a system prompt and user message."""
    resp = _llm_client.chat.completions.create(
        model=config.MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# MC quiz generation, runner, and prefetch
# ---------------------------------------------------------------------------
MC_SYSTEM_PROMPT = """\
You are a language-learning quiz generator. You receive a text that a student \
has just read. Generate exactly 5 multiple-choice comprehension questions \
about this text.

Question philosophy:
- Questions test whether the student UNDERSTOOD the text — start with meaning.
- Mix: 2 literal comprehension (facts stated in the text), \
2 vocabulary-in-context (what does word X most likely mean?), \
1 inference (something implied but not stated directly).
- Each question has exactly 4 options, only one correct.
- Write questions and all options in the SAME language as the text.
- Make wrong options plausible — not obviously absurd.

Return ONLY a JSON array. No markdown fences, no commentary. Each element:
{"question": "...", "options": ["A","B","C","D"], "correct": 0}
where `correct` is the 0-based index of the right answer."""

MC_EXPLAIN_SYSTEM = """\
You are a warm, encouraging language tutor. The student just answered a \
question incorrectly. Given the text they read, the question, \
and the correct answer, give a brief 1-2 sentence explanation in a mix of \
the target language and English (more target language for advanced students). \
Reference the specific part of the text that contains the answer. Be kind."""

REVIEW_MC_SYSTEM = """\
You are a language-learning vocabulary review quiz generator. You receive a \
JSON list of vocabulary items the student needs to review (each has id, word, \
translation, context). Generate one multiple-choice question per item.

Rules:
- Format each question: "En la frase '...context...', ¿qué significa '**word**'?"
- Options should be in English (testing recognition of meaning).
- Exactly 4 options per question, only one correct (the translation).
- Wrong options must be plausible — similar meanings, related concepts.
- Pass through the item's "id" as "item_id" in each question.

Return ONLY a JSON array. No markdown fences, no commentary. Each element:
{"question": "...", "options": ["A","B","C","D"], "correct": 0, "item_id": 123}
where `correct` is the 0-based index of the right answer."""

VOCAB_MC_SYSTEM = """\
You are a language-learning vocabulary quiz generator. You receive a text \
that a student has just read and answered comprehension questions about. \
Generate exactly 5 multiple-choice vocabulary questions based on this text.

Question philosophy:
- Pick 5 words or short phrases from the text that are important for the \
student to learn. Focus on useful, high-frequency words — not obscure ones.
- Each question asks what a word/phrase from the text means, using the \
sentence from the text as context.
- Format: "En la frase '...sentence...', ¿qué significa 'word'?"
- Options should be in the student's native language (English) so you are \
testing comprehension, not production.
- Make wrong options plausible — similar meanings, related concepts.

Return ONLY a JSON array. No markdown fences, no commentary. Each element:
{"question": "...", "options": ["A","B","C","D"], "correct": 0, \
"word": "the target word", "translation": "correct English meaning", \
"context": "the sentence from the text containing the word"}
where `correct` is the 0-based index of the right answer."""

def _parse_json_response(raw: str) -> list[dict] | None:
    """Parse a JSON array from an LLM response, stripping markdown fences."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()
    try:
        result = json.loads(cleaned)
        if isinstance(result, list) and len(result) >= 1:
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Background prefetch system — generate quiz questions while user is busy
# ---------------------------------------------------------------------------
_prefetch_lock = threading.Lock()
_prefetch_slots: dict[str, dict] = {}  # slot_name -> {"thread", "result"}


def _bg_llm_worker(slot: str, system: str, user: str) -> None:
    """Background worker: run an LLM call and store the parsed result."""
    try:
        raw = _llm_call(system, user)
        parsed = _parse_json_response(raw)
        with _prefetch_lock:
            _prefetch_slots[slot]["result"] = parsed
    except Exception:
        pass


def start_bg_generate(slot: str, system: str, user: str) -> None:
    """Kick off a background LLM generation in the named slot."""
    with _prefetch_lock:
        _prefetch_slots[slot] = {"thread": None, "result": None}
    t = threading.Thread(target=_bg_llm_worker, args=(slot, system, user), daemon=True)
    with _prefetch_lock:
        _prefetch_slots[slot]["thread"] = t
    t.start()


def get_bg_result(slot: str, timeout: float = 30) -> list[dict] | None:
    """Block until the named slot finishes. Returns parsed questions or None."""
    with _prefetch_lock:
        entry = _prefetch_slots.get(slot)
    if not entry:
        return None
    t = entry.get("thread")
    if t is not None:
        t.join(timeout=timeout)
    with _prefetch_lock:
        result = entry.get("result")
        _prefetch_slots.pop(slot, None)
    return result


def _shuffle_options(q: dict) -> dict:
    """Return a copy of the question with options in a random order."""
    correct_idx = q["correct"]
    # Pair each option with a flag indicating if it's the correct one
    indexed = [(text, i == correct_idx) for i, text in enumerate(q["options"])]
    random.shuffle(indexed)
    options = [text for text, _ in indexed]
    new_correct = next(i for i, (_, is_correct) in enumerate(indexed) if is_correct)
    result = {
        "question": q["question"],
        "options": options,
        "correct": new_correct,
    }
    # Preserve extra fields (word, translation, context) for vocab quizzes
    for key in ("word", "translation", "context", "item_id"):
        if key in q:
            result[key] = q[key]
    return result


def _run_mc_round(
    questions: list[dict], text: str, title: str = "Quiz",
    on_miss=None,
) -> tuple[int, list[dict]]:
    """Display MC questions one at a time. Returns (score, list_of_missed).

    on_miss(question_dict) is called immediately when a question is missed,
    before the explanation is shown.
    """
    questions = [_shuffle_options(q) for q in questions[:5]]
    score = 0
    missed: list[dict] = []

    for i, q in enumerate(questions, 1):
        rows = [f"  [bold]{title} {i}/{len(questions)}:[/bold] {q['question']}\n"]
        for j, opt in enumerate(q["options"], 1):
            rows.append(f"  [bold][cyan][{j}][/cyan][/bold] {opt}")
        body = "\n".join(rows)
        console.print()
        console.print(Panel(body, border_style="yellow", padding=(1, 2)))

        try:
            answer = checked_input("[bold cyan]Your answer (1-4):[/] ")
            idx = int(answer) - 1
        except (ValueError, EOFError, KeyboardInterrupt):
            idx = -1

        if idx == q["correct"]:
            score += 1
            console.print("  [bold green]Correct![/]")
        else:
            correct_text = q["options"][q["correct"]]
            console.print(
                f"  [bold red]Not quite.[/] The answer is: [bold]{correct_text}[/]"
            )
            missed.append(q)
            if on_miss:
                on_miss(q)
            user_msg = (
                f"Text:\n{text}\n\n"
                f"Question: {q['question']}\n"
                f"Correct answer: {correct_text}"
            )
            explanation = _llm_call(MC_EXPLAIN_SYSTEM, user_msg)
            print_response(explanation)

    console.print()
    console.print(
        Panel(
            f"  You got [bold]{score}/{len(questions)}[/bold] correct!",
            border_style="green" if score >= 4 else "yellow",
            padding=(1, 2),
        )
    )
    return score, missed


def run_mc_quiz(agent: TutorAgent, text: str) -> str | None:
    """Run the comprehension MC quiz. Returns the text for follow-up quizzes."""
    console.print("\n  [dim]Preparing comprehension questions...[/]")
    questions = get_bg_result("mc")
    if not questions:
        reply = agent.chat(
            "[System: Generate the first multiple-choice question about "
            "the text you wrote. Present one question with 4 options.]"
        )
        print_response(reply)
        return None

    # Kick off vocab question generation while user answers MC
    start_bg_generate("vocab", VOCAB_MC_SYSTEM, text)

    score, _missed = _run_mc_round(questions, text, title="Pregunta")

    agent.history.append({
        "role": "user",
        "content": f"[Comprehension quiz complete: {score}/{len(questions)} correct]",
    })
    agent.history.append({
        "role": "assistant",
        "content": f"Comprehension quiz done — {score}/{len(questions)}.",
    })
    return text


def run_vocab_quiz(agent: TutorAgent, text: str) -> None:
    """Run the vocabulary MC quiz. Missed words are auto-added to SRS."""
    console.print("\n  [dim]Preparing vocabulary questions...[/]")
    questions = get_bg_result("vocab")
    if not questions:
        # bg wasn't started or failed — try synchronously
        raw = _llm_call(VOCAB_MC_SYSTEM, text)
        questions = _parse_json_response(raw)
    if not questions:
        # Fallback: let the agent handle vocab conversationally
        reply = agent.chat(
            "[System: Highlight 3-5 key vocabulary items from the text. "
            "Present them in context and add them to the review deck.]"
        )
        print_response(reply)
        return

    # Add missed vocab to SRS immediately as student misses each one
    from db.srs import add_review_item
    lang = agent.target_language or "es"
    added = 0

    def _on_vocab_miss(q: dict) -> None:
        nonlocal added
        word = q.get("word")
        translation = q.get("translation")
        context = q.get("context", "")
        if word and translation:
            try:
                add_review_item(
                    agent.db, item_type="vocab", language=lang,
                    word=word, translation=translation,
                    context=context, category="content-lesson",
                )
                added += 1
                console.print(f"  [dim]📝 Added to review deck:[/] [bold]{word}[/] — {translation}")
            except Exception:
                pass

    score, missed = _run_mc_round(questions, text, title="Vocab", on_miss=_on_vocab_miss)

    agent.history.append({
        "role": "user",
        "content": f"[Vocab quiz complete: {score}/{len(questions)} correct, {added} added to SRS]",
    })
    agent.history.append({
        "role": "assistant",
        "content": f"Vocab quiz done — {score}/{len(questions)}. Moving to short answer.",
    })

BANNER = r"""[bold green]
  ██╗███╗   ██╗ ██████╗ ██████╗ ███╗   ██╗████████╗███████╗██╗  ██╗████████╗
  ██║████╗  ██║██╔════╝██╔═══██╗████╗  ██║╚══██╔══╝██╔════╝╚██╗██╔╝╚══██╔══╝
  ██║██╔██╗ ██║██║     ██║   ██║██╔██╗ ██║   ██║   █████╗   ╚███╔╝    ██║
  ██║██║╚██╗██║██║     ██║   ██║██║╚██╗██║   ██║   ██╔══╝   ██╔██╗    ██║
  ██║██║ ╚████║╚██████╗╚██████╔╝██║ ╚████║   ██║   ███████╗██╔╝ ██╗   ██║
  ╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ╚══════╝╚═╝  ╚═╝   ╚═╝
[/]"""

# ---------------------------------------------------------------------------
# Tool-call labels for status lines
# ---------------------------------------------------------------------------
TOOL_LABELS = {
    "search_youtube": "Searching YouTube",
    "lookup_wikipedia": "Looking up Wikipedia",
    "lookup_definition": "Looking up definition",
    "add_source": "Saving source",
    "list_sources": "Listing sources",
    "read_source": "Reading source",
    "read_skill": "Loading skill",
    "add_review_item": "Saving to review deck",
    "get_due_reviews": "Checking review deck",
    "log_review": "Logging review",
    "update_student_profile": "Updating profile",
    "speak_text": "Generating audio",
    "propose_tool": "Proposing new tool",
    "save_tool": "Building custom tool",
    "store_credential": "Storing credential",
}

# ---------------------------------------------------------------------------
# Session modes
# ---------------------------------------------------------------------------
SESSION_MODES = [
    ("Content-Based Learning", "📖"),
    ("Knowledge Review", "🔄"),
    ("Language Acquisition Q&A", "🧠"),
    ("Custom", "🛠️"),
]

def _model_tiers() -> list[tuple[str, str, str]]:
    """Return model tiers with provider-appropriate model IDs."""
    if config.PROVIDER == "mistral":
        return [
            ("mistral-small-latest", "Small", "Fast, cheapest"),
            ("mistral-medium-latest", "Medium", "Balanced"),
            ("mistral-large-latest", "Large", "Most capable"),
        ]
    # OpenRouter — multi-vendor selection
    return [
        # Google
        ("google/gemini-3-flash-preview", "Gemini 3 Flash", "Fast, cheap (default)"),
        ("google/gemini-3.1-pro-preview", "Gemini 3.1 Pro", "Capable, balanced"),
        # Anthropic
        ("anthropic/claude-haiku-4-5-20251001", "Claude Haiku 4.5", "Fast, lightweight"),
        ("anthropic/claude-sonnet-4.6", "Claude Sonnet 4.6", "Strong all-rounder"),
        ("anthropic/claude-opus-4.6", "Claude Opus 4.6", "Most capable"),
        # Mistral
        ("mistralai/mistral-small-creative", "Mistral Small", "Fast, creative"),
        ("mistralai/mistral-large-2512", "Mistral Large", "Powerful"),
    ]

CONTENT_LENGTHS = [
    ("Short", "~1 paragraph"),
    ("Medium", "~4 paragraphs"),
    ("Long", "~10 paragraphs"),
]

LENGTH_TO_DESCRIPTION = {
    "Short": "about 1 paragraph",
    "Medium": "about 4 paragraphs",
    "Long": "about 10 paragraphs",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_active_agent: "TutorAgent | None" = None  # set in main()
_current_mode: str | None = None  # set wherever pick_mode() succeeds
_audio_auto: bool = False  # when True, auto-play audio on content generation

_EXIT_COMMANDS = {"/quit", "/exit"}

# Phrases that indicate the model couldn't produce content for the topic
_NO_CONTENT_PHRASES = [
    "couldn't find",
    "could not find",
    "no results",
    "unable to find",
    "not find any",
    "didn't find",
    "did not find",
    "no information",
    "try a different",
    "try another",
    "unable to locate",
]


def _reply_is_no_content(reply: str) -> bool:
    """Return True if the agent reply indicates it failed to find content."""
    lower = reply.lower()
    # Short replies are suspicious — real content passages are longer
    if len(reply.split()) < 40:
        return any(phrase in lower for phrase in _NO_CONTENT_PHRASES)
    return False


class SessionExit(Exception):
    """Raised when the user types an exit command at any prompt."""


_SLASH_COMMANDS = [
    ("/help", "Show available commands"),
    ("/menu", "Pick a session mode"),
    ("/profile", "View student profile"),
    ("/sources", "List saved sources"),
    ("/tools", "List custom tools"),
    ("/model", "Switch model tier"),
    ("/easier", "Simplify the current text"),
    ("/audio", "Listen to the current text"),
    ("/audio-on", "Auto-play audio"),
    ("/audio-off", "Disable auto-play audio"),
    ("/switch", "Toggle conversation language"),
    ("/stop", "Stop audio playback"),
    ("/reset", "Start fresh session"),
    ("/exit", "Exit"),
    ("/quit", "Exit"),
]


class _SlashCompleter(Completer):
    """Show slash-command completions when the input starts with '/'."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        for cmd, desc in _SLASH_COMMANDS:
            if cmd.startswith(text):
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display_meta=desc,
                )


_slash_completer = _SlashCompleter()


def _prompt_input(prompt_text: str) -> str:
    """Read input with slash-command autocompletion.

    *prompt_text* may contain Rich markup — it's printed via Rich first,
    then prompt_toolkit reads the actual input on the same line.
    """
    # Print the Rich-formatted prompt without a trailing newline
    console.print(prompt_text, end="")
    return pt_prompt("", completer=_slash_completer, complete_while_typing=True)


def checked_input(prompt: str) -> str:
    """Like console.input but raises SessionExit on exit commands.

    Also handles slash commands inline so they work at any prompt
    (pickers, quizzes, etc.) without interrupting the flow.
    """
    while True:
        raw = _prompt_input(prompt).strip()
        lower = raw.lower()
        if lower in _EXIT_COMMANDS:
            raise SessionExit
        if lower in ("?", "/help"):
            show_help()
            continue
        if lower == "/profile":
            _show_profile()
            continue
        if lower == "/sources":
            _show_sources()
            continue
        if lower == "/tools":
            _show_tools()
            continue
        if lower == "/model":
            _pick_model()
            continue
        if lower == "/stop":
            _stop_audio()
            continue
        if lower == "/switch":
            _toggle_language()
            continue
        if lower == "/audio-on":
            global _audio_auto
            _audio_auto = True
            console.print("  [dim]Auto-audio enabled. Content will be read aloud automatically.[/]")
            continue
        if lower == "/audio-off":
            _audio_auto = False
            console.print("  [dim]Auto-audio disabled.[/]")
            continue
        return raw


def print_response(text: str) -> None:
    """Print an agent response inside a green-bordered panel."""
    md = Markdown(text)
    panel = Panel(md, border_style="green", padding=(1, 2))
    console.print(panel)


def _play_audio(agent: TutorAgent) -> None:
    """If the agent produced audio, play it with afplay (macOS)."""
    path = agent.audio_output
    if not path:
        return
    agent.audio_output = None
    import subprocess
    try:
        console.print("  [dim]Playing audio...[/]")
        subprocess.run(["afplay", path], check=True)
    except FileNotFoundError:
        console.print("  [dim yellow]No audio player found (afplay).[/]")
    except subprocess.CalledProcessError:
        console.print("  [dim yellow]Audio playback failed.[/]")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _toggle_language() -> None:
    """Toggle the conversation language for Language Acquisition Q&A mode."""
    if not _active_agent:
        console.print("  [dim yellow]No active session.[/]")
        return
    agent = _active_agent
    current = agent.use_target_language
    if current is True:
        agent.use_target_language = False
        console.print("  [dim]Switched to English / native language.[/]")
    else:
        # None (auto) or False → switch to target language
        agent.use_target_language = True
        lang = agent.target_language_name or "target language"
        console.print(f"  [dim]Switched to {lang}.[/]")


def show_help() -> None:
    """Display available commands."""
    table = Table(title="Commands", show_header=True, header_style="bold cyan")
    table.add_column("Command", style="bold")
    table.add_column("Description")
    table.add_row("?  /help", "Show this help")
    table.add_row("/menu", "Pick a session mode")
    table.add_row("/profile", "View student profile")
    table.add_row("/sources", "List saved sources")
    table.add_row("/tools", "List custom tools")
    table.add_row("/model", "Switch model tier")
    table.add_row("/easier", "Simplify the current text (during content lessons)")
    table.add_row("/audio", "Listen to the current text (during content lessons)")
    table.add_row("/audio-on", "Auto-play audio when content is generated")
    table.add_row("/audio-off", "Disable auto-play audio")
    table.add_row("/switch", "Toggle conversation language (target ↔ English)")
    table.add_row("/stop", "Stop audio playback")
    table.add_row("/reset", "Start fresh session")
    table.add_row("/exit  /quit", "Exit")
    console.print()
    console.print(table)
    console.print()


def _show_profile() -> None:
    """Display the student profile."""
    profile = load_student_profile()
    if profile:
        lines = []
        for key, value in profile.items():
            if isinstance(value, list):
                lines.append(f"  [bold]{key}:[/] {', '.join(str(v) for v in value)}")
            else:
                lines.append(f"  [bold]{key}:[/] {value}")
        console.print()
        console.print(Panel("\n".join(lines), title="Student Profile", border_style="magenta", padding=(1, 2)))
    else:
        console.print("\n  [dim]No profile yet — keep chatting and I'll learn about you![/]")
    console.print()


def _show_sources() -> None:
    """List saved source files."""
    sources = list_source_files()
    if sources:
        console.print()
        for s in sources:
            console.print(f"  [dim]•[/] {s}")
    else:
        console.print("\n  [dim]No sources saved yet.[/]")
    console.print()


def _show_tools() -> None:
    """List custom tools."""
    from custom_tools import get_custom_tool_info

    tools = get_custom_tool_info()
    if tools:
        console.print()
        for t in tools:
            console.print(f"  [dim]•[/] [bold]{t['name']}[/] — {t['description']}")
    else:
        console.print("\n  [dim]No custom tools yet. Ask the tutor to build one![/]")
    console.print()


_PHASE_NAMES = ["Reading", "Comprehension", "Vocabulary", "Short Answer"]


def _phase_banner(phase: int, total: int = 4) -> None:
    """Print a Rich Rule showing the current lesson phase with progress dots."""
    dots = []
    for i in range(1, total + 1):
        if i < phase:
            dots.append("[green]●[/]")
        elif i == phase:
            dots.append("[bold yellow]●[/]")
        else:
            dots.append("[dim]○[/]")
    progress = "━".join(dots)
    name = _PHASE_NAMES[phase - 1] if phase <= len(_PHASE_NAMES) else f"Phase {phase}"
    title = f"Content Lesson  {progress}  {name} ({phase}/{total})"
    console.print()
    console.print(Rule(title, style="cyan"))


def _input_prompt() -> str:
    """Return mode-aware input prompt."""
    if _current_mode == "Content-Based Learning":
        return "[bold cyan]📖 Content You:[/] "
    return "[bold cyan]You:[/] "


def _pick_model() -> None:
    """Show model picker and switch if selected."""
    agent = _active_agent
    if not agent:
        return
    tiers = _model_tiers()
    current = agent.model
    rows = []
    for i, (model_id, label, desc) in enumerate(tiers, 1):
        marker = " [bold green]◄[/]" if model_id == current else ""
        rows.append(f"  [bold][cyan][{i}][/cyan][/bold] {label} — {desc}{marker}")
    console.print()
    console.print(Panel("\n".join(rows), title="Model", border_style="cyan", padding=(1, 2)))
    try:
        pick = console.input(f"[bold cyan]Pick a model (1-{len(tiers)}):[/] ").strip()
        idx = int(pick) - 1
        if 0 <= idx < len(tiers):
            model_id, label, _ = tiers[idx]
            agent.model = model_id
            console.print(f"  [dim]→ Switched to {label} ({model_id})[/]")
        else:
            console.print("  [dim]Invalid choice.[/]")
    except (ValueError, EOFError, KeyboardInterrupt):
        console.print("  [dim]Cancelled.[/]")
    console.print()


def pick_mode() -> str | None:
    """Show mode picker, return the selected mode name or None."""
    rows = []
    for i, (name, icon) in enumerate(SESSION_MODES, 1):
        rows.append(f"  [bold][cyan][{i}][/cyan][/bold] {icon} {name}")
    body = "\n".join(rows)
    console.print()
    console.print(Panel(body, title="Session Mode", border_style="cyan", padding=(1, 2)))
    while True:
        try:
            choice = checked_input("[bold cyan]Pick a mode (1-4):[/] ")
            idx = int(choice) - 1
            if 0 <= idx < len(SESSION_MODES):
                name = SESSION_MODES[idx][0]
                console.print(f"  [dim]→ {name}[/]")
                return name
        except ValueError:
            pass
        console.print("  [dim]Please pick 1-4.[/]")


def pick_content_length() -> str | None:
    """Show content-length picker, return description or None."""
    rows = []
    for i, (label, desc) in enumerate(CONTENT_LENGTHS, 1):
        rows.append(f"  [bold][cyan][{i}][/cyan][/bold] {label} — {desc}")
    body = "\n".join(rows)
    console.print()
    console.print(Panel(body, title="Content Length", border_style="cyan", padding=(1, 2)))
    while True:
        try:
            choice = checked_input("[bold cyan]Pick a length (1-3):[/] ")
            idx = int(choice) - 1
            if 0 <= idx < len(CONTENT_LENGTHS):
                label = CONTENT_LENGTHS[idx][0]
                console.print(f"  [dim]→ {label}[/]")
                return LENGTH_TO_DESCRIPTION[label]
        except ValueError:
            pass
        console.print("  [dim]Please pick 1-3.[/]")


CONTENT_SOURCES = [
    ("Search a topic", "🔍"),
    ("Enter a URL", "🔗"),
    ("Saved source", "📂"),
    ("Generate a story", "📝"),
]


def _prefetch_url(url: str) -> tuple[str, str | None]:
    """If the URL can be fetched directly (e.g. YouTube), save it and return
    ("saved", filename). Otherwise return ("url", url) for the model to handle."""
    import re as _re
    from agent.tools import _extract_youtube_id, _add_source
    yt_id = _extract_youtube_id(url)
    if yt_id:
        console.print("  [dim]Fetching transcript...[/]")
        result = _add_source(url, f"youtube-{yt_id}", None)
        # Extract actual filename from result like "Saved as sources/foo.txt (...)"
        m = _re.search(r"Saved as sources/(\S+)", result)
        if m:
            filename = m.group(1)
            console.print(f"  [dim]→ Saved: {filename}[/]")
            return ("saved", filename)
    return ("url", url)


def _clarify_topic(topic: str) -> str:
    """If the topic is very short/vague, ask the user to be more specific."""
    if len(topic.split()) <= 2:
        console.print(f"  [dim]Topic is a bit broad. Add some detail so I can find better content.[/]")
        detail = console.input(f"  [bold cyan]More specific (or Enter to keep \"{topic}\"):[/] ").strip()
        if detail:
            return f"{topic} {detail}"
    return topic


def pick_content_source() -> tuple[str, str | None]:
    """Show content-source picker. Returns (source_type, user_input) or ("story", None)."""
    sources = list_source_files()
    rows = []
    for i, (name, icon) in enumerate(CONTENT_SOURCES, 1):
        label = f"  [bold][cyan][{i}][/cyan][/bold] {icon} {name}"
        if name == "Saved source" and not sources:
            label += " [dim](none saved)[/dim]"
        rows.append(label)
    body = "\n".join(rows)
    console.print()
    console.print(Panel(body, title="Content Source", border_style="cyan", padding=(1, 2)))
    try:
        choice = checked_input("[bold cyan]Pick a source (1-4), or type a topic:[/] ")
        if not choice:
            return ("search", None)
        # If the user pasted a URL directly
        if choice.startswith(("http://", "https://", "www.")):
            console.print(f"  [dim]→ URL: {choice}[/]")
            return _prefetch_url(choice)
        # Try as a number
        try:
            idx = int(choice) - 1
        except ValueError:
            # Not a number — treat as a search topic
            choice = _clarify_topic(choice)
            console.print(f"  [dim]→ Searching: {choice}[/]")
            return ("search", choice)
        if idx == 0:
            topic = console.input("[bold cyan]Topic:[/] ").strip()
            if not topic:
                return ("search", None)
            topic = _clarify_topic(topic)
            console.print(f"  [dim]→ Searching: {topic}[/]")
            return ("search", topic)
        elif idx == 1:
            url = console.input("[bold cyan]URL:[/] ").strip()
            console.print(f"  [dim]→ URL: {url}[/]")
            return _prefetch_url(url)
        elif idx == 2:
            if not sources:
                console.print("  [dim]No saved sources. Falling back to search.[/]")
                topic = console.input("[bold cyan]Topic:[/] ").strip()
                if not topic:
                    return ("search", None)
                topic = _clarify_topic(topic)
                console.print(f"  [dim]→ Searching: {topic}[/]")
                return ("search", topic)
            # Show saved sources for selection
            console.print()
            for j, s in enumerate(sources, 1):
                console.print(f"  [bold][cyan][{j}][/cyan][/bold] {s}")
            pick = console.input(f"[bold cyan]Pick a source (1-{len(sources)}):[/] ").strip()
            si = int(pick) - 1
            if 0 <= si < len(sources):
                filename = sources[si]
                console.print(f"  [dim]→ Source: {filename}[/]")
                return ("saved", filename)
            console.print("  [dim]Invalid choice.[/]")
            return ("search", None)
        elif idx == 3:
            console.print("  [dim]→ Generate a story[/]")
            return ("story", None)
    except (EOFError, KeyboardInterrupt):
        pass
    console.print("  [dim]Defaulting to search.[/]")
    return ("search", None)


def mode_to_message(
    mode: str,
    length_desc: str | None = None,
    source_type: str | None = None,
    source_input: str | None = None,
    student_level: str | None = None,
    target_language: str | None = None,
) -> str:
    """Build the message sent to the agent when a mode is picked."""
    if mode == "Content-Based Learning" and length_desc:
        return content_learning_write_prompt(
            length_desc, source_type, source_input, student_level, target_language
        )
    if mode == "Custom":
        return "[Mode: Custom] Ask the student what they'd like to focus on."
    if mode == "Language Acquisition Q&A":
        return (
            "[Mode: Language Acquisition Q&A] The student wants to learn about "
            "language acquisition — how languages are learned, study methods, "
            "and research-backed strategies. Start by loading "
            "`language-acquisition/SKILL.md`, then ask what aspect of language "
            "acquisition they're curious about."
        )
    return f"[Mode: {mode}] Start a {mode} session."


def on_tool_call(name: str, _arguments: str) -> None:
    """Callback: print a dim status line when the agent calls a tool."""
    if name == "__malformed__":
        console.print("  [dim yellow]⚠ Malformed tool call, retrying...[/]")
        return
    label = TOOL_LABELS.get(name, name)
    console.print(f"  [dim]⚡ {label}...[/]")


def _run_knowledge_review(agent: TutorAgent) -> None:
    """Run a vocab-style MC quiz over SRS items that are due for review."""
    from db.srs import get_due_reviews, log_review

    due_items = get_due_reviews(agent.db, limit=10, item_type="vocab")
    if not due_items:
        console.print()
        console.print(
            Panel(
                "  [bold]Nothing to review right now![/]\n"
                "  Keep doing content lessons to build your review deck.",
                border_style="green",
                padding=(1, 2),
            )
        )
        return

    # Build payload for the LLM
    payload = [
        {
            "id": item["id"],
            "word": item["word"],
            "translation": item["translation"],
            "context": item.get("context", ""),
        }
        for item in due_items
    ]

    console.print("\n  [dim]Preparing review questions...[/]")
    raw = _llm_call(REVIEW_MC_SYSTEM, json.dumps(payload))
    questions = _parse_json_response(raw)
    if not questions:
        console.print("  [yellow]Couldn't generate quiz. Try again later.[/]")
        return

    questions = [_shuffle_options(q) for q in questions]
    score = 0
    total = len(questions)

    for i, q in enumerate(questions, 1):
        rows = [f"  [bold]Review {i}/{total}:[/bold] {q['question']}\n"]
        for j, opt in enumerate(q["options"], 1):
            rows.append(f"  [bold][cyan][{j}][/cyan][/bold] {opt}")
        body = "\n".join(rows)
        console.print()
        console.print(Panel(body, border_style="yellow", padding=(1, 2)))

        try:
            answer = checked_input("[bold cyan]Your answer (1-4):[/] ")
            idx = int(answer) - 1
        except (ValueError, EOFError, KeyboardInterrupt):
            idx = -1

        item_id = q.get("item_id")
        if idx == q["correct"]:
            score += 1
            console.print("  [bold green]Correct![/]")
            if item_id:
                log_review(agent.db, item_id, rating=4)
                console.print("  [dim]✅ Reviewed — interval extended[/]")
        else:
            correct_text = q["options"][q["correct"]]
            console.print(
                f"  [bold red]Not quite.[/] The answer is: [bold]{correct_text}[/]"
            )
            if item_id:
                log_review(agent.db, item_id, rating=1)
                console.print("  [dim]🔁 Scheduled for sooner review[/]")

    console.print()
    console.print(
        Panel(
            f"  You got [bold]{score}/{total}[/bold] correct!",
            border_style="green" if score == total else "yellow",
            padding=(1, 2),
        )
    )


def _pick_and_run_mode(agent: TutorAgent) -> None:
    """Show mode picker, run the selected mode, and loop back after content lessons."""
    global _current_mode
    while True:
        mode = pick_mode()
        if not mode:
            return
        _current_mode = mode
        length_desc = None
        source_type = None
        source_input = None
        if mode == "Knowledge Review":
            _run_knowledge_review(agent)
            continue
        if mode == "Content-Based Learning":
            length_desc = pick_content_length()
            source_type, source_input = pick_content_source()
        reply = agent.chat(mode_to_message(
            mode, length_desc, source_type, source_input,
            agent.student_level, agent.target_language_name,
        ))
        print_response(reply)
        if mode == "Content-Based Learning":
            # If the agent couldn't find content, let the user retry
            while _reply_is_no_content(reply):
                console.print()
                topic = checked_input(
                    "[bold cyan]Try a different topic (or Enter to skip):[/] "
                ).strip()
                if not topic:
                    break
                topic = _clarify_topic(topic)
                reply = agent.chat(mode_to_message(
                    mode, length_desc, "search", topic,
                    agent.student_level, agent.target_language_name,
                ))
                print_response(reply)
            else:
                _run_content_lesson(agent, reply)
            # After lesson, loop back to menu
            continue
        return


# ---------------------------------------------------------------------------
# Background audio generation and playback
# ---------------------------------------------------------------------------
import subprocess as _sp

_audio_lock = threading.Lock()
_audio_cache: dict = {}  # "thread", "path", "player"


def _bg_audio_worker(text: str) -> None:
    """Background worker: generate audio and store the path."""
    try:
        from voice.elevenlabs import generate_speech
        path = generate_speech(text)
        with _audio_lock:
            _audio_cache["path"] = path
    except Exception:
        with _audio_lock:
            _audio_cache["path"] = None


def _start_bg_audio(text: str) -> None:
    """Kick off background audio generation."""
    _stop_audio()
    with _audio_lock:
        _audio_cache.clear()
    t = threading.Thread(target=_bg_audio_worker, args=(text,), daemon=True)
    with _audio_lock:
        _audio_cache["thread"] = t
    t.start()


def _play_audio_file(path: str) -> None:
    """Start afplay in the background (non-blocking)."""
    _stop_audio()
    try:
        proc = _sp.Popen(["afplay", path])
        with _audio_lock:
            _audio_cache["player"] = proc
            _audio_cache["player_path"] = path
        console.print("  [dim]Playing audio... (type [bold]/stop[/bold] to stop)[/]")
    except FileNotFoundError:
        console.print("  [dim yellow]No audio player found (afplay).[/]")


def _stop_audio() -> None:
    """Stop any currently playing audio and clean up all cached files."""
    with _audio_lock:
        proc = _audio_cache.pop("player", None)
        player_path = _audio_cache.pop("player_path", None)
        cached_path = _audio_cache.pop("path", None)
    if proc and proc.poll() is None:
        proc.terminate()
        console.print("  [dim]Audio stopped.[/]")
    for p in (player_path, cached_path):
        if p:
            try:
                os.remove(p)
            except OSError:
                pass


def _play_cached_audio() -> None:
    """Wait for bg audio to finish, then play it."""
    with _audio_lock:
        t = _audio_cache.get("thread")
    if t is None:
        console.print("  [dim yellow]No audio queued. Try /audio-on first.[/]")
        return
    if isinstance(t, threading.Thread) and t.is_alive():
        console.print("  [dim]Waiting for audio...[/]")
        t.join(timeout=30)
    with _audio_lock:
        path = _audio_cache.get("path")
    if not path:
        console.print("  [dim yellow]Audio generation failed.[/]")
        return
    _play_audio_file(path)


def _generate_or_play_audio(text: str) -> None:
    """Synchronously generate then play audio (for manual /audio without auto mode)."""
    try:
        from voice.elevenlabs import generate_speech
        console.print("  [dim]Generating audio...[/]")
        path = generate_speech(text)
        _play_audio_file(path)
    except ImportError:
        console.print("  [dim yellow]ElevenLabs not configured. Set ELEVENLABS_API_KEY in .env[/]")
    except Exception as e:
        console.print(f"  [dim yellow]Audio error: {e}[/]")


def _run_content_lesson(agent: TutorAgent, text_reply: str) -> None:
    """Run the full content-based learning flow after the text is displayed."""
    start_bg_generate("mc", MC_SYSTEM_PROMPT, text_reply)

    # Pre-generate audio in background if auto mode is on
    if _audio_auto:
        _start_bg_audio(text_reply)
        console.print("  [dim]Audio generating in background. Type /audio to listen.[/]")

    # Phase 1: Reading
    _phase_banner(1)
    while True:
        try:
            answer = checked_input(
                "[dim]Press Enter when you're ready for questions, "
                "[bold]/easier[/bold] for a simpler version, "
                "[bold]/improve <topic>[/bold] to mix something in, "
                "or [bold]/audio[/bold] to listen...[/] "
            )
        except (EOFError, KeyboardInterrupt):
            answer = ""

        lower = answer.lower().strip()

        if lower in ("/audio", "audio"):
            if _audio_auto and _audio_cache.get("thread") is not None:
                _play_cached_audio()
            else:
                _generate_or_play_audio(text_reply)
            continue

        if lower in ("/easier", "easier"):
            console.print("\n  [dim]Rewriting at a simpler level...[/]")
            text_reply = agent.chat(content_learning_simplify_prompt())
            print_response(text_reply)
            # Re-prefetch questions for the new text
            start_bg_generate("mc", MC_SYSTEM_PROMPT, text_reply)
            continue

        if lower.startswith("/improve "):
            topic = answer[len("/improve "):].strip()
            if not topic:
                console.print("  [dim]Usage: /improve <topic>[/]")
                continue
            console.print(f"\n  [dim]Reworking text with \"{topic}\"...[/]")
            text_reply = agent.chat(content_learning_improve_prompt(topic))
            print_response(text_reply)
            start_bg_generate("mc", MC_SYSTEM_PROMPT, text_reply)
            continue

        # Moving on to questions — clean up any unused audio
        _stop_audio()
        break

    # Phase 2: Comprehension MC (kicks off vocab generation in background)
    _phase_banner(2)
    text = run_mc_quiz(agent, text_reply)
    # Phase 3: Vocabulary MC
    if text:
        _phase_banner(3)
        run_vocab_quiz(agent, text)
    # Phase 4: Short answer — exactly 2 questions
    _phase_banner(4)
    for i in range(1, 3):
        sa_reply = agent.chat(content_learning_short_answer_prompt(i))
        print_response(sa_reply)
        answer = checked_input(_input_prompt())
        if not answer:
            continue
        feedback = agent.chat(answer)
        print_response(feedback)

    # Lesson complete
    console.print()
    console.print(Rule("[bold green]Lesson Complete[/]", style="green"))


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main() -> None:
    console.print(BANNER)
    console.print("  [dim]Your personal language tutor · Type [bold]?[/bold] for commands · [bold]quit[/bold] to exit[/]\n")

    global _active_agent, _current_mode
    agent = TutorAgent()
    _active_agent = agent
    agent.on_tool_call = on_tool_call

    # Agent speaks first
    opening = agent.chat("__session_start__")
    print_response(opening)

    # New user: run onboarding conversation before showing mode picker
    if not agent.profile:
        while not agent.profile:
            try:
                msg = checked_input("[bold cyan]You:[/] ")
            except (EOFError, KeyboardInterrupt):
                console.print("\n  [bold green]¡Hasta luego! 👋[/]\n")
                return
            if not msg:
                continue
            reply = agent.chat(msg)
            print_response(reply)
            # Reload profile in case the agent saved it via update_student_profile
            agent.profile = load_student_profile()

    # Show interactive mode picker
    try:
        _pick_and_run_mode(agent)
    except SessionExit:
        console.print("\n  [bold green]¡Hasta luego! 👋[/]\n")
        return

    # Main input loop
    while True:
        console.print()
        try:
            msg = _prompt_input(_input_prompt()).strip()
        except (EOFError, KeyboardInterrupt, SessionExit):
            break

        if not msg:
            continue

        lower = msg.lower()

        # Exit
        if lower in _EXIT_COMMANDS:
            break

        # Commands
        if lower in ("?", "/help"):
            show_help()
            continue

        if lower == "/menu":
            try:
                _pick_and_run_mode(agent)
            except SessionExit:
                break
            continue

        if lower == "/profile":
            _show_profile()
            continue

        if lower == "/model":
            _pick_model()
            continue

        if lower == "/sources":
            _show_sources()
            continue

        if lower == "/tools":
            _show_tools()
            continue

        if lower == "/reset":
            try:
                agent = TutorAgent()
                _active_agent = agent
                agent.on_tool_call = on_tool_call
                console.print("\n  [dim]Session reset.[/]\n")
                opening = agent.chat("__session_start__")
                print_response(opening)
                _pick_and_run_mode(agent)
            except SessionExit:
                break
            continue

        # Normal message
        try:
            reply = agent.chat(msg)
            console.print()
            print_response(reply)
            _play_audio(agent)
        except SessionExit:
            break

    console.print("\n  [bold green]¡Hasta luego! 👋[/]\n")


if __name__ == "__main__":
    main()
