"""Self-extending tool system — loader, registry, and credential store.

Custom tools live in subdirectories of this package:

    custom_tools/
      fetch_news/
        manifest.json   (Mistral function schema + metadata)
        tool.py         (def execute(args, agent) -> str)
"""

import importlib.util
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

_CUSTOM_TOOLS_DIR = Path(__file__).parent

# In-memory registry: name -> {"schema": {...}, "execute": <callable>}
_registry: dict[str, dict] = {}

# Patterns that are blocked in user-supplied tool code
_DANGEROUS_PATTERNS = [
    "os.system",
    "subprocess",
    "eval(",
    "exec(",
    "__import__",
    "shutil.rmtree",
    "os.remove",
]

# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

_CREDENTIALS_PATH = _CUSTOM_TOOLS_DIR / "_credentials.json"


def get_credential(key: str) -> str | None:
    """Read a credential by key from the local credential store."""
    if not _CREDENTIALS_PATH.exists():
        return None
    try:
        data = json.loads(_CREDENTIALS_PATH.read_text())
        return data.get(key)
    except (json.JSONDecodeError, OSError):
        return None


def save_credential(key: str, value: str) -> None:
    """Write a credential to the local credential store."""
    data: dict = {}
    if _CREDENTIALS_PATH.exists():
        try:
            data = json.loads(_CREDENTIALS_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    data[key] = value
    _CREDENTIALS_PATH.write_text(json.dumps(data, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _load_tool(tool_dir: Path) -> bool:
    """Load a single custom tool from its directory. Returns True on success."""
    manifest_path = tool_dir / "manifest.json"
    tool_py_path = tool_dir / "tool.py"

    if not manifest_path.exists() or not tool_py_path.exists():
        return False

    try:
        manifest = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False

    # Validate manifest has the expected structure
    func_def = manifest.get("function")
    if not func_def or "name" not in func_def:
        return False

    # Check credentials
    creds_needed = manifest.get("credentials_needed", [])
    for cred_key in creds_needed:
        if get_credential(cred_key) is None:
            return False

    # Dynamically import tool.py
    name = func_def["name"]
    spec = importlib.util.spec_from_file_location(f"custom_tools.{name}", tool_py_path)
    if spec is None or spec.loader is None:
        return False
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return False

    if not hasattr(module, "execute"):
        return False

    schema = {"type": "function", "function": func_def}

    _registry[name] = {
        "schema": schema,
        "execute": module.execute,
    }
    return True


def load_all() -> int:
    """Scan subdirectories and load all valid custom tools. Returns count loaded."""
    _registry.clear()
    loaded = 0
    if not _CUSTOM_TOOLS_DIR.is_dir():
        return 0
    for entry in sorted(_CUSTOM_TOOLS_DIR.iterdir()):
        if entry.is_dir() and not entry.name.startswith("_"):
            if _load_tool(entry):
                loaded += 1
    return loaded


# ---------------------------------------------------------------------------
# Registry queries
# ---------------------------------------------------------------------------


def get_custom_schemas() -> list[dict]:
    """Return Mistral-format tool schemas for all loaded custom tools."""
    return [entry["schema"] for entry in _registry.values()]


def get_custom_tool_names() -> list[str]:
    """Return names of all loaded custom tools."""
    return list(_registry.keys())


def get_custom_tool_info() -> list[dict]:
    """Return name + description for each loaded custom tool."""
    result = []
    for name, entry in _registry.items():
        desc = entry["schema"]["function"].get("description", "")
        result.append({"name": name, "description": desc})
    return result


def execute_custom_tool(name: str, args: dict, agent) -> str | None:
    """Dispatch to a loaded custom tool. Returns None if tool not found."""
    entry = _registry.get(name)
    if entry is None:
        return None
    try:
        return entry["execute"](args, agent)
    except Exception as e:
        return f"Error in custom tool {name}: {e}"


# ---------------------------------------------------------------------------
# Save & register (hot-load)
# ---------------------------------------------------------------------------


def _validate_code(code: str) -> str | None:
    """Validate tool code. Returns error message or None if safe."""
    if "def execute(" not in code:
        return "Tool code must contain a `def execute(` function."

    for pattern in _DANGEROUS_PATTERNS:
        if pattern in code:
            return f"Blocked: tool code contains dangerous pattern `{pattern}`."

    return None


def _save_and_register_tool(proposal: dict, code: str) -> str:
    """Write manifest + tool.py to disk and hot-load. Returns status message."""
    # Validate code safety
    error = _validate_code(code)
    if error:
        return f"Tool rejected: {error}"

    name = proposal["name"]
    tool_dir = _CUSTOM_TOOLS_DIR / name

    # Build manifest
    manifest = {
        "type": "function",
        "function": {
            "name": name,
            "description": proposal["description"],
            "parameters": proposal.get("parameters_schema", {"type": "object", "properties": {}}),
        },
        "credentials_needed": proposal.get("credentials_needed", []),
        "created": datetime.now(timezone.utc).isoformat(),
    }

    # Write files
    tool_dir.mkdir(parents=True, exist_ok=True)
    (tool_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (tool_dir / "tool.py").write_text(code)

    # Hot-load
    if _load_tool(tool_dir):
        return f"Tool `{name}` saved and loaded successfully."
    else:
        return f"Tool `{name}` saved but failed to load — check credentials or code."
