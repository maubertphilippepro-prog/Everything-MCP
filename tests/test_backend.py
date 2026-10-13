import json
import subprocess
import time
from datetime import datetime, timezone

import pytest

import config
import everything_backend as eb


@pytest.fixture(autouse=True)
def es_path(monkeypatch):
    monkeypatch.setattr(config, "ES_PATH", r"C:\Program Files (x86)\Everything\es.exe")
    monkeypatch.setattr(config, "INSTANCE", "")


def test_command_line_appends_raw_query():
    cmd = eb.es_command_line('ext:msg "C:\\A B\\" dm:>=2020-01-01', 10)
    assert cmd.startswith('"C:\\Program Files (x86)\\Everything\\es.exe" -csv -size -dm -attributes')
    assert "-n 10 -o 0 -sort date-modified -sort-descending" in cmd
    assert cmd.endswith(' ext:msg "C:\\A B\\" dm:>=2020-01-01')


def test_command_line_options():
    cmd = eb.es_command_line("x", 5, offset=20, sort="bogus", descending=False, match_path=True, regex=True)
    assert "-o 20 -sort date-modified -sort-ascending -p -r x" in cmd


def test_command_line_instance(monkeypatch):
    monkeypatch.setattr(config, "INSTANCE", "1.5a")
    assert "-instance 1.5a -csv" in eb.es_command_line("x", 5)


def test_option_like_terms_are_neutralized():
    assert eb.neutralize_options("-export-csv out.csv /n 5 ext:md") == "<-export-csv> out.csv </n> 5 ext:md"


def test_quoted_terms_and_newlines_preserved():
    assert eb.neutralize_options('ext:md\n"C:\\A -B\\"  !x') == 'ext:md "C:\\A -B\\" !x'


def test_parse_es_csv():
    text = (
        "Filename,Size,Date Modified,Attributes\r\n"
        '"C:\\Docs\\Plans\\",0,2026-10-13T17:42:28,16\r\n'
        '"C:\\Docs\\a.xls",37376,2007-10-05T18:31:06,5242912\r\n'
        '"C:\\",0,2026-01-01T00:00:00,22\r\n'
    )
    entries = eb.parse_es_csv(text)
    assert entries[0] == eb.Entry("C:\\Docs\\Plans", 0, "2026-10-13T17:42:28", 16, True)
    assert entries[1] == eb.Entry("C:\\Docs\\a.xls", 37376, "2007-10-05T18:31:06", 5242912, False)
    assert entries[2].path == "C:\\" and entries[2].is_dir


def test_parse_empty_output():
    assert eb.parse_es_csv("") == []


def test_entry_to_dict():
    assert eb.Entry("C:\\a", 1, None, 32, False).to_dict() == {"path": "C:\\a", "size": 1, "modified": None}
    assert eb.Entry("C:\\d", 0, None, 16, True).to_dict()["type"] == "folder"


def test_missing_es_raises(monkeypatch):
    monkeypatch.setattr(config, "BACKEND", "es")
    monkeypatch.setattr(config, "ES_PATH", r"C:\nulle-part\es.exe")
    with pytest.raises(eb.EverythingError, match="introuvable"):
        eb.search("x")


def _fake_run(returncode=0, stdout=b"", stderr=b"", csv_text=None):
    """Remplace subprocess.run ; écrit csv_text dans le fichier d'export demandé."""
    def run(cmd, **kwargs):
        if csv_text is not None:
            time.sleep(0.01)
            path = cmd.split("-export-csv ", 1)[1].split(" -utf8-bom", 1)[0].strip('"')
            with open(path, "wb") as f:
                f.write(b"\xef\xbb\xbf" + csv_text.encode("utf-8"))
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)
    return run


def test_command_line_export():
    cmd = eb.es_command_line("x", 5, export_path="C:\\T\\o.csv")
    assert "-export-csv C:\\T\\o.csv -utf8-bom -n 5" in cmd


def test_es_search_reads_utf8_export(monkeypatch):
    monkeypatch.setattr(config, "BACKEND", "es")
    csv_text = ('Filename,Size,Date Modified,Attributes\r\n'
                '"C:\\D\\Évaluation_œuvre_çà.txt",3,2026-10-13T18:57:29,32\r\n')
    monkeypatch.setattr(eb.subprocess, "run", _fake_run(csv_text=csv_text))
    entries = eb.search("x")
    assert entries[0].path == "C:\\D\\Évaluation_œuvre_çà.txt"


def test_es_nonzero_exit_reports_code_and_stderr(monkeypatch):
    monkeypatch.setattr(config, "BACKEND", "es")
    monkeypatch.setattr(eb.subprocess, "run", _fake_run(returncode=2, stderr=b"option inconnue"))
    with pytest.raises(eb.EverythingError, match=r"code 2.*option inconnue"):
        eb.search("x")


def test_es_code_8_hints_everything_not_running(monkeypatch):
    monkeypatch.setattr(config, "BACKEND", "es")
    monkeypatch.setattr(eb.subprocess, "run", _fake_run(returncode=8, stderr=b"IPC"))
    with pytest.raises(eb.EverythingError, match="Everything est-il lancé ?"):
        eb.search("x")


def test_es_timeout_raises(monkeypatch):
    monkeypatch.setattr(config, "BACKEND", "es")

    def run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 120)
    monkeypatch.setattr(eb.subprocess, "run", run)
    with pytest.raises(eb.EverythingError, match="dépassé"):
        eb.search("x")


class _FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(body):
    return lambda url, timeout=None: _FakeResponse(body)


def test_http_search_happy_path(monkeypatch):
    monkeypatch.setattr(config, "BACKEND", "http")
    monkeypatch.setattr(config, "HTTP_URL", "http://localhost:8080")
    body = json.dumps({"results": [
        {"type": "file", "name": "a.txt", "path": "C:\\Docs", "size": "12",
         "date_modified": "133000000000000000"},
        {"type": "folder", "name": "Plans", "path": "C:\\Docs", "size": "", "date_modified": None},
    ]}).encode("utf-8")
    monkeypatch.setattr(eb.urllib.request, "urlopen", _fake_urlopen(body))
    entries = eb.search("x")
    assert entries[0].path == "C:\\Docs\\a.txt" and entries[0].size == 12 and not entries[0].is_dir
    assert entries[0].modified == datetime.fromtimestamp(
        (133000000000000000 - 116444736000000000) / 10_000_000, tz=timezone.utc
    ).astimezone().isoformat(timespec="seconds")
    assert entries[1].path == "C:\\Docs\\Plans" and entries[1].is_dir and entries[1].size is None
    assert entries[1].modified is None


@pytest.mark.parametrize("body", [b"pas du json", b"\xff\xfe", b"[1, 2]"])
def test_http_invalid_response_raises(monkeypatch, body):
    monkeypatch.setattr(config, "BACKEND", "http")
    monkeypatch.setattr(config, "HTTP_URL", "http://localhost:8080")
    monkeypatch.setattr(eb.urllib.request, "urlopen", _fake_urlopen(body))
    with pytest.raises(eb.EverythingError, match="invalide"):
        eb.search("x")


HEADER = "Filename,Size\r\n"


def test_es_header_only_export_means_no_results(monkeypatch):
    monkeypatch.setattr(config, "BACKEND", "es")
    monkeypatch.setattr(eb.subprocess, "run", _fake_run(csv_text=HEADER))
    assert eb.search("x") == []


def test_es_unwritten_export_is_not_mistaken_for_results(monkeypatch):
    monkeypatch.setattr(config, "BACKEND", "es")
    monkeypatch.setattr(eb.subprocess, "run", _fake_run(csv_text=HEADER + '"C:\\a",1\r\n'))
    assert len(eb.search("x")) == 1
    monkeypatch.setattr(eb.subprocess, "run", _fake_run())  # code 0 mais rien d'écrit
    with pytest.raises(eb.EverythingError, match="export"):
        eb.search("x")
