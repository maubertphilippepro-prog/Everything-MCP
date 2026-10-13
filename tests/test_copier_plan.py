import os
import subprocess

import pytest

import copier


def write(path, content=b"data"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_relative_destination_refused():
    with pytest.raises(copier.CopyRefused, match="absolu"):
        copier.plan_copy([], "extract")


def test_drive_root_refused():
    with pytest.raises(copier.CopyRefused, match="racine"):
        copier.plan_copy([], "C:\\")


def test_system_folder_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("SystemRoot", str(tmp_path / "win"))
    with pytest.raises(copier.CopyRefused, match="système"):
        copier.plan_copy([], str(tmp_path / "win" / "sub"))


def test_destination_that_is_a_file_refused(tmp_path):
    f = write(tmp_path / "f")
    with pytest.raises(copier.CopyRefused, match="pas un dossier"):
        copier.plan_copy([], str(f))


def test_destination_inside_source_folder_refused(tmp_path):
    src = tmp_path / "src"
    write(src / "a.txt")
    with pytest.raises(copier.CopyRefused, match="sans fin"):
        copier.plan_copy([str(src)], str(src / "extract"))


def test_plan_flat_files_and_dirs_creates_nothing(tmp_path):
    a = write(tmp_path / "src" / "a.txt", b"12345")
    write(tmp_path / "src" / "d" / "b.txt", b"xy")
    (tmp_path / "src" / "d" / "vide").mkdir()
    plan = copier.plan_copy([str(a), str(tmp_path / "src" / "d")], str(tmp_path / "out"))
    assert plan.mode == "flat"
    assert (plan.file_count, plan.total_bytes) == (2, 7)
    dir_job = plan.jobs[1]
    assert isinstance(dir_job, copier.DirJob) and dir_job.name == "d" and dir_job.subdirs == ["vide"]
    assert not (tmp_path / "out").exists()


def test_plan_skips(tmp_path):
    dest = tmp_path / "out"
    inside = write(dest / "deja.txt")
    a = write(tmp_path / "a.txt")
    plan = copier.plan_copy(["relatif.txt", str(tmp_path / "absent.txt"), str(inside), str(a), str(a)], str(dest))
    assert [s["reason"] for s in plan.skipped] == [
        "chemin non absolu", "introuvable", "déjà dans la destination", "en double dans la liste",
    ]
    assert plan.file_count == 1


def test_plan_tree_mode(tmp_path):
    root = tmp_path / "Chantiers"
    f = write(root / "A" / "B" / "f.xls")
    other = write(tmp_path / "autre.xls")
    plan = copier.plan_copy([str(f), str(other)], str(tmp_path / "out"), preserve_tree_from=str(root))
    assert plan.mode == "tree"
    assert plan.jobs[0].parent == str(tmp_path / "out" / "A" / "B")
    assert plan.skipped == [{"source": str(other), "reason": "hors de la racine preserve_tree_from"}]


def test_tree_root_must_exist(tmp_path):
    with pytest.raises(copier.CopyRefused, match="preserve_tree_from"):
        copier.plan_copy([], str(tmp_path / "out"), preserve_tree_from=str(tmp_path / "absent"))


def test_junction_not_followed(tmp_path):
    src = tmp_path / "src"
    write(src / "a.txt")
    write(tmp_path / "cible" / "secret.txt")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(src / "lien"), str(tmp_path / "cible")],
                   check=True, capture_output=True)
    plan = copier.plan_copy([str(src)], str(tmp_path / "out"))
    assert plan.file_count == 1
    assert plan.skipped == [{"source": str(src / "lien"), "reason": "lien symbolique ou jonction non suivi"}]


def test_tree_dir_onto_itself_skipped(tmp_path):
    root = tmp_path / "R"
    write(root / "B" / "f.txt")
    plan = copier.plan_copy([str(root / "B")], str(root), preserve_tree_from=str(root))
    assert plan.jobs == []
    assert plan.skipped == [{"source": str(root / "B"), "reason": "déjà dans la destination"}]


def test_flat_dir_onto_itself_skipped(tmp_path):
    write(tmp_path / "R" / "B" / "f.txt")
    plan = copier.plan_copy([str(tmp_path / "R" / "B")], str(tmp_path / "R"))
    assert plan.jobs == []
    assert [s["reason"] for s in plan.skipped] == ["déjà dans la destination"]


def test_destination_through_junction_into_source_refused(tmp_path):
    src = tmp_path / "src"
    write(src / "a.txt")
    link = tmp_path / "lien"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(src)], check=True, capture_output=True)
    with pytest.raises(copier.CopyRefused, match="sans fin"):
        copier.plan_copy([str(src)], str(link / "sub"))


def test_short_name_of_system_folder_refused():
    import ctypes
    root = os.environ["SystemRoot"]
    buf = ctypes.create_unicode_buffer(512)
    assert ctypes.windll.kernel32.GetShortPathNameW(root, buf, 512)
    short = os.path.join(os.path.dirname(buf.value), os.path.basename(buf.value), "sub")
    with pytest.raises(copier.CopyRefused, match="système"):
        copier.plan_copy([], short)


def test_destination_junction_to_system_folder_refused(tmp_path):
    link = tmp_path / "sys"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), os.environ["SystemRoot"]],
                   check=True, capture_output=True)
    with pytest.raises(copier.CopyRefused, match="système"):
        copier.plan_copy([], str(link / "sub"))


def test_stat_error_in_walk_skips_entry(tmp_path, monkeypatch):
    src = tmp_path / "src"
    write(src / "ok.txt")
    write(src / "bad.txt")
    real_scandir = os.scandir

    class Bad:
        name = "bad.txt"
        path = str(src / "bad.txt")

        def is_symlink(self):
            raise PermissionError("refusé")

    def fake(path):
        return [e if e.name != "bad.txt" else Bad() for e in real_scandir(path)]

    monkeypatch.setattr(os, "scandir", fake)
    plan = copier.plan_copy([str(src)], str(tmp_path / "out"))
    assert plan.file_count == 1
    assert len(plan.skipped) == 1
    assert plan.skipped[0]["reason"].startswith("illisible : ")


def test_getsize_error_skips_file(tmp_path, monkeypatch):
    a = write(tmp_path / "a.txt")

    def boom(p):
        raise OSError("boum")

    monkeypatch.setattr(os.path, "getsize", boom)
    plan = copier.plan_copy([str(a)], str(tmp_path / "out"))
    assert plan.jobs == []
    assert plan.skipped[0]["reason"] == "illisible : boum"


def test_is_within():
    assert copier.is_within(r"C:\a\b", r"C:\a")
    assert copier.is_within(r"C:\a", r"C:\a")
    assert not copier.is_within(r"C:\ab", r"C:\a")
    assert copier.is_within(r"c:\A\B", r"C:\a")
    assert copier.is_within(r"C:\a\b", r"C:\a\\")
    assert copier.is_within(r"C:\a", r"C:\a\\")
    assert copier.is_within(r"C:\a", r"C:\\")
    assert copier.is_within(r"C:\\", r"C:\\")
    assert not copier.is_within(r"D:\a", r"C:\\")


def test_system_folders_forbidden_without_env_vars(monkeypatch):
    for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "SystemDrive"):
        monkeypatch.delenv(var, raising=False)
    for dest in (r"C:\Windows\x", r"C:\Program Files\x", r"C:\Program Files (x86)\x", r"C:\ProgramData\x"):
        with pytest.raises(copier.CopyRefused, match="système"):
            copier.plan_copy([], dest)


def test_known_folder_api_gives_windows_dir():
    paths = [os.path.normcase(p) for p in copier._known_folder_paths()]
    assert os.path.normcase(os.environ["SystemRoot"]) in paths


def test_folder_and_its_contents_not_planned_twice(tmp_path):
    src = tmp_path / "src"
    f = write(src / "sous" / "a.txt")
    write(src / "b.txt")
    plan = copier.plan_copy([str(src), str(f), str(src / "sous")], str(tmp_path / "out"),
                            preserve_tree_from=str(tmp_path))
    assert plan.file_count == 2
    assert [s["reason"] for s in plan.skipped] == [f"déjà inclus dans {src}"] * 2


def test_folder_listed_after_its_contents_still_wins(tmp_path):
    src = tmp_path / "src"
    f = write(src / "a.txt")
    plan = copier.plan_copy([str(f), str(src)], str(tmp_path / "out"))
    assert plan.file_count == 1
    assert plan.skipped[0]["source"] == str(f) and "déjà inclus" in plan.skipped[0]["reason"]


def test_container_outside_tree_root_does_not_suppress_inner_files(tmp_path):
    c = tmp_path / "C"
    f = write(c / "Martin" / "f.xls")
    plan = copier.plan_copy([str(c), str(f)], str(tmp_path / "out"), preserve_tree_from=str(c / "Martin"))
    assert plan.file_count == 1
    assert [s["reason"] for s in plan.skipped] == ["hors de la racine preserve_tree_from"]
