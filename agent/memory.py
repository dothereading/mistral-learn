"""File-based memory: student profile, session logs, source files."""

import os
from datetime import date

import yaml

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
MEMORY_DIR = os.path.join(BASE_DIR, "memory")
SOURCES_DIR = os.path.join(BASE_DIR, "sources")
SOUL_DIR = os.path.join(BASE_DIR, "soul")
SKILLS_DIR = os.path.join(BASE_DIR, "skills")

_PROFILE_PATH = os.path.join(MEMORY_DIR, "user.yaml")


def load_file(relative_path: str) -> str | None:
    """Load a file relative to the project root. Returns None if missing."""
    path = os.path.join(BASE_DIR, relative_path)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return f.read()


def load_student_profile() -> dict | None:
    """Load memory/user.yaml as a dict. Returns None if the student is new."""
    if not os.path.exists(_PROFILE_PATH):
        return None
    with open(_PROFILE_PATH, "r") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else None


def save_student_profile(data: dict) -> None:
    """Write the student profile dict to memory/user.yaml."""
    os.makedirs(MEMORY_DIR, exist_ok=True)
    with open(_PROFILE_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def update_student_profile(updates: dict) -> dict:
    """Merge updates into the existing profile. Creates it if needed.

    Returns the updated profile dict.
    """
    current = load_student_profile() or {}
    current.update(updates)
    save_student_profile(current)
    return current


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
