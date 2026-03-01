import json
import random
import sys
import os
import threading
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from mistralai import Mistral
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
import config
from agent.core import TutorAgent
from agent.memory import list_source_files, load_student_profile
from agent.prompts import (
    content_learning_write_prompt,
    content_learning_short_answer_prompt,
    content_learning_simplify_prompt,
)

console = Console()

# ---------------------------------------------------------------------------
# Lightweight LLM helper (no agent context, no tools, no history)
# ---------------------------------------------------------------------------
_llm_client = Mistral(api_key=config.MISTRAL_API_KEY)


def _llm_call(system: str, user: str) -> str:
    """Single-shot LLM call with just a system prompt and user message."""
    resp = _llm_client.chat.complete(
        model=config.MISTRAL_MODEL,
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


_prefetch_lock = threading.Lock()
_prefetched_questions: list[dict] | None = None
_prefetched_text: str | None = None
_prefetch_thread: threading.Thread | None = None


def _prefetch_worker(text: str) -> None:
    """Background: generate 5 MC questions from just the text."""
    global _prefetched_questions, _prefetched_text
    try:
        raw = _llm_call(MC_SYSTEM_PROMPT, text)
        questions = _parse_json_response(raw)
        if questions:
            with _prefetch_lock:
                _prefetched_questions = questions
                _prefetched_text = text
    except Exception:
        pass


def start_prefetch(text: str) -> None:
    """Kick off background MC generation from the adapted text."""
    global _prefetch_thread, _prefetched_questions, _prefetched_text
    with _prefetch_lock:
        _prefetched_questions = None
        _prefetched_text = None
    _prefetch_thread = threading.Thread(
        target=_prefetch_worker, args=(text,), daemon=True
    )
    _prefetch_thread.start()


def get_prefetched_questions() -> tuple[list[dict] | None, str | None]:
    """Block until prefetch finishes (or times out). Returns (questions, text)."""
    global _prefetched_questions, _prefetched_text, _prefetch_thread
    if _prefetch_thread is not None:
        _prefetch_thread.join(timeout=30)
    with _prefetch_lock:
        qs = _prefetched_questions
        txt = _prefetched_text
        _prefetched_questions = None
        _prefetched_text = None
        _prefetch_thread = None
    return qs, txt


def _shuffle_options(q: dict) -> dict:
    """Return a copy of the question with options in a random order."""
    correct_idx = q["correct"]
    # Pair each option with a flag indicating if it's the correct one
    indexed = [(text, i == correct_idx) for i, text in enumerate(q["options"])]
    random.shuffle(indexed)
    options = [text for text, _ in indexed]
    new_correct = next(i for i, (_, is_correct) in enumerate(indexed) if is_correct)
    return {
        "question": q["question"],
        "options": options,
        "correct": new_correct,
    }


def _run_mc_round(
    questions: list[dict], text: str, title: str = "Quiz"
) -> tuple[int, list[dict]]:
    """Display MC questions one at a time. Returns (score, list_of_missed)."""
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
            answer = console.input("[bold cyan]Your answer (1-4):[/] ").strip()
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


def run_mc_quiz(agent: TutorAgent) -> str | None:
    """Run the comprehension MC quiz. Returns the text for follow-up quizzes."""
    console.print("\n  [dim]Preparing comprehension questions...[/]")
    questions, text = get_prefetched_questions()
    if not questions or not text:
        reply = agent.chat(
            "[System: Generate the first multiple-choice question about "
            "the text you wrote. Present one question with 4 options.]"
        )
        print_response(reply)
        return None

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

    score, missed = _run_mc_round(questions, text, title="Vocab")

    # Auto-add missed vocab to SRS
    from db.srs import add_review_item
    lang = agent.target_language or "es"
    added = 0
    for q in missed:
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
            except Exception:
                pass

    if added:
        console.print(f"\n  [dim]📝 Added {added} missed word{'s' if added != 1 else ''} to your review deck.[/]")

    agent.history.append({
        "role": "user",
        "content": f"[Vocab quiz complete: {score}/{len(questions)} correct, {added} added to SRS]",
    })
    agent.history.append({
        "role": "assistant",
        "content": f"Vocab quiz done — {score}/{len(questions)}. Moving to short answer.",
    })

BANNER = r"""[bold green]
  ███╗   ███╗██╗███████╗████████╗██████╗  █████╗ ██╗
  ████╗ ████║██║██╔════╝╚══██╔══╝██╔══██╗██╔══██╗██║
  ██╔████╔██║██║███████╗   ██║   ██████╔╝███████║██║
  ██║╚██╔╝██║██║╚════██║   ██║   ██╔══██╗██╔══██║██║
  ██║ ╚═╝ ██║██║███████║   ██║   ██║  ██║██║  ██║███████╗
  ╚═╝     ╚═╝╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝

  ██╗     ███████╗ █████╗ ██████╗ ███╗   ██╗
  ██║     ██╔════╝██╔══██╗██╔══██╗████╗  ██║
  ██║     █████╗  ███████║██████╔╝██╔██╗ ██║
  ██║     ██╔══╝  ██╔══██║██╔══██╗██║╚██╗██║
  ███████╗███████╗██║  ██║██║  ██║██║ ╚████║
  ╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝
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
    ("Role Play", "🎭"),
    ("Q&A", "❓"),
    ("Custom", "🛠️"),
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
def print_response(text: str) -> None:
    """Print an agent response inside a green-bordered panel."""
    md = Markdown(text)
    panel = Panel(md, border_style="green", padding=(1, 2))
    console.print(panel)


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
    table.add_row("/easier", "Simplify the current text (during content lessons)")
    table.add_row("/reset", "Start fresh session")
    table.add_row("quit", "Exit")
    console.print()
    console.print(table)
    console.print()


def pick_mode() -> str | None:
    """Show mode picker, return the selected mode name or None."""
    rows = []
    for i, (name, icon) in enumerate(SESSION_MODES, 1):
        rows.append(f"  [bold][cyan][{i}][/cyan][/bold] {icon} {name}")
    body = "\n".join(rows)
    console.print()
    console.print(Panel(body, title="Session Mode", border_style="cyan", padding=(1, 2)))
    try:
        choice = console.input("[bold cyan]Pick a mode (1-5):[/] ").strip()
        idx = int(choice) - 1
        if 0 <= idx < len(SESSION_MODES):
            name = SESSION_MODES[idx][0]
            console.print(f"  [dim]→ {name}[/]")
            return name
    except (ValueError, EOFError):
        pass
    console.print("  [dim]Invalid choice, skipping.[/]")
    return None


def pick_content_length() -> str | None:
    """Show content-length picker, return description or None."""
    rows = []
    for i, (label, desc) in enumerate(CONTENT_LENGTHS, 1):
        rows.append(f"  [bold][cyan][{i}][/cyan][/bold] {label} — {desc}")
    body = "\n".join(rows)
    console.print()
    console.print(Panel(body, title="Content Length", border_style="cyan", padding=(1, 2)))
    try:
        choice = console.input("[bold cyan]Pick a length (1-3):[/] ").strip()
        idx = int(choice) - 1
        if 0 <= idx < len(CONTENT_LENGTHS):
            label = CONTENT_LENGTHS[idx][0]
            console.print(f"  [dim]→ {label}[/]")
            return LENGTH_TO_DESCRIPTION[label]
    except (ValueError, EOFError):
        pass
    return None


CONTENT_SOURCES = [
    ("Search a topic", "🔍"),
    ("Enter a URL", "🔗"),
    ("Saved source", "📂"),
    ("Generate a story", "📝"),
]


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
        choice = console.input("[bold cyan]Pick a source (1-4), or type a topic:[/] ").strip()
        if not choice:
            return ("search", None)
        # If the user pasted a URL directly, treat as URL
        if choice.startswith(("http://", "https://", "www.")):
            console.print(f"  [dim]→ URL: {choice}[/]")
            return ("url", choice)
        # Try as a number
        try:
            idx = int(choice) - 1
        except ValueError:
            # Not a number — treat as a search topic
            console.print(f"  [dim]→ Searching: {choice}[/]")
            return ("search", choice)
        if idx == 0:
            topic = console.input("[bold cyan]Topic:[/] ").strip()
            if not topic:
                return ("search", None)
            console.print(f"  [dim]→ Searching: {topic}[/]")
            return ("search", topic)
        elif idx == 1:
            url = console.input("[bold cyan]URL:[/] ").strip()
            console.print(f"  [dim]→ URL: {url}[/]")
            return ("url", url)
        elif idx == 2:
            if not sources:
                console.print("  [dim]No saved sources. Falling back to search.[/]")
                topic = console.input("[bold cyan]Topic:[/] ").strip()
                if not topic:
                    return ("search", None)
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
) -> str:
    """Build the message sent to the agent when a mode is picked."""
    if mode == "Content-Based Learning" and length_desc:
        return content_learning_write_prompt(length_desc, source_type, source_input)
    if mode == "Custom":
        return "[Mode: Custom] Ask the student what they'd like to focus on."
    return f"[Mode: {mode}] Start a {mode} session."


def on_tool_call(name: str, _arguments: str) -> None:
    """Callback: print a dim status line when the agent calls a tool."""
    if name == "__malformed__":
        console.print("  [dim yellow]⚠ Malformed tool call, retrying...[/]")
        return
    label = TOOL_LABELS.get(name, name)
    console.print(f"  [dim]⚡ {label}...[/]")


def _run_content_lesson(agent: TutorAgent, text_reply: str) -> None:
    """Run the full content-based learning flow after the text is displayed."""
    start_prefetch(text_reply)
    console.print()
    try:
        answer = console.input(
            "[dim]Press Enter when you're ready for questions, "
            "or type [bold]/easier[/bold] for a simpler version...[/] "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""

    if answer in ("/easier", "easier"):
        console.print("\n  [dim]Rewriting at a simpler level...[/]")
        text_reply = agent.chat(content_learning_simplify_prompt())
        print_response(text_reply)
        # Re-prefetch questions for the new text
        start_prefetch(text_reply)
        console.print()
        try:
            console.input("[dim]Press Enter when you're ready for questions...[/]")
        except (EOFError, KeyboardInterrupt):
            pass

    # Phase 1: Comprehension MC
    text = run_mc_quiz(agent)
    # Phase 2: Vocabulary MC
    if text:
        run_vocab_quiz(agent, text)
    # Phase 3: Short answer (agent takes over)
    sa_reply = agent.chat(content_learning_short_answer_prompt())
    print_response(sa_reply)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main() -> None:
    console.print(BANNER)
    console.print("  [dim]Your personal language tutor · Type [bold]?[/bold] for commands · [bold]quit[/bold] to exit[/]\n")

    agent = TutorAgent()
    agent.on_tool_call = on_tool_call

    # Agent speaks first
    opening = agent.chat("__session_start__")
    print_response(opening)

    # Show interactive mode picker for returning or new users
    mode = pick_mode()
    if mode:
        length_desc = None
        source_type = None
        source_input = None
        if mode == "Content-Based Learning":
            length_desc = pick_content_length()
            source_type, source_input = pick_content_source()
        msg = mode_to_message(mode, length_desc, source_type, source_input)
        console.print()
        reply = agent.chat(msg)
        print_response(reply)
        if mode == "Content-Based Learning":
            _run_content_lesson(agent, reply)

    # Main input loop
    while True:
        console.print()
        try:
            msg = console.input("[bold cyan]You:[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not msg:
            continue

        lower = msg.lower()

        # Exit
        if lower in ("quit", "exit", "q"):
            break

        # Commands
        if lower in ("?", "/help"):
            show_help()
            continue

        if lower == "/menu":
            mode = pick_mode()
            if mode:
                length_desc = None
                source_type = None
                source_input = None
                if mode == "Content-Based Learning":
                    length_desc = pick_content_length()
                    source_type, source_input = pick_content_source()
                reply = agent.chat(mode_to_message(mode, length_desc, source_type, source_input))
                print_response(reply)
                if mode == "Content-Based Learning":
                    _run_content_lesson(agent, reply)
            continue

        if lower == "/profile":
            profile = load_student_profile()
            if profile:
                console.print()
                console.print(Panel(Markdown(profile), title="Student Profile", border_style="magenta", padding=(1, 2)))
            else:
                console.print("\n  [dim]No profile yet — keep chatting and I'll learn about you![/]")
            console.print()
            continue

        if lower == "/sources":
            sources = list_source_files()
            if sources:
                console.print()
                for s in sources:
                    console.print(f"  [dim]•[/] {s}")
            else:
                console.print("\n  [dim]No sources saved yet.[/]")
            console.print()
            continue

        if lower == "/tools":
            from custom_tools import get_custom_tool_info

            tools = get_custom_tool_info()
            if tools:
                console.print()
                for t in tools:
                    console.print(f"  [dim]•[/] [bold]{t['name']}[/] — {t['description']}")
            else:
                console.print("\n  [dim]No custom tools yet. Ask the tutor to build one![/]")
            console.print()
            continue

        if lower == "/reset":
            agent = TutorAgent()
            agent.on_tool_call = on_tool_call
            console.print("\n  [dim]Session reset.[/]\n")
            opening = agent.chat("__session_start__")
            print_response(opening)
            mode = pick_mode()
            if mode:
                length_desc = None
                source_type = None
                source_input = None
                if mode == "Content-Based Learning":
                    length_desc = pick_content_length()
                    source_type, source_input = pick_content_source()
                reply = agent.chat(mode_to_message(mode, length_desc, source_type, source_input))
                print_response(reply)
                if mode == "Content-Based Learning":
                    _run_content_lesson(agent, reply)
            continue

        # Normal message
        reply = agent.chat(msg)
        console.print()
        print_response(reply)

    console.print("\n  [bold green]¡Hasta luego! 👋[/]\n")


if __name__ == "__main__":
    main()
