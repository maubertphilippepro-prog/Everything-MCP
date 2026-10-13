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
