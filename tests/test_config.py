import config


def test_first_existing_returns_first_present(tmp_path):
    present = tmp_path / "es.exe"
    present.write_bytes(b"")
    assert config.first_existing([str(tmp_path / "absent.exe"), str(present)]) == str(present)


def test_first_existing_falls_back_to_first(tmp_path):
    first = str(tmp_path / "a.exe")
    assert config.first_existing([first, str(tmp_path / "b.exe")]) == first


def test_env_int(monkeypatch):
    monkeypatch.setenv("EVERYTHING_TEST_INT", "12")
    assert config.env_int("EVERYTHING_TEST_INT", 3) == 12
    monkeypatch.setenv("EVERYTHING_TEST_INT", "abc")
    assert config.env_int("EVERYTHING_TEST_INT", 3) == 3
    monkeypatch.delenv("EVERYTHING_TEST_INT")
    assert config.env_int("EVERYTHING_TEST_INT", 3) == 3


def test_defaults():
    assert config.COPY_MAX_FILES == 500
    assert config.COPY_MAX_BYTES == 2 * 1024**3
    assert config.CONTENT_TIMEOUT == 300
    assert config.FOLDER_MAX_ITEMS == 500_000
