"""Copie sûre de fichiers et de dossiers.

Garde-fou : ce module ne fait que créer. Il n'écrase, ne déplace, ne renomme et ne
supprime jamais rien. Chaque fichier est créé en mode exclusif ("xb") ; si le nom est
déjà pris, un suffixe " (2)", " (3)"… est ajouté. Un dossier copié n'est jamais fusionné
dans un dossier existant.
"""

import csv
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime

import config


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
    real = os.path.realpath(dest)
    if _norm(real) == _norm(os.path.splitdrive(real)[0] + "\\"):
        raise CopyRefused(f"Copie à la racine d'un lecteur refusée : {dest} (résolu en {real})")
    for root in _forbidden_roots():
        if is_within(dest, root) or is_within(real, os.path.realpath(root)):
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
            try:
                if entry.is_symlink() or entry.is_junction():
                    skipped.append({"source": entry.path, "reason": "lien symbolique ou jonction non suivi"})
                elif entry.is_dir(follow_symlinks=False):
                    dirs.append(child_rel)
                    stack.append(child_rel)
                else:
                    files.append((entry.path, child_rel, entry.stat(follow_symlinks=False).st_size))
            except OSError as e:
                skipped.append({"source": entry.path, "reason": f"illisible : {e}"})
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
    try:
        size = os.path.getsize(src)
    except OSError as e:
        plan.skipped.append({"source": src, "reason": f"illisible : {e}"})
        return
    plan.jobs.append(FileJob(src, os.path.normpath(parent), os.path.basename(src), size))


def _plan_dir(plan, src, dest, root):
    if is_within(dest, src) or is_within(os.path.realpath(dest), os.path.realpath(src)):
        raise CopyRefused(
            f"La destination {dest} est à l'intérieur du dossier source {src} : copie sans fin refusée.")
    if root:
        if not is_within(src, root):
            plan.skipped.append({"source": src, "reason": "hors de la racine preserve_tree_from"})
            return
        rel = os.path.relpath(src, root)
        base = dest if rel == "." else os.path.join(dest, rel)
        if _norm(base) == _norm(src) or _norm(os.path.realpath(base)) == _norm(os.path.realpath(src)):
            plan.skipped.append({"source": src, "reason": "déjà dans la destination"})
            return
        files, dirs = _walk_dir(src, plan.skipped)
        plan.tree_dirs.append(base)
        plan.tree_dirs += [os.path.join(base, d) for d in dirs]
        for fsrc, frel, size in files:
            plan.jobs.append(FileJob(fsrc, os.path.normpath(os.path.join(base, os.path.dirname(frel))),
                                     os.path.basename(frel), size))
    else:
        files, dirs = _walk_dir(src, plan.skipped)
        name = os.path.basename(src) or src.replace(":", "").strip("\\")
        if _norm(os.path.join(dest, name)) == _norm(src):
            plan.skipped.append({"source": src, "reason": "déjà dans la destination"})
            return
        plan.jobs.append(DirJob(src, dest, name, files, dirs))


MANIFEST_NAME = "manifest.csv"
MANIFEST_HEADER = ["date_copie", "source", "copie", "taille"]
COPY_BUFFER = 1024 * 1024
MAX_SUFFIX = 10_000


class PartialCopyError(Exception):
    def __init__(self, target, cause):
        super().__init__(f"{cause} (copie partielle conservée : {target})")
        self.target = target


def human_size(n):
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or unit == "Go":
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}"
        n /= 1024


def _candidate_name(name, i, keep_ext=True):
    if i == 1:
        return name
    if not keep_ext:
        return f"{name} ({i})"
    stem, ext = os.path.splitext(name)
    return f"{stem} ({i}){ext}"


def copy_file_exclusive(source, parent, name):
    """Copie `source` dans `parent` sous un nom libre, sans jamais écraser. Renvoie le chemin créé."""
    with open(source, "rb") as src:
        for i in range(1, MAX_SUFFIX):
            target = os.path.join(parent, _candidate_name(name, i))
            try:
                dst = open(target, "xb")
            except FileExistsError:
                continue
            with dst:
                try:
                    shutil.copyfileobj(src, dst, COPY_BUFFER)
                except OSError as e:
                    raise PartialCopyError(target, e) from e
            shutil.copystat(source, target)
            return target
    raise OSError(f"Aucun nom libre pour {name} dans {parent}")


def _mkdir_unique(parent, name):
    for i in range(1, MAX_SUFFIX):
        target = os.path.join(parent, _candidate_name(name, i, keep_ext=False))
        try:
            os.mkdir(target)
            return target
        except FileExistsError:
            continue
    raise OSError(f"Aucun nom de dossier libre pour {name} dans {parent}")


def _is_our_manifest(path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            return next(csv.reader(f, delimiter=";"), None) == MANIFEST_HEADER
    except (OSError, UnicodeDecodeError):
        return False


def _open_manifest(destination):
    """Ouvre notre manifeste en ajout, ou en crée un nouveau ; ne touche jamais un fichier étranger."""
    for i in range(1, MAX_SUFFIX):
        path = os.path.join(destination, _candidate_name(MANIFEST_NAME, i))
        try:
            f = open(path, "x", encoding="utf-8-sig", newline="")
            csv.writer(f, delimiter=";").writerow(MANIFEST_HEADER)
            return path, f
        except FileExistsError:
            if _is_our_manifest(path):
                return path, open(path, "a", encoding="utf-8", newline="")
    raise OSError("Impossible de créer le manifeste")


def execute(plan, max_files=None, max_bytes=None):
    max_files = config.COPY_MAX_FILES if max_files is None else max_files
    max_bytes = config.COPY_MAX_BYTES if max_bytes is None else max_bytes
    if plan.file_count > max_files:
        raise CopyRefused(f"{plan.file_count} fichiers à copier : au-delà du plafond de {max_files} "
                          f"(EVERYTHING_COPY_MAX_FILES). Rien n'a été copié.")
    if plan.total_bytes > max_bytes:
        raise CopyRefused(f"{human_size(plan.total_bytes)} à copier : au-delà du plafond de "
                          f"{human_size(max_bytes)} (EVERYTHING_COPY_MAX_BYTES). Rien n'a été copié.")

    result = {"destination": plan.destination, "mode": plan.mode, "copied_files": 0, "copied_bytes": 0,
              "copied": [], "skipped": plan.skipped, "errors": [], "manifest": None}
    if not plan.jobs and not plan.tree_dirs:
        return result

    os.makedirs(plan.destination, exist_ok=True)
    copied, errors = [], result["errors"]
    manifest_path, manifest = _open_manifest(plan.destination)
    with manifest:
        writer = csv.writer(manifest, delimiter=";")

        def copy_one(source, parent, name, size):
            try:
                os.makedirs(parent, exist_ok=True)
                target = copy_file_exclusive(source, parent, name)
            except (OSError, PartialCopyError) as e:
                errors.append({"source": source, "error": str(e)})
                return
            copied.append({"source": source, "copy": target, "size": size})
            writer.writerow([datetime.now().isoformat(timespec="seconds"), source, target, size])
            manifest.flush()

        for directory in plan.tree_dirs:
            try:
                os.makedirs(directory, exist_ok=True)
            except OSError as e:
                errors.append({"source": directory, "error": str(e)})
        for job in plan.jobs:
            if isinstance(job, FileJob):
                copy_one(job.source, job.parent, job.name, job.size)
                continue
            try:
                base = _mkdir_unique(job.parent, job.name)
                for sub in job.subdirs:
                    os.makedirs(os.path.join(base, sub), exist_ok=True)
            except OSError as e:
                errors.append({"source": job.source, "error": str(e)})
                continue
            for source, rel, size in job.files:
                copy_one(source, os.path.join(base, os.path.dirname(rel)), os.path.basename(rel), size)

    result.update(copied_files=len(copied), copied_bytes=sum(c["size"] for c in copied),
                  copied=copied[:200], manifest=manifest_path)
    return result


def copy_items(paths, destination, preserve_tree_from="", max_files=None, max_bytes=None):
    return execute(plan_copy(paths, destination, preserve_tree_from), max_files, max_bytes)
