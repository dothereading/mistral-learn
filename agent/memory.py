"""File-based memory: student profile, session logs, source files."""

import os
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
MEMORY_DIR = os.path.join(BASE_DIR, "memory")
SOURCES_DIR = os.path.join(BASE_DIR, "sources")
SOUL_DIR = os.path.join(BASE_DIR, "soul")
SKILLS_DIR = os.path.join(BASE_DIR, "skills")


def load_file(relative_path: str) -> str | None:
    """Load a file relative to the project root. Returns None if missing."""
    path = os.path.join(BASE_DIR, relative_path)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return f.read()


def load_student_profile() -> str | None:
    """Load memory/USER.md. Returns None if the student is new."""
    return load_file("memory/USER.md")


def save_student_profile(content: str) -> None:
    """Write the full student profile to memory/USER.md."""
    os.makedirs(MEMORY_DIR, exist_ok=True)
    path = os.path.join(MEMORY_DIR, "USER.md")
    with open(path, "w") as f:
        f.write(content)


def update_student_profile(updates: str) -> str:
    """Append observations to the student profile. Creates it if needed.

    Returns the updated profile content.
    """
    current = load_student_profile() or "# Student Profile\n"
    # If updates look like a full profile replacement (starts with #), overwrite
    if updates.strip().startswith("# Student Profile"):
        save_student_profile(updates)
        return updates
    # Otherwise append
    updated = current.rstrip() + "\n" + updates.strip() + "\n"
    save_student_profile(updated)
    return updated


def save_session_log(content: str, session_date: date | None = None) -> str:
    """Append to today's session log. Returns the log path."""
    session_date = session_date or date.today()
    sessions_dir = os.path.join(MEMORY_DIR, "sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    path = os.path.join(sessions_dir, f"{session_date.isoformat()}.md")
    with open(path, "a") as f:
        f.write(content + "\n")
    return path


def load_skill(skill_path: str) -> str | None:
    """Load a skill file from skills/{skill_path}."""
    return load_file(os.path.join("skills", skill_path))


def list_source_files() -> list[str]:
    """List .txt files in sources/ folder."""
    if not os.path.exists(SOURCES_DIR):
        return []
    return sorted(f for f in os.listdir(SOURCES_DIR) if f.endswith(".txt"))


def read_source(filename: str) -> str | None:
    """Read a source file. Truncates to ~2000 words if very long."""
    path = os.path.join(SOURCES_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        content = f.read()
    words = content.split()
    if len(words) > 2000:
        content = " ".join(words[:2000]) + "\n\n[... truncated, full file has {} words]".format(len(words))
    return content


def save_source(filename: str, content: str) -> str:
    """Save content to sources/{filename}. Returns the path."""
    os.makedirs(SOURCES_DIR, exist_ok=True)
    path = os.path.join(SOURCES_DIR, filename)
    with open(path, "w") as f:
        f.write(content)
    return path
