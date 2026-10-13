import asyncio
import json

import everything_backend
import server
from everything_backend import Entry

TOOLS = ["everything_copy", "everything_find_content", "everything_folder_info", "everything_search", "everything_show"]


def tool_names():
    return sorted(t.name for t in asyncio.run(server.mcp.list_tools()))


def test_tools_registered():
    assert tool_names() == TOOLS


def test_no_destructive_tool():
    for name in tool_names():
        assert not any(word in name for word in ("move", "delete", "remove", "rename", "write"))


def test_search_formats_results(monkeypatch):
    monkeypatch.setattr(everything_backend, "search",
                        lambda q, **kw: [Entry(r"C:\a.pdf", 3, "2025-01-01T00:00:00", 32, False)])
    out = json.loads(server.everything_search("ext:pdf"))
    assert out["results"] == [{"path": r"C:\a.pdf", "size": 3, "modified": "2025-01-01T00:00:00"}]
    assert out["returned"] == 1 and "note" not in out


def test_search_error_is_reported(monkeypatch):
    def boom(q, **kw):
        raise everything_backend.EverythingError("Everything n'est pas lancé")
    monkeypatch.setattr(everything_backend, "search", boom)
    assert "lancé" in json.loads(server.everything_search("x"))["error"]


def test_find_content_error_is_reported(monkeypatch):
    monkeypatch.setattr(everything_backend, "search", lambda q, **kw: [Entry(f"C:\{i}", 1, None, 32, False) for i in range(5)])
    out = json.loads(server.everything_find_content("ext:txt", "x", max_candidates=2))
    assert "restreindre" in out["error"]


def test_folder_info_error_is_reported(tmp_path):
    assert "introuvable" in json.loads(server.everything_folder_info(str(tmp_path / "absent")))["error"]


def test_copy_refusal_is_reported():
    assert "absolu" in json.loads(server.everything_copy([], "extract"))["error"]


def test_copy_end_to_end(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("x")
    out = json.loads(server.everything_copy([str(src)], str(tmp_path / "out")))
    assert out["copied_files"] == 1 and (tmp_path / "out" / "a.txt").exists()
