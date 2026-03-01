"""Tests for the self-extending custom tools system."""

import json
import os
import pytest
from pathlib import Path

import custom_tools
from agent.tools import execute_tool
from db.models import init_database


class FakeAgent:
    """Minimal agent stand-in for tool execution tests."""

    def __init__(self, conn=None):
        self.db = conn
        self.target_language = "es"
        self.audio_output = None
        self._pending_tool_proposal = None


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


@pytest.fixture
def tools_dir(tmp_path, monkeypatch):
    """Point custom_tools at a temp directory."""
    d = tmp_path / "custom_tools"
    d.mkdir()
    monkeypatch.setattr(custom_tools, "_CUSTOM_TOOLS_DIR", d)
    monkeypatch.setattr(custom_tools, "_CREDENTIALS_PATH", d / "_credentials.json")
    custom_tools._registry.clear()
    return d


def _make_tool(tools_dir: Path, name: str, *, code: str | None = None, manifest: dict | None = None, creds: list[str] | None = None):
    """Helper: create a minimal custom tool directory."""
    tool_dir = tools_dir / name
    tool_dir.mkdir()

    if manifest is None:
        manifest = {
            "type": "function",
            "function": {
                "name": name,
                "description": f"Test tool {name}",
                "parameters": {"type": "object", "properties": {}},
            },
            "credentials_needed": creds or [],
        }
    (tool_dir / "manifest.json").write_text(json.dumps(manifest))

    if code is None:
        code = 'def execute(args, agent) -> str:\n    return "ok"\n'
    (tool_dir / "tool.py").write_text(code)

    return tool_dir


# ---------------------------------------------------------------------------
# TestCustomToolLoader
# ---------------------------------------------------------------------------


class TestCustomToolLoader:
    def test_discovers_valid_tools(self, tools_dir):
        _make_tool(tools_dir, "greet")
        _make_tool(tools_dir, "farewell")

        loaded = custom_tools.load_all()
        assert loaded == 2
        assert "greet" in custom_tools.get_custom_tool_names()
        assert "farewell" in custom_tools.get_custom_tool_names()

    def test_skips_missing_credentials(self, tools_dir):
        _make_tool(tools_dir, "needs_key", creds=["SOME_API_KEY"])

        loaded = custom_tools.load_all()
        assert loaded == 0
        assert "needs_key" not in custom_tools.get_custom_tool_names()

    def test_loads_tool_when_credentials_present(self, tools_dir):
        _make_tool(tools_dir, "needs_key", creds=["MY_KEY"])
        custom_tools.save_credential("MY_KEY", "secret123")

        loaded = custom_tools.load_all()
        assert loaded == 1

    def test_skips_malformed_directory_no_manifest(self, tools_dir):
        bad = tools_dir / "broken"
        bad.mkdir()
        (bad / "tool.py").write_text("def execute(args, agent): return 'hi'")
        # No manifest.json

        loaded = custom_tools.load_all()
        assert loaded == 0

    def test_skips_malformed_directory_no_tool_py(self, tools_dir):
        bad = tools_dir / "broken2"
        bad.mkdir()
        (bad / "manifest.json").write_text(json.dumps({
            "type": "function",
            "function": {"name": "broken2", "description": "test", "parameters": {}},
        }))
        # No tool.py

        loaded = custom_tools.load_all()
        assert loaded == 0

    def test_skips_invalid_json_manifest(self, tools_dir):
        bad = tools_dir / "badjson"
        bad.mkdir()
        (bad / "manifest.json").write_text("not json{{{")
        (bad / "tool.py").write_text("def execute(args, agent): return 'hi'")

        loaded = custom_tools.load_all()
        assert loaded == 0

    def test_skips_underscore_dirs(self, tools_dir):
        _make_tool(tools_dir, "_private")

        loaded = custom_tools.load_all()
        assert loaded == 0

    def test_schemas_match_loaded_tools(self, tools_dir):
        _make_tool(tools_dir, "hello")
        custom_tools.load_all()

        schemas = custom_tools.get_custom_schemas()
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "hello"


# ---------------------------------------------------------------------------
# TestCustomToolExecution
# ---------------------------------------------------------------------------


class TestCustomToolExecution:
    def test_dispatches_to_loaded_executor(self, tools_dir, agent):
        _make_tool(
            tools_dir, "echo_tool",
            code='def execute(args, agent) -> str:\n    return f"echo: {args.get(\'msg\', \'?\')}"\n',
        )
        custom_tools.load_all()

        result = custom_tools.execute_custom_tool("echo_tool", {"msg": "hi"}, agent)
        assert result == "echo: hi"

    def test_returns_none_for_unknown(self, tools_dir, agent):
        custom_tools.load_all()
        result = custom_tools.execute_custom_tool("no_such_tool", {}, agent)
        assert result is None

    def test_handles_execution_error(self, tools_dir, agent):
        _make_tool(
            tools_dir, "bad_tool",
            code='def execute(args, agent) -> str:\n    raise ValueError("boom")\n',
        )
        custom_tools.load_all()

        result = custom_tools.execute_custom_tool("bad_tool", {}, agent)
        assert "Error" in result
        assert "boom" in result


# ---------------------------------------------------------------------------
# TestCredentials
# ---------------------------------------------------------------------------


class TestCredentials:
    def test_save_and_load_round_trip(self, tools_dir):
        custom_tools.save_credential("TEST_KEY", "test_value")
        assert custom_tools.get_credential("TEST_KEY") == "test_value"

    def test_file_created_on_disk(self, tools_dir):
        custom_tools.save_credential("K", "V")
        cred_file = tools_dir / "_credentials.json"
        assert cred_file.exists()
        data = json.loads(cred_file.read_text())
        assert data["K"] == "V"

    def test_missing_credential_returns_none(self, tools_dir):
        assert custom_tools.get_credential("NONEXISTENT") is None

    def test_multiple_credentials(self, tools_dir):
        custom_tools.save_credential("A", "1")
        custom_tools.save_credential("B", "2")
        assert custom_tools.get_credential("A") == "1"
        assert custom_tools.get_credential("B") == "2"


# ---------------------------------------------------------------------------
# TestSaveAndRegister
# ---------------------------------------------------------------------------


class TestSaveAndRegister:
    def test_saves_files_and_hot_loads(self, tools_dir):
        proposal = {
            "name": "my_tool",
            "description": "A test tool",
            "parameters_schema": {"type": "object", "properties": {"x": {"type": "string"}}},
            "credentials_needed": [],
        }
        code = 'def execute(args, agent) -> str:\n    return "hello"\n'

        result = custom_tools._save_and_register_tool(proposal, code)
        assert "saved and loaded" in result

        # Files exist
        assert (tools_dir / "my_tool" / "manifest.json").exists()
        assert (tools_dir / "my_tool" / "tool.py").exists()

        # Tool is available
        assert "my_tool" in custom_tools.get_custom_tool_names()

    def test_rejects_code_without_execute(self, tools_dir):
        proposal = {"name": "bad", "description": "bad", "parameters_schema": {}}
        code = "def helper():\n    pass\n"

        result = custom_tools._save_and_register_tool(proposal, code)
        assert "rejected" in result.lower()
        assert "bad" not in custom_tools.get_custom_tool_names()

    def test_rejects_dangerous_os_system(self, tools_dir):
        proposal = {"name": "evil", "description": "evil", "parameters_schema": {}}
        code = 'import os\ndef execute(args, agent) -> str:\n    os.system("rm -rf /")\n    return "done"\n'

        result = custom_tools._save_and_register_tool(proposal, code)
        assert "rejected" in result.lower() or "Blocked" in result

    def test_rejects_dangerous_subprocess(self, tools_dir):
        proposal = {"name": "evil2", "description": "evil", "parameters_schema": {}}
        code = 'import subprocess\ndef execute(args, agent) -> str:\n    subprocess.run(["ls"])\n    return "done"\n'

        result = custom_tools._save_and_register_tool(proposal, code)
        assert "rejected" in result.lower() or "Blocked" in result

    def test_rejects_dangerous_eval(self, tools_dir):
        proposal = {"name": "evil3", "description": "evil", "parameters_schema": {}}
        code = 'def execute(args, agent) -> str:\n    return eval("1+1")\n'

        result = custom_tools._save_and_register_tool(proposal, code)
        assert "rejected" in result.lower() or "Blocked" in result

    def test_rejects_dangerous_exec(self, tools_dir):
        proposal = {"name": "evil4", "description": "evil", "parameters_schema": {}}
        code = 'def execute(args, agent) -> str:\n    exec("x=1")\n    return "done"\n'

        result = custom_tools._save_and_register_tool(proposal, code)
        assert "rejected" in result.lower() or "Blocked" in result

    def test_rejects_dangerous_dunder_import(self, tools_dir):
        proposal = {"name": "evil5", "description": "evil", "parameters_schema": {}}
        code = 'def execute(args, agent) -> str:\n    m = __import__("os")\n    return "done"\n'

        result = custom_tools._save_and_register_tool(proposal, code)
        assert "rejected" in result.lower() or "Blocked" in result


# ---------------------------------------------------------------------------
# TestMetaToolIntegration
# ---------------------------------------------------------------------------


class TestMetaToolIntegration:
    @pytest.fixture(autouse=True)
    def _isolated_tools(self, tools_dir):
        """Ensure custom_tools points at tmp dir for all integration tests."""
        pass

    def test_propose_stores_on_agent(self, agent):
        result = execute_tool("propose_tool", json.dumps({
            "name": "fetch_news",
            "description": "Fetch news articles",
            "parameters_schema": {
                "type": "object",
                "properties": {"topic": {"type": "string"}},
            },
            "credentials_needed": ["NEWS_API_KEY"],
        }), agent)

        assert "fetch_news" in result
        assert "[Ask the student to confirm]" in result
        assert agent._pending_tool_proposal is not None
        assert agent._pending_tool_proposal["name"] == "fetch_news"

    def test_save_requires_proposal(self, agent):
        agent._pending_tool_proposal = None
        result = execute_tool("save_tool", json.dumps({
            "name": "anything",
            "code": "def execute(args, agent): return 'hi'",
        }), agent)
        assert "No pending" in result

    def test_save_requires_name_match(self, agent):
        agent._pending_tool_proposal = {
            "name": "tool_a",
            "description": "A",
            "parameters_schema": {},
            "credentials_needed": [],
        }
        result = execute_tool("save_tool", json.dumps({
            "name": "tool_b",
            "code": "def execute(args, agent): return 'hi'",
        }), agent)
        assert "mismatch" in result.lower()

    def test_full_propose_save_flow(self, agent):
        # Step 1: propose
        execute_tool("propose_tool", json.dumps({
            "name": "greeter",
            "description": "Greet in any language",
            "parameters_schema": {
                "type": "object",
                "properties": {"lang": {"type": "string"}},
            },
        }), agent)

        assert agent._pending_tool_proposal is not None

        # Step 2: save
        code = 'def execute(args, agent) -> str:\n    return f"Hello in {args.get(\'lang\', \'en\')}!"\n'
        result = execute_tool("save_tool", json.dumps({
            "name": "greeter",
            "code": code,
        }), agent)

        assert "saved and loaded" in result
        assert agent._pending_tool_proposal is None
        assert "greeter" in custom_tools.get_custom_tool_names()

    def test_store_credential(self, agent):
        result = execute_tool("store_credential", json.dumps({
            "key_name": "MY_API_KEY",
            "key_value": "super-secret",
        }), agent)
        assert "saved" in result.lower()
        assert custom_tools.get_credential("MY_API_KEY") == "super-secret"

    def test_custom_tool_dispatch_via_execute_tool(self, agent, tools_dir):
        """Custom tools are reachable through the main execute_tool dispatcher."""
        _make_tool(
            tools_dir, "ping",
            code='def execute(args, agent) -> str:\n    return "pong"\n',
        )
        custom_tools.load_all()

        result = execute_tool("ping", json.dumps({}), agent)
        assert result == "pong"
