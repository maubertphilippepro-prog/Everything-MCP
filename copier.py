"""Copie sûre de fichiers et de dossiers.

Garde-fou : ce module ne fait que créer. Il n'écrase, ne déplace, ne renomme et ne
supprime jamais rien. Chaque fichier est créé en mode exclusif ("xb") ; si le nom est
déjà pris, un suffixe " (2)", " (3)"… est ajouté. Un dossier copié n'est jamais fusionné
dans un dossier existant.
"""

import os
from dataclasses import dataclass, field


class CopyRefused(Exception):
    """La copie est refusée dans son ensemble : rien n'a été créé."""


def _norm(path):
    return os.path.normcase(os.path.normpath(path))


def is_within(path, parent):
    p, q = _norm(path), _norm(parent)
    return p == q or p.startswith(q.rstrip("\\") + "\\")


def _forbidden_roots():
    roots = []
    for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        value = os.environ.get(var)
        if value:
            roots.append(value)
    return roots


def check_destination(destination):
    if not destination or not os.path.isabs(destination) or not os.path.splitdrive(destination)[0]:
        raise CopyRefused(f"La destination doit être un chemin absolu (ex. C:\\...\\extract) : {destination!r}")
    dest = os.path.normpath(destination)
    if _norm(dest) == _norm(os.path.splitdrive(dest)[0] + "\\"):
        raise CopyRefused(f"Copie à la racine d'un lecteur refusée : {dest}")
    for root in _forbidden_roots():
        if is_within(dest, root):
            raise CopyRefused(f"Destination dans un dossier système refusée : {dest}")
    if os.path.exists(dest) and not os.path.isdir(dest):
        raise CopyRefused(f"La destination existe et n'est pas un dossier : {dest}")
    return dest


@dataclass
class FileJob:
    source: str
    parent: str   # dossier cible, créé au besoin
    name: str
    size: int


@dataclass
class DirJob:
    source: str
    parent: str   # dossier dans lequel créer la copie du dossier
    name: str
    files: list   # [(chemin source, chemin relatif, taille)]
    subdirs: list  # [chemin relatif]


@dataclass
class Plan:
    destination: str
    mode: str
    jobs: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    tree_dirs: list = field(default_factory=list)

    @property
    def file_count(self):
        return sum(1 if isinstance(j, FileJob) else len(j.files) for j in self.jobs)

    @property
    def total_bytes(self):
        return sum(j.size if isinstance(j, FileJob) else sum(s for _, _, s in j.files) for j in self.jobs)


def _is_link(path):
    return os.path.islink(path) or os.path.isjunction(path)


def _walk_dir(top, skipped):
    """Fichiers [(source, relatif, taille)] et sous-dossiers relatifs, sans suivre liens ni jonctions."""
    files, dirs = [], []
    stack = [""]
    while stack:
        rel = stack.pop()
        current = os.path.join(top, rel) if rel else top
        try:
            entries = sorted(os.scandir(current), key=lambda e: e.name)
        except OSError as e:
            skipped.append({"source": current, "reason": f"dossier illisible : {e}"})
            continue
        for entry in entries:
            child_rel = os.path.join(rel, entry.name) if rel else entry.name
            if entry.is_symlink() or entry.is_junction():
                skipped.append({"source": entry.path, "reason": "lien symbolique ou jonction non suivi"})
            elif entry.is_dir(follow_symlinks=False):
                dirs.append(child_rel)
                stack.append(child_rel)
            else:
                files.append((entry.path, child_rel, entry.stat(follow_symlinks=False).st_size))
    return files, dirs


def plan_copy(paths, destination, preserve_tree_from=""):
    """Liste tout ce qui sera copié, sans rien créer."""
    dest = check_destination(destination)
    root = None
    if preserve_tree_from:
        if not os.path.isabs(preserve_tree_from) or not os.path.isdir(preserve_tree_from):
            raise CopyRefused(
                f"preserve_tree_from doit être un dossier existant, en chemin absolu : {preserve_tree_from!r}")
        root = os.path.normpath(preserve_tree_from)

    plan = Plan(dest, "tree" if root else "flat")
    seen = set()
    for raw in paths:
        if not raw or not os.path.isabs(raw):
            plan.skipped.append({"source": raw, "reason": "chemin non absolu"})
            continue
        src = os.path.normpath(raw)
        if _norm(src) in seen:
            plan.skipped.append({"source": src, "reason": "en double dans la liste"})
            continue
        seen.add(_norm(src))
        if _is_link(src):
            plan.skipped.append({"source": src, "reason": "lien symbolique ou jonction non suivi"})
        elif os.path.isdir(src):
            _plan_dir(plan, src, dest, root)
        elif os.path.isfile(src):
            _plan_file(plan, src, dest, root)
        else:
            plan.skipped.append({"source": src, "reason": "introuvable"})
    return plan


def _plan_file(plan, src, dest, root):
    if root:
        if not is_within(src, root):
            plan.skipped.append({"source": src, "reason": "hors de la racine preserve_tree_from"})
            return
        parent = os.path.join(dest, os.path.dirname(os.path.relpath(src, root)))
    else:
        parent = dest
    if _norm(os.path.dirname(src)) == _norm(parent):
        plan.skipped.append({"source": src, "reason": "déjà dans la destination"})
        return
    plan.jobs.append(FileJob(src, os.path.normpath(parent), os.path.basename(src), os.path.getsize(src)))


def _plan_dir(plan, src, dest, root):
    if is_within(dest, src):
        raise CopyRefused(
            f"La destination {dest} est à l'intérieur du dossier source {src} : copie sans fin refusée.")
    if root:
        if not is_within(src, root):
            plan.skipped.append({"source": src, "reason": "hors de la racine preserve_tree_from"})
            return
        rel = os.path.relpath(src, root)
        base = dest if rel == "." else os.path.join(dest, rel)
        files, dirs = _walk_dir(src, plan.skipped)
        plan.tree_dirs.append(base)
        plan.tree_dirs += [os.path.join(base, d) for d in dirs]
        for fsrc, frel, size in files:
            plan.jobs.append(FileJob(fsrc, os.path.normpath(os.path.join(base, os.path.dirname(frel))),
                                     os.path.basename(frel), size))
    else:
        files, dirs = _walk_dir(src, plan.skipped)
        name = os.path.basename(src) or src.replace(":", "").strip("\\")
        plan.jobs.append(DirJob(src, dest, name, files, dirs))
