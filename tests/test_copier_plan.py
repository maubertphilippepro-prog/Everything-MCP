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
