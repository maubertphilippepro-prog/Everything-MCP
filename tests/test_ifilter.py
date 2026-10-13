import sys

import pytest

import ifilter


def test_has_filter_unknown_extension():
    assert not ifilter.has_filter(".zzzinconnu")
    assert not ifilter.has_filter("")


@pytest.mark.skipif(not ifilter.has_filter(".rtf"), reason="pas d'IFilter .rtf sur ce poste")
def test_rtf_via_ifilter(tmp_path):
    p = tmp_path / "a.rtf"
    p.write_bytes(b"{\\rtf1\\ansi Bonjour IFilter XYZ\\par}")
    assert "Bonjour IFilter XYZ" in ifilter.extract_text(str(p), timeout=60)


def test_timeout_kills_child(monkeypatch):
    monkeypatch.setattr(ifilter, "child_command",
                        lambda path: [sys.executable, "-c", "import time; time.sleep(30)"])
    with pytest.raises(ifilter.IFilterError, match="délai"):
        ifilter.extract_text("x", timeout=1)


def test_child_error_is_reported(monkeypatch):
    monkeypatch.setattr(ifilter, "child_command",
                        lambda path: [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(2)"])
    with pytest.raises(ifilter.IFilterError, match="boom"):
        ifilter.extract_text("x", timeout=30)
