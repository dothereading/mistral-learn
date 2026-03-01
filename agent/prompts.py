"""Dynamic system prompt builder. Rebuilt every turn."""


# ---------------------------------------------------------------------------
# Mode prompt builders
# ---------------------------------------------------------------------------


def content_learning_write_prompt(
    length_desc: str, source_type: str | None, source_input: str | None
) -> str:
    """Build the user message for Content-Based Learning text-writing phase."""
    write_rules = (
        "WRITING RULES:\n"
        "LENGTH CONSTRAINT — STRICTLY {length_desc}. Do NOT exceed this. "
        "If the limit is 1 paragraph, write exactly 1 paragraph.\n"
        "Write an ORIGINAL text in the target language. "
        "Adapt to the student's level (i+1): they should understand ~95-98%. "
        "Err on the side of TOO EASY rather than too hard — the student should "
        "feel confident, not overwhelmed. At most 1 unfamiliar word per sentence "
        "for beginners; use high-frequency vocabulary throughout. "
        "Surround any new words with strong context clues so meaning is obvious. "
        "Stay on topic — no unrelated analogies from student interests. "
        "Output ONLY the text. No vocab lists, no questions, no explanations."
    ).format(length_desc=length_desc)

    if source_type == "search" and source_input:
        return (
            f"[Mode: Content-Based Learning]\n"
            f"Step 1: Search in the TARGET LANGUAGE — call search_youtube "
            f"and lookup_wikipedia with the language parameter set to the "
            f'target language to find information about "{source_input}". '
            f"Use target-language search terms.\n"
            f"Step 2: {write_rules}\n"
            f"Step 3: After the text, add a short '---\\nFuentes / Sources' "
            f"section with 2-3 markdown hyperlinks to the native-language "
            f"sources you found. Format each as `[descriptive title](url)` "
            f"— for example `[Video: Mi tema](https://youtube.com/watch?v=...)` "
            f"or `[Wikipedia: Tema](https://es.wikipedia.org/wiki/...)`. "
            f"The student can click these to explore further."
        )
    elif source_type == "url" and source_input:
        return (
            f"[Mode: Content-Based Learning]\n"
            f'Step 1: Call add_source with url="{source_input}" to save it.\n'
            f"Step 2: Call read_source to load the saved content.\n"
            f"Step 3: {write_rules}"
        )
    elif source_type == "saved" and source_input:
        return (
            f"[Mode: Content-Based Learning]\n"
            f'Step 1: Call read_source with filename="{source_input}" to load the saved content.\n'
            f"Step 2: {write_rules}"
        )
    else:
        return f"[Mode: Content-Based Learning]\n{write_rules}"


def content_learning_simplify_prompt() -> str:
    """Prompt the agent to rewrite the text at a lower level."""
    return (
        "[System: The student found the text too difficult. Rewrite it at a "
        "MUCH simpler level — shorter sentences, more common vocabulary, less "
        "complex grammar. They should understand 98-100% of it. Keep the same "
        "topic and roughly the same length. Output ONLY the rewritten text, "
        "nothing else.]"
    )


def content_learning_short_answer_prompt() -> str:
    """Build the system injection for the short-answer phase after quizzes."""
    return (
        "[System: The quizzes are complete. Now ask the student ONE "
        "short-answer question about the text. Ask them to summarize, "
        "give an opinion, or describe something from the text in their "
        "own words. Keep it natural — no grammar jargon. Present one "
        "question and wait.]"
    )


def knowledge_review_prompt() -> str:
    """Mode instructions for Knowledge Review."""
    return (
        "Go through SRS items that are due. NOT as flashcards — weave review "
        "into natural exchanges:\n"
        "- Short conversations using due vocabulary\n"
        "- Fill-in-the-blank in fresh sentences\n"
        '- "How would you say X in a restaurant?"\n'
        "- Quick translation challenges\n"
        "- For grammar patterns: create a natural situation where the student "
        "needs to use it — don't ask them to \"conjugate\" or \"use the "
        'subjunctive," just put them in a context where they\'d naturally say it\n\n'
        "Call `get_due_reviews` at the start. In this mode review is the primary "
        "activity. In other modes, opportunistically weave due items in."
    )


def roleplay_prompt() -> str:
    """Mode instructions for Role Play."""
    return (
        "Simulated real-world scenarios. You play a character (waiter, shopkeeper, "
        "new friend, coworker, customs officer) and the student practices conversation. "
        "Adapt complexity to their level:\n"
        "- Beginners: heavy scaffolding, hints, slow pace\n"
        "- Advanced: natural-speed conversation with idioms\n\n"
        "Correct errors mid-roleplay without breaking immersion — use recasting "
        "(repeat correctly without calling it out explicitly), then note the pattern "
        "briefly after the exchange."
    )


def qa_prompt() -> str:
    """Mode instructions for Q&A."""
    return (
        "Open-ended. Student asks anything: grammar questions, \"how do you say...\", "
        "cultural questions, pronunciation help, \"what's the difference between X "
        'and Y". Answer clearly at their level and turn answers into mini-lessons '
        "when appropriate."
    )


def custom_prompt() -> str:
    """Mode instructions for Custom mode."""
    return (
        "Student directs. Adapt to whatever they need: job interview prep, email "
        "writing practice, slang, specific topics. Follow their lead."
    )


def _content_learning_mode_prompt() -> str:
    """Mode instructions for Content-Based Learning (injected into system prompt)."""
    return (
        "The student consumes content (reading or listening) and you ask comprehension "
        "and vocabulary questions about it. Content can be AI-generated, real content "
        "via YouTube/Wikipedia/saved sources, or user-provided URLs.\n\n"
        "NEVER paste raw source material at the student. ALWAYS rewrite it as an "
        "original text adapted to their level. Load `language-acquisition/SKILL.md` "
        "before writing. Apply i+1 principles.\n\n"
        "The interface handles comprehension and vocabulary MC quizzes automatically. "
        "After the quizzes, you take over for short-answer work: open-ended questions "
        "that get the student producing language naturally. Keep it conversational — "
        "no grammar jargon. Present one question at a time."
    )


_MODE_PROMPT_MAP: dict[str, callable] = {
    "Content-Based Learning": _content_learning_mode_prompt,
    "Knowledge Review": knowledge_review_prompt,
    "Role Play": roleplay_prompt,
    "Q&A": qa_prompt,
    "Custom": custom_prompt,
}


def _get_mode_instructions(mode: str) -> str:
    """Look up mode-specific instructions. Returns empty string for unknown modes."""
    builder = _MODE_PROMPT_MAP.get(mode)
    return builder() if builder else ""


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------


def build_system_prompt(
    soul_md: str,
    student_profile: str | None,
    skill_index: str,
    due_reviews: list[dict],
    session_history_summary: str | None = None,
    current_mode: str | None = None,
    available_sources: list[str] | None = None,
) -> str:
    """Build the system prompt from components. Called before every LLM request."""

    parts = [soul_md]

    # Student context
    if student_profile:
        parts.append(f"## Current Student\n{student_profile}")
    else:
        parts.append(
            "## New Student\n"
            "No student profile exists. Run the onboarding flow: ask what language "
            "they want to learn, their age bracket (for content appropriateness), "
            "assess their level conversationally, ask about goals and interests. "
            "Be warm and welcoming. Call `update_student_profile` after each piece "
            "of information to save it progressively."
        )

    # Current session mode
    if current_mode:
        mode_instructions = _get_mode_instructions(current_mode)
        parts.append(f"## Current Mode: {current_mode}\n{mode_instructions}")
    elif student_profile:
        parts.append(
            "## Session Start\n"
            "Greet the student warmly in one short line. Do NOT show a session menu — "
            "the interface handles mode selection. Do NOT re-ask onboarding questions."
        )

    # Due reviews
    if due_reviews:
        lines = []
        for r in due_reviews:
            label = r.get("word") or r.get("pattern_name", "?")
            detail = r.get("translation") or r.get("pattern_description", "")
            last = r.get("last_reviewed", "never")
            lines.append(f"- [{r['item_type']}] {label} ({detail}) — last seen {last}")
        review_text = "\n".join(lines)
        parts.append(
            f"## Items Due for Review ({len(due_reviews)} total)\n"
            f"Weave these into the conversation naturally:\n{review_text}"
        )

    # Available sources
    if available_sources:
        sources_text = "\n".join(f"- {s}" for s in available_sources)
        parts.append(
            f"## Available Source Material\n"
            f"The student has these saved sources you can use for content-based lessons:\n{sources_text}"
        )

    # Skills index
    parts.append(
        f"## Available Skills\n"
        f"Use `read_skill` tool to load any of these when needed:\n{skill_index}"
    )

    # Custom tools
    from custom_tools import get_custom_tool_info

    custom_tools = get_custom_tool_info()
    if custom_tools:
        names = ", ".join(t["name"] for t in custom_tools)
        parts.append(
            f"## Custom Tools\n"
            f"You have {len(custom_tools)} custom-built tool{'s' if len(custom_tools) != 1 else ''}: {names}."
        )

    # Self-extending tools
    parts.append(
        "## Self-Extending Tools\n"
        "If the student asks for something that requires a capability you don't "
        "have, you can propose building a new tool using `propose_tool`. Always "
        "ask for confirmation before building. Keep tools focused and simple."
    )

    # Session context
    if session_history_summary:
        parts.append(f"## This Session So Far\n{session_history_summary}")

    return "\n\n".join(parts)
