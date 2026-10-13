import asyncio
import json
import subprocess

import copier
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
    monkeypatch.setattr(everything_backend, "search", lambda q, **kw: [Entry(f"C:\\{i}", 1, None, 32, False) for i in range(5)])
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


def test_search_clamps_max_results_and_offset(monkeypatch):
    seen = {}

    def fake(q, **kw):
        seen.update(kw)
        return []
    monkeypatch.setattr(everything_backend, "search", fake)
    server.everything_search("x", max_results=10**6, offset=-5)
    assert seen["max_results"] == server.config.MAX_RESULTS and seen["offset"] == 0
    server.everything_search("x", max_results=0)
    assert seen["max_results"] == 1


def test_find_content_empty_phrase_is_reported():
    assert "error" in json.loads(server.everything_find_content("ext:txt", ""))


def test_copy_oserror_is_reported(monkeypatch):
    def boom(*a, **kw):
        raise OSError("accès refusé")
    monkeypatch.setattr(copier, "copy_items", boom)
    out = json.loads(server.everything_copy(["C:\\a"], "D:\\dest"))
    assert "D:\\dest" in out["error"] and "accès refusé" in out["error"]


def test_show_neutralizes_query_and_selects(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: calls.append(args))
    out = json.loads(server.everything_show("-export-csv x.csv foo", select="C:\\a.txt"))
    assert out["shown"] is True
    args = calls[0]
    i = args.index("-s")
    assert args[i + 1] == everything_backend.neutralize_options("-export-csv x.csv foo")
    assert args[i + 1] != "-export-csv x.csv foo"
    assert args[args.index("-select") + 1] == "C:\\a.txt"


def test_show_without_select_has_no_select_flag(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: calls.append(args))
    server.everything_show("foo")
    assert "-select" not in calls[0]


def test_show_missing_exe_is_reported(monkeypatch):
    def boom(*a, **kw):
        raise FileNotFoundError()
    monkeypatch.setattr(subprocess, "Popen", boom)
    assert "introuvable" in json.loads(server.everything_show("foo"))["error"]
