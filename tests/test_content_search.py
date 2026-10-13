import pytest

import content_search
from everything_backend import Entry
from extractors import MatchResult


def E(path, attributes=32):
    return Entry(path, 10, "2024-01-01T00:00:00", attributes, False)


def fake_search(entries, calls):
    def search(query, max_results, **kwargs):
        calls.append((query, max_results, kwargs))
        return entries[:max_results]
    return search


def never_called(*args, **kwargs):
    pytest.fail("aucune lecture de fichier attendue")


def test_classifies_results():
    entries = [E(r"C:\a.xls"), E(r"C:\b.xls"), E(r"C:\c.xls")]
    results = {
        r"C:\a.xls": MatchResult(True, "native"),
        r"C:\b.xls": MatchResult(False, "native"),
        r"C:\c.xls": MatchResult(None, None, "protégé par mot de passe"),
    }
    calls = []
    out = content_search.find_content(
        "ext:xls", "XYZ", search=fake_search(entries, calls),
        match=lambda path, phrase, **kw: results[path],
    )
    assert out["query"] == "ext:xls file:"
    assert out["candidates"] == 3
    assert out["matches"] == [{"path": r"C:\a.xls", "size": 10, "modified": "2024-01-01T00:00:00", "method": "native"}]
    assert out["not_matching"] == 1
    assert out["unverified"] == [{"path": r"C:\c.xls", "reason": "protégé par mot de passe"}]
    assert calls[0][1] == 2001


def test_too_many_candidates():
    entries = [E(f"C:\\{i}.txt") for i in range(4)]
    with pytest.raises(content_search.TooManyCandidates, match="restreindre"):
        content_search.find_content("ext:txt", "x", max_candidates=3,
                                    search=fake_search(entries, []), match=never_called)


def test_cloud_only_files_skipped_without_reading():
    out = content_search.find_content("ext:pdf", "x", search=fake_search([E(r"C:\od.pdf", 0x500020)], []),
                                      match=never_called)
    assert out["unverified"][0]["reason"].startswith("en ligne uniquement")


def test_cloud_only_files_included_on_request():
    out = content_search.find_content("ext:pdf", "x", include_cloud=True,
                                      search=fake_search([E(r"C:\od.pdf", 0x500020)], []),
                                      match=lambda path, phrase, **kw: MatchResult(True, "native"))
    assert len(out["matches"]) == 1


def test_timeout_marks_remaining_files():
    ticks = iter([0, 0, 10])
    entries = [E(r"C:\1.txt"), E(r"C:\2.txt"), E(r"C:\3.txt")]
    out = content_search.find_content("ext:txt", "x", timeout=5, clock=lambda: next(ticks),
                                      search=fake_search(entries, []),
                                      match=lambda path, phrase, **kw: MatchResult(False, "native"))
    assert out["not_matching"] == 1
    assert [u["reason"] for u in out["unverified"]] == ["délai dépassé", "délai dépassé"]


def test_unexpected_reader_error_is_unverified():
    def boom(path, phrase, **kw):
        raise RuntimeError("boum")
    out = content_search.find_content("ext:txt", "x", search=fake_search([E(r"C:\1.txt")], []), match=boom)
    assert "boum" in out["unverified"][0]["reason"]


def test_empty_phrase_refused():
    with pytest.raises(ValueError):
        content_search.find_content("ext:txt", "", search=fake_search([], []), match=never_called)


def test_is_cloud_only_reads_stat_when_attributes_missing(tmp_path):
    p = tmp_path / "local.txt"
    p.write_text("x")
    assert content_search.is_cloud_only(Entry(str(p), 1, None, None, False)) is False
