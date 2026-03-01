"""Tests for agent/tools.py — tool schemas and execution."""

import json
import os
import pytest

from agent.tools import get_available_tools, execute_tool, TOOLS
from db.models import init_database


class FakeAgent:
    """Minimal agent stand-in for tool execution tests."""

    def __init__(self, conn):
        self.db = conn
        self.target_language = "es"
        self.audio_output = None


@pytest.fixture
def conn(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr("db.models.DB_PATH", db_path)
    connection = init_database()
    yield connection
    connection.close()


@pytest.fixture
def agent(conn):
    return FakeAgent(conn)


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.memory.BASE_DIR", str(tmp_path))
    monkeypatch.setattr("agent.memory.MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setattr("agent.memory.SOURCES_DIR", str(tmp_path / "sources"))
    monkeypatch.setattr("agent.memory.SKILLS_DIR", str(tmp_path / "skills"))
    return tmp_path


class TestToolSchemas:
    def test_all_tools_have_required_fields(self):
        for tool in TOOLS:
            assert tool["type"] == "function"
            func = tool["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func

    def test_tool_names_unique(self):
        names = [t["function"]["name"] for t in TOOLS]
        assert len(names) == len(set(names))

    def test_elevenlabs_tool_excluded_by_default(self):
        os.environ.pop("ELEVENLABS_API_KEY", None)
        tools = get_available_tools()
        names = [t["function"]["name"] for t in tools]
        assert "speak_text" not in names

    def test_elevenlabs_tool_included_when_configured(self):
        os.environ["ELEVENLABS_API_KEY"] = "test-key"
        tools = get_available_tools()
        names = [t["function"]["name"] for t in tools]
        assert "speak_text" in names
        os.environ.pop("ELEVENLABS_API_KEY")


class TestExecuteTool:
    def test_add_and_get_reviews(self, agent):
        # Add a vocab item
        result = execute_tool("add_review_item", json.dumps({
            "item_type": "vocab",
            "word": "perro",
            "translation": "dog",
            "context": "El perro es grande.",
            "category": "animals",
        }), agent)
        assert "perro" in result
        assert "id=" in result

        # Get due reviews
        result = execute_tool("get_due_reviews", json.dumps({"limit": 5}), agent)
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["word"] == "perro"

    def test_log_review(self, agent):
        execute_tool("add_review_item", json.dumps({
            "item_type": "vocab", "word": "gato", "translation": "cat",
            "context": "El gato duerme.", "category": "animals",
        }), agent)
        result = execute_tool("log_review", json.dumps({
            "item_id": 1, "rating": 3,
        }), agent)
        assert "Review logged" in result

    def test_log_review_invalid(self, agent):
        result = execute_tool("log_review", json.dumps({
            "item_id": 999, "rating": 3,
        }), agent)
        assert "Error" in result

    def test_no_due_reviews(self, agent):
        result = execute_tool("get_due_reviews", json.dumps({}), agent)
        assert "No items due" in result

    def test_update_student_profile(self, agent):
        result = execute_tool("update_student_profile", json.dumps({
            "updates": "- Level: A2\n- Interests: cooking",
        }), agent)
        assert "profile updated" in result.lower() or "Profile" in result

    def test_read_skill_missing(self, agent):
        result = execute_tool("read_skill", json.dumps({
            "skill_path": "nonexistent/SKILL.md",
        }), agent)
        assert "not found" in result.lower()

    def test_read_skill_existing(self, agent, isolated_dirs):
        skill_dir = isolated_dirs / "skills" / "test"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Test Skill")
        result = execute_tool("read_skill", json.dumps({
            "skill_path": "test/SKILL.md",
        }), agent)
        assert "Test Skill" in result

    def test_list_sources_empty(self, agent):
        result = execute_tool("list_sources", json.dumps({}), agent)
        assert "No source" in result

    def test_read_source_missing(self, agent):
        result = execute_tool("read_source", json.dumps({
            "filename": "nope.txt",
        }), agent)
        assert "not found" in result.lower()

    def test_unknown_tool(self, agent):
        result = execute_tool("nonexistent_tool", json.dumps({}), agent)
        assert "Unknown tool" in result

    def test_add_grammar_item(self, agent):
        result = execute_tool("add_review_item", json.dumps({
            "item_type": "grammar",
            "pattern_name": "preterite -ar",
            "pattern_description": "Past tense for -ar verbs",
            "context": "Yo hablé con ella ayer.",
            "category": "verb-conjugation",
        }), agent)
        assert "preterite -ar" in result

    def test_uses_agent_target_language(self, agent):
        agent.target_language = "fr"
        execute_tool("add_review_item", json.dumps({
            "item_type": "vocab",
            "word": "bonjour",
            "translation": "hello",
            "context": "Bonjour, comment allez-vous?",
        }), agent)
        # Verify it was stored with French language code
        result = execute_tool("get_due_reviews", json.dumps({}), agent)
        data = json.loads(result)
        assert data[0]["language"] == "fr"
