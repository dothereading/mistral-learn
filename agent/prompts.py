"""Dynamic system prompt builder. Rebuilt every turn."""


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
        parts.append(
            f"## Current Mode: {current_mode}\n"
            "Adapt your behavior to this mode. See Session Modes in your soul for details."
        )
    elif student_profile:
        parts.append(
            "## Session Start\n"
            "The student hasn't chosen a mode yet. Suggest 1-2 based on context "
            "(items due for review? suggest Knowledge Review. First session in a while? "
            "suggest Content-Based Learning to ease back in). Keep it natural, not a numbered menu."
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

    # Session context
    if session_history_summary:
        parts.append(f"## This Session So Far\n{session_history_summary}")

    return "\n\n".join(parts)
