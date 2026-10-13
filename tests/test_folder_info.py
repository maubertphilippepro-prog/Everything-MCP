import pytest

import folder_info
from everything_backend import Entry


def build(root):
    return [
        Entry(root + r"\A", 0, None, 16, True),
        Entry(root + r"\A\B", 0, None, 16, True),
        Entry(root + r"\A\f1.xls", 100, "2024-01-01T00:00:00", 32, False),
        Entry(root + r"\A\B\f2.XLS", 50, "2025-06-01T00:00:00", 32, False),
        Entry(root + r"\f3.pdf", 10, "2023-01-01T00:00:00", 32, False),
        Entry(root + r"\README", 1, None, 32, False),
        Entry(r"D:\ailleurs\x.txt", 999, None, 32, False),  # hors du dossier : ignoré
    ]


def fake_search(entries, calls):
    def search(query, max_results, **kwargs):
        calls.append((query, max_results))
        return entries[:max_results]
    return search


def test_aggregates_depth_1(tmp_path):
    root = str(tmp_path)
    calls = []
    out = folder_info.folder_info(root, search=fake_search(build(root), calls))
    assert calls[0][0] == f'"{root}\\"'
    assert (out["files"], out["folders"], out["size"]) == (4, 2, 161)
    assert out["latest_modified"] == "2025-06-01T00:00:00"
    assert out["truncated"] is False
    assert out["subfolders"] == [{"path": root + r"\A", "relative": "A", "files": 2, "folders": 1, "size": 150}]
    by_ext = {d["extension"]: d for d in out["by_extension"]}
    assert by_ext[".xls"] == {"extension": ".xls", "files": 2, "size": 150}
    assert by_ext["(sans extension)"]["files"] == 1
    assert out["by_extension"][0]["extension"] == ".xls"


def test_depth_2_lists_nested_folders(tmp_path):
    root = str(tmp_path)
    out = folder_info.folder_info(root, depth=2, search=fake_search(build(root), []))
    nested = {s["relative"]: s for s in out["subfolders"]}
    assert nested["A\\B"] == {"path": root + r"\A\B", "relative": "A\\B", "files": 1, "folders": 0, "size": 50}


def test_truncated(tmp_path):
    root = str(tmp_path)
    out = folder_info.folder_info(root, search=fake_search(build(root), []), max_items=2)
    assert out["truncated"] is True


def test_invalid_path(tmp_path):
    with pytest.raises(ValueError):
        folder_info.folder_info(str(tmp_path / "absent"), search=fake_search([], []))
    with pytest.raises(ValueError):
        folder_info.folder_info("relatif", search=fake_search([], []))
