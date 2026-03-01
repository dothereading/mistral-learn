"""Dynamic system prompt builder. Rebuilt every turn."""


# ---------------------------------------------------------------------------
# Mode prompt builders
# ---------------------------------------------------------------------------


def content_learning_write_prompt(
    length_desc: str,
    source_type: str | None,
    source_input: str | None,
    student_level: str | None = None,
    target_language: str | None = None,
) -> str:
    """Build the user message for Content-Based Learning text-writing phase."""
    context_hint = ""
    if target_language:
        context_hint += f"LANGUAGE: Write ENTIRELY in {target_language}. Do NOT write in English. "
    if student_level:
        context_hint += f"The student's level is {student_level}. "
    write_rules = (
        "WRITING RULES:\n"
        "{context_hint}"
        "LENGTH CONSTRAINT — STRICTLY {length_desc}. Do NOT exceed this. "
        "Write an ORIGINAL text in the target language. "
        "Do NOT exhaustively summarize the source — pick the most interesting "
        "angle or moment and write about it. Be selective: a few vivid "
        "details beat a dry overview. "
        "Adapt to the student's level (i+1): they should understand ~95-98%. "
        "Err on the side of TOO EASY rather than too hard — the student should "
        "feel confident, not overwhelmed. At most 1 unfamiliar word per sentence "
        "for beginners; use high-frequency vocabulary throughout. "
        "Surround any new words with strong context clues so meaning is obvious. "
        "Output ONLY the text — no questions, no quizzes, no commentary, no instructions. "
        "Do NOT ask the student anything. Do NOT start a quiz. Just write the reading passage. "
        "Stick to {length_desc}."
        "You should add a title at the top."
    ).format(length_desc=length_desc, context_hint=context_hint)

    if source_type == "search" and source_input:
        return (
            f"[Mode: Content-Based Learning]\n"
            f"Step 1: Search in the TARGET LANGUAGE — call lookup_wikipedia "
            f"with the language parameter set to the target language to find "
            f'information about "{source_input}". Use target-language search '
            f"terms. Only call search_youtube if the student specifically "
            f"asked for a video or YouTube content.\n"
            f"Step 2: {write_rules}\n"
            f"Step 3: After the text, add a short '---\\nFuentes / Sources' "
            f"section with 2-3 markdown hyperlinks to the native-language "
            f"sources you found. Format each as `[descriptive title](url)` "
            f"— for example `[Wikipedia: Tema](https://es.wikipedia.org/wiki/...)`. "
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
        from agent.memory import read_source
        content = read_source(source_input)
        if content:
            # Truncate to ~800 words to keep prompt manageable
            words = content.split()
            if len(words) > 800:
                content = " ".join(words[:800]) + "..."
            return (
                f"[Mode: Content-Based Learning]\n"
                f"SOURCE MATERIAL (use this as the basis for your text):\n"
                f"---\n{content}\n---\n\n"
                f"{write_rules}"
            )
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
        "simpler level — shorter sentences, more common vocabulary, less "
        "complex grammar. They should understand or be able to infer everything from context. "
        "Keep the same topic and roughly the same length. Output ONLY the rewritten text, "
        "nothing else.]"
    )


def content_learning_short_answer_prompt(question_num: int = 1) -> str:
    """Build the system injection for the short-answer phase after quizzes."""
    if question_num == 1:
        return (
            "[System: The quizzes are complete. Now ask the student ONE "
            "short-answer question about the text. Ask them to summarize, "
            "give an opinion, or describe something from the text in their "
            "own words. Keep it natural — no grammar jargon. Present one "
            "question and wait.]"
        )
    return (
        "[System: Ask ONE more short-answer question about the text — "
        "different from the previous one. Could be an opinion, a comparison, "
        "or asking them to explain something in their own words. Keep it "
        "natural. Present the question and wait.]"
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
        "The student consumes content (reading or listening). Content can be "
        "AI-generated, real content via YouTube/Wikipedia/saved sources, or "
        "user-provided URLs.\n\n"
        "NEVER paste raw source material at the student. ALWAYS rewrite it as an "
        "original text adapted to their level. Load `language-acquisition/SKILL.md` "
        "before writing. Apply i+1 principles.\n\n"
        "IMPORTANT: Your ONLY job right now is to write the reading passage. "
        "Do NOT ask questions, do NOT start a quiz, do NOT prompt the student. "
        "The interface handles all quizzes automatically after the text is displayed."
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


def _format_profile(profile: dict) -> str:
    """Format a student profile dict into readable text for the system prompt."""
    lines = ["# Student Profile"]
    if "language" in profile:
        lang = profile["language"]
        variant = profile.get("variant")
        lines.append(f"Language: {lang} ({variant})" if variant else f"Language: {lang}")
    if "level" in profile:
        lines.append(f"Level: {profile['level']}")
    if "goals" in profile:
        lines.append(f"Goals: {profile['goals']}")
    return "\n".join(lines)


def build_system_prompt(
    soul_md: str,
    student_profile: dict | None,
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
        parts.append(f"## Current Student\n{_format_profile(student_profile)}")
    else:
        parts.append(
            "## New Student\n"
            "No student profile exists. Run the onboarding flow: ask what language "
            "they want to learn, their age bracket (for content appropriateness), "
            "assess their level conversationally, ask about goals and interests. "
            "Be warm and welcoming. Call `update_student_profile` with structured "
            "fields (language, variant, level, goals) after each piece "
            "of information to save it progressively. Do NOT ask about interests."
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
            f"The student has these saved sources you can use for content-based lessons:\n{sources_text}\n"
            f"Do NOT call `list_sources` — you already have the full list here."
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
