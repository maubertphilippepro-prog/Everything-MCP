"""Le serveur ne doit contenir aucune opération destructrice : ni suppression, ni déplacement,
ni renommage, ni écrasement. Ce test analyse le code source de chaque module serveur."""

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER_MODULES = sorted(ROOT.glob("*.py"))

FORBIDDEN_ATTRS = {
    "os": {"remove", "unlink", "rmdir", "removedirs", "rename", "renames", "replace", "truncate", "open"},
    "shutil": {"move", "rmtree", "copytree", "copy", "copy2", "copyfile"},
}
FORBIDDEN_MODULES = {"pathlib", "send2trash"}


def _open_mode(call):
    if len(call.args) > 1:
        return call.args[1]
    return next((k.value for k in call.keywords if k.arg == "mode"), None)


def violations(source):
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.attr in FORBIDDEN_ATTRS.get(node.value.id, ()):
                found.append(f"{node.value.id}.{node.attr} (ligne {node.lineno})")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in FORBIDDEN_MODULES:
                found.append(f"import {node.module} (ligne {node.lineno})")
            for alias in node.names:
                if alias.name in FORBIDDEN_ATTRS.get(node.module, ()):
                    found.append(f"from {node.module} import {alias.name} (ligne {node.lineno})")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_MODULES:
                    found.append(f"import {alias.name} (ligne {node.lineno})")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            mode = _open_mode(node)
            if mode is None:
                continue
            if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
                found.append(f"open() avec un mode non littéral (ligne {node.lineno})")
            elif "w" in mode.value or "+" in mode.value:
                found.append(f"open(..., {mode.value!r}) (ligne {node.lineno})")
    return found


def test_all_server_modules_are_checked():
    names = {p.name for p in SERVER_MODULES}
    assert {"server.py", "copier.py", "extractors.py", "ifilter.py", "content_search.py",
            "folder_info.py", "everything_backend.py", "config.py"} <= names


@pytest.mark.parametrize("module", SERVER_MODULES, ids=lambda p: p.name)
def test_no_destructive_operation(module):
    assert violations(module.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("snippet", [
    "import os\nos.remove('x')",
    "import os\nos.replace('a', 'b')",
    "import shutil\nshutil.copy2('a', 'b')",
    "import shutil\nshutil.move('a', 'b')",
    "from os import rename",
    "import pathlib",
    "open('f', 'w')",
    "open('f', mode='r+b')",
])
def test_checker_detects(snippet):
    assert violations(snippet)


def test_checker_allows_safe_calls():
    assert violations("open('f', 'xb')\nopen('m', 'a')\nopen('s', 'rb')\nimport shutil\nshutil.copyfileobj(a, b)") == []
