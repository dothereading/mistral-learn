"""Tests for agent/memory.py — file-based memory operations."""

import os
import pytest
from agent.memory import (
    load_file,
    load_student_profile,
    save_student_profile,
    update_student_profile,
    save_session_log,
    load_skill,
    list_source_files,
    read_source,
    save_source,
)


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """Point all memory/source paths to temp directories."""
    monkeypatch.setattr("agent.memory.BASE_DIR", str(tmp_path))
    monkeypatch.setattr("agent.memory.MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setattr("agent.memory.SOURCES_DIR", str(tmp_path / "sources"))
    monkeypatch.setattr("agent.memory.SKILLS_DIR", str(tmp_path / "skills"))
    return tmp_path


class TestLoadFile:
    def test_existing_file(self, isolated_dirs):
        path = isolated_dirs / "test.txt"
        path.write_text("hello world")
        result = load_file("test.txt")
        assert result == "hello world"

    def test_missing_file(self):
        assert load_file("nonexistent.txt") is None


class TestStudentProfile:
    def test_no_profile_returns_none(self):
        assert load_student_profile() is None

    def test_save_and_load(self):
        save_student_profile("# Student\n- Level: A1")
        profile = load_student_profile()
        assert "Level: A1" in profile

    def test_update_appends(self):
        save_student_profile("# Student Profile\n- Level: A1")
        result = update_student_profile("- Interests: cooking")
        assert "Level: A1" in result
        assert "Interests: cooking" in result

    def test_update_creates_if_missing(self):
        result = update_student_profile("- Level: A2")
        assert "Student Profile" in result
        assert "Level: A2" in result

    def test_update_full_replacement(self):
        save_student_profile("# Student Profile\n- Level: A1")
        new_profile = "# Student Profile\n- Level: B1\n- Goals: travel"
        result = update_student_profile(new_profile)
        assert "B1" in result
        assert "A1" not in result


class TestSessionLog:
    def test_creates_log_file(self, isolated_dirs):
        from datetime import date
        path = save_session_log("Test entry", session_date=date(2026, 3, 1))
        assert os.path.exists(path)
        assert "2026-03-01.md" in path
        with open(path) as f:
            assert "Test entry" in f.read()

    def test_appends_to_existing(self, isolated_dirs):
        from datetime import date
        d = date(2026, 3, 1)
        save_session_log("First entry", session_date=d)
        save_session_log("Second entry", session_date=d)
        path = os.path.join(str(isolated_dirs), "memory", "sessions", "2026-03-01.md")
        with open(path) as f:
            content = f.read()
        assert "First entry" in content
        assert "Second entry" in content


class TestSkills:
    def test_load_existing_skill(self, isolated_dirs):
        skill_dir = isolated_dirs / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Test Skill\nContent here.")
        result = load_skill("test-skill/SKILL.md")
        assert "Test Skill" in result

    def test_load_missing_skill(self):
        assert load_skill("nonexistent/SKILL.md") is None


class TestSources:
    def test_list_empty(self):
        assert list_source_files() == []

    def test_save_and_list(self):
        save_source("article.txt", "Some article content")
        files = list_source_files()
        assert "article.txt" in files

    def test_list_only_txt(self):
        save_source("article.txt", "text content")
        save_source("notes.txt", "more content")
        # Create a non-txt file
        from agent.memory import SOURCES_DIR
        os.makedirs(SOURCES_DIR, exist_ok=True)
        with open(os.path.join(SOURCES_DIR, "readme.md"), "w") as f:
            f.write("not a source")
        files = list_source_files()
        assert len(files) == 2
        assert all(f.endswith(".txt") for f in files)

    def test_read_source(self):
        save_source("test.txt", "Hello source content")
        content = read_source("test.txt")
        assert content == "Hello source content"

    def test_read_missing_source(self):
        assert read_source("nope.txt") is None

    def test_read_truncates_long_source(self):
        long_text = " ".join(f"word{i}" for i in range(3000))
        save_source("long.txt", long_text)
        content = read_source("long.txt")
        assert "truncated" in content
        assert len(content.split()) < 2100
