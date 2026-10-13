"""Résumé d'un dossier (sous-dossiers, nombre de fichiers, tailles, extensions) depuis l'index Everything."""

import os

import config
import everything_backend


def _stats():
    return {"files": 0, "folders": 0, "size": 0}


def folder_info(path, depth=1, *, search=None, max_items=None):
    search = search or everything_backend.search
    max_items = config.FOLDER_MAX_ITEMS if max_items is None else max_items
    depth = max(1, min(int(depth), 5))
    if not os.path.isabs(path) or not os.path.isdir(path):
        raise ValueError(f"Dossier introuvable ou chemin non absolu : {path}")

    root = os.path.normpath(path)
    prefix = root.rstrip("\\") + "\\"
    entries = search(f'"{prefix}"', max_results=max_items + 1, sort="path", descending=False)
    truncated = len(entries) > max_items
    entries = entries[:max_items]

    total, subfolders, by_ext, latest = _stats(), {}, {}, None
    for entry in entries:
        if not entry.path.lower().startswith(prefix.lower()):
            continue
        rel = entry.path[len(prefix):]
        parts = rel.split("\\")
        # sous-dossiers suivis (jusqu'à `depth`) qui contiennent cet élément
        ancestors = ["\\".join(parts[:k]) for k in range(1, min(depth, len(parts) - 1) + 1)]
        if entry.is_dir:
            total["folders"] += 1
            for a in ancestors:
                subfolders.setdefault(a, _stats())["folders"] += 1
            if len(parts) <= depth:
                subfolders.setdefault(rel, _stats())
            continue
        size = entry.size or 0
        total["files"] += 1
        total["size"] += size
        for a in ancestors:
            stats = subfolders.setdefault(a, _stats())
            stats["files"] += 1
            stats["size"] += size
        ext = os.path.splitext(parts[-1])[1].lower() or "(sans extension)"
        ext_stats = by_ext.setdefault(ext, {"files": 0, "size": 0})
        ext_stats["files"] += 1
        ext_stats["size"] += size
        if entry.modified and (latest is None or entry.modified > latest):
            latest = entry.modified

    return {
        "path": root,
        **total,
        "latest_modified": latest,
        "truncated": truncated,
        "subfolders": [
            {"path": os.path.join(root, rel), "relative": rel, **stats}
            for rel, stats in sorted(subfolders.items())
        ],
        "by_extension": sorted(
            ({"extension": ext, **stats} for ext, stats in by_ext.items()),
            key=lambda d: -d["size"],
        )[:30],
    }
