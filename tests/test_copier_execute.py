import builtins
import csv
import os
import shutil

import pytest

import copier


def write(path, content=b"data"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_copy_file_keeps_content_and_date(tmp_path):
    src = write(tmp_path / "src" / "a.txt", b"hello")
    os.utime(src, (1_600_000_000, 1_600_000_000))
    out = copier.copy_items([str(src)], str(tmp_path / "out"))
    target = tmp_path / "out" / "a.txt"
    assert target.read_bytes() == b"hello"
    assert int(target.stat().st_mtime) == 1_600_000_000
    assert out["copied_files"] == 1 and out["copied"][0]["copy"] == str(target)
    assert src.read_bytes() == b"hello"


def test_collision_never_overwrites(tmp_path):
    existing = write(tmp_path / "out" / "a.txt", b"ANCIEN")
    os.utime(existing, (1_500_000_000, 1_500_000_000))
    s1 = write(tmp_path / "s1" / "a.txt", b"un")
    s2 = write(tmp_path / "s2" / "a.txt", b"deux")
    copier.copy_items([str(s1), str(s2)], str(tmp_path / "out"))
    assert existing.read_bytes() == b"ANCIEN"
    assert int(existing.stat().st_mtime) == 1_500_000_000
    assert (tmp_path / "out" / "a (2).txt").read_bytes() == b"un"
    assert (tmp_path / "out" / "a (3).txt").read_bytes() == b"deux"


def test_copy_folder_recursive_without_merging(tmp_path):
    src = tmp_path / "src" / "Dossier"
    write(src / "x.txt", b"x")
    write(src / "sous" / "y.txt", b"y")
    (src / "vide").mkdir()
    existing = write(tmp_path / "out" / "Dossier" / "x.txt", b"ANCIEN")
    out = copier.copy_items([str(src)], str(tmp_path / "out"))
    copy = tmp_path / "out" / "Dossier (2)"
    assert (copy / "x.txt").read_bytes() == b"x"
    assert (copy / "sous" / "y.txt").read_bytes() == b"y"
    assert (copy / "vide").is_dir()
    assert existing.read_bytes() == b"ANCIEN"
    assert sorted(os.listdir(tmp_path / "out" / "Dossier")) == ["x.txt"]
    assert out["copied_files"] == 2


def test_tree_mode_recreates_structure(tmp_path):
    root = tmp_path / "Chantiers"
    f1 = write(root / "A" / "f.xls", b"1")
    f2 = write(root / "B" / "C" / "f.xls", b"2")
    out = copier.copy_items([str(f1), str(f2)], str(tmp_path / "out"), preserve_tree_from=str(root))
    assert out["mode"] == "tree"
    assert (tmp_path / "out" / "A" / "f.xls").read_bytes() == b"1"
    assert (tmp_path / "out" / "B" / "C" / "f.xls").read_bytes() == b"2"


def test_limits_refuse_everything(tmp_path):
    a = write(tmp_path / "a.txt", b"12345")
    b = write(tmp_path / "b.txt", b"1")
    with pytest.raises(copier.CopyRefused, match="plafond"):
        copier.copy_items([str(a), str(b)], str(tmp_path / "out"), max_files=1)
    with pytest.raises(copier.CopyRefused, match="plafond"):
        copier.copy_items([str(a)], str(tmp_path / "out"), max_bytes=4)
    assert not (tmp_path / "out").exists()


def test_manifest_is_appended(tmp_path):
    dest = tmp_path / "out"
    a = write(tmp_path / "a.txt", b"abc")
    b = write(tmp_path / "b.txt", b"de")
    copier.copy_items([str(a)], str(dest))
    out = copier.copy_items([str(b)], str(dest))
    with open(out["manifest"], encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))
    assert rows[0] == copier.MANIFEST_HEADER
    assert [r[1] for r in rows[1:]] == [str(a), str(b)]
    assert rows[2][2] == str(dest / "b.txt") and rows[2][3] == "2"


def test_foreign_manifest_untouched(tmp_path):
    foreign = write(tmp_path / "out" / "manifest.csv", b"mes notes")
    out = copier.copy_items([str(write(tmp_path / "a.txt"))], str(tmp_path / "out"))
    assert foreign.read_bytes() == b"mes notes"
    assert out["manifest"] == str(tmp_path / "out" / "manifest (2).csv")


def test_source_named_manifest_does_not_collide(tmp_path):
    m = write(tmp_path / "src" / "manifest.csv", b"source")
    out = copier.copy_items([str(m)], str(tmp_path / "out"))
    assert out["manifest"] == str(tmp_path / "out" / "manifest.csv")
    assert (tmp_path / "out" / "manifest (2).csv").read_bytes() == b"source"


def test_unreadable_source_creates_nothing(tmp_path, monkeypatch):
    a = write(tmp_path / "a.txt")
    real_open = builtins.open

    def fake_open(file, mode="r", *args, **kwargs):
        if str(file) == str(a) and "rb" in mode:
            raise PermissionError("accès refusé")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)
    out = copier.copy_items([str(a)], str(tmp_path / "out"))
    assert out["copied_files"] == 0
    assert "accès refusé" in out["errors"][0]["error"]
    assert not (tmp_path / "out" / "a.txt").exists()


def test_partial_copy_is_kept_and_reported(tmp_path, monkeypatch):
    a = write(tmp_path / "a.txt", b"0123456789")

    def broken_copy(src, dst, length=0):
        dst.write(src.read(3))
        raise OSError("disque plein")

    monkeypatch.setattr(shutil, "copyfileobj", broken_copy)
    out = copier.copy_items([str(a)], str(tmp_path / "out"))
    assert "copie partielle conservée" in out["errors"][0]["error"]
    assert (tmp_path / "out" / "a.txt").read_bytes() == b"012"


def test_manifest_roundtrip_special_characters(tmp_path):
    a = write(tmp_path / "s;rc" / "it's;a=b,name.txt", b"abc")
    out = copier.copy_items([str(a)], str(tmp_path / "out"))
    with open(out["manifest"], encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))
    assert rows[1][1] == str(a)
    assert rows[1][2] == str(tmp_path / "out" / "it's;a=b,name.txt")


def test_bom_written_once(tmp_path):
    dest = tmp_path / "out"
    copier.copy_items([str(write(tmp_path / "a.txt"))], str(dest))
    out = copier.copy_items([str(write(tmp_path / "b.txt"))], str(dest))
    raw = open(out["manifest"], "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf") and raw.count(b"\xef\xbb\xbf") == 1


def test_directory_named_like_target_gives_suffix(tmp_path):
    (tmp_path / "out" / "a.txt").mkdir(parents=True)
    out = copier.copy_items([str(write(tmp_path / "s" / "a.txt", b"x"))], str(tmp_path / "out"))
    assert (tmp_path / "out" / "a (2).txt").read_bytes() == b"x"
    assert out["errors"] == []


def test_one_error_does_not_abort_others(tmp_path, monkeypatch):
    a = write(tmp_path / "a.txt")
    b = write(tmp_path / "b.txt", b"bb")
    real_open = builtins.open

    def fake_open(file, mode="r", *args, **kwargs):
        if str(file) == str(a) and "rb" in mode:
            raise PermissionError("refusé")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)
    out = copier.copy_items([str(a), str(b)], str(tmp_path / "out"))
    assert out["copied_files"] == 1 and len(out["errors"]) == 1
    assert (tmp_path / "out" / "b.txt").read_bytes() == b"bb"


def test_partial_copy_target_reported_in_folder_job(tmp_path, monkeypatch):
    src = tmp_path / "src" / "D"
    write(src / "sub" / "a.txt", b"0123456789")

    def broken_copy(s, d, length=0):
        d.write(s.read(3))
        raise OSError("disque plein")

    monkeypatch.setattr(shutil, "copyfileobj", broken_copy)
    out = copier.copy_items([str(src)], str(tmp_path / "out"))
    target = tmp_path / "out" / "D" / "sub" / "a.txt"
    assert out["errors"][0]["target"] == str(target)
    assert target.read_bytes() == b"012"


def test_close_failure_is_partial_copy(tmp_path, monkeypatch):
    a = write(tmp_path / "a.txt", b"abc")
    real_copyfileobj = shutil.copyfileobj

    def flaky(s, d, length=0):
        real_copyfileobj(s, d, length)
        d.flush = lambda: None  # le tampon sera vidé à la fermeture
        raise OSError("flush échoué")

    monkeypatch.setattr(shutil, "copyfileobj", flaky)
    out = copier.copy_items([str(a)], str(tmp_path / "out"))
    assert out["errors"][0]["target"] == str(tmp_path / "out" / "a.txt")


def test_copystat_failure_is_warning(tmp_path, monkeypatch):
    a = write(tmp_path / "a.txt", b"abc")

    def bad_stat(*args, **kwargs):
        raise OSError("stat refusé")

    monkeypatch.setattr(shutil, "copystat", bad_stat)
    out = copier.copy_items([str(a)], str(tmp_path / "out"))
    assert out["copied_files"] == 1 and out["errors"] == []
    assert out["warnings"][0]["target"] == str(tmp_path / "out" / "a.txt")
    assert (tmp_path / "out" / "a.txt").read_bytes() == b"abc"


def test_manifest_write_failure_does_not_abort(tmp_path, monkeypatch):
    a = write(tmp_path / "a.txt", b"a")
    b = write(tmp_path / "b.txt", b"b")

    class BadWriter:
        def __init__(self, *args, **kwargs):
            pass

        def writerow(self, row):
            raise OSError("disque plein")

    real_writer = csv.writer
    calls = []

    def fake_writer(f, *args, **kwargs):
        calls.append(1)
        return real_writer(f, *args, **kwargs) if len(calls) == 1 else BadWriter()

    monkeypatch.setattr(csv, "writer", fake_writer)
    out = copier.copy_items([str(a), str(b)], str(tmp_path / "out"))
    monkeypatch.undo()
    assert out["copied_files"] == 2
    assert out["manifest_error"] and "disque plein" in out["manifest_error"]
    assert str(tmp_path / "out" / "a.txt") in [e["target"] for e in out["errors"]]
    assert (tmp_path / "out" / "b.txt").read_bytes() == b"b"


def test_tree_mode_does_not_write_through_destination_junction(tmp_path):
    import subprocess
    root = tmp_path / "root"
    src = write(root / "sub" / "f.txt", b"x")
    out = tmp_path / "out"
    out.mkdir()
    elsewhere = tmp_path / "ailleurs"
    elsewhere.mkdir()
    subprocess.run(["cmd", "/c", "mklink", "/J", str(out / "sub"), str(elsewhere)],
                   check=True, capture_output=True)
    res = copier.copy_items([str(src)], str(out), preserve_tree_from=str(root))
    assert list(elsewhere.iterdir()) == []
    assert res["copied_files"] == 0
    assert "hors de la destination" in res["errors"][0]["error"]
