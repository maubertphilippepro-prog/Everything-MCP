"""Recherche d'une expression exacte dans le contenu des fichiers sélectionnés par Everything."""

import os
import time

import config
import everything_backend
import extractors

# OFFLINE | RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN — OneDrive « en ligne uniquement » porte 0x400000.
CLOUD_ATTRIBUTES = 0x1000 | 0x400000 | 0x40000


class TooManyCandidates(Exception):
    pass


def is_cloud_only(entry):
    attributes = entry.attributes
    if attributes is None:
        try:
            attributes = os.stat(entry.path, follow_symlinks=False).st_file_attributes
        except OSError:
            return False
    return bool(attributes & CLOUD_ATTRIBUTES)


def find_content(query, phrase, case_sensitive=False, include_cloud=False, allow_raw=True,
                 max_candidates=2000, *, search=None, match=None, timeout=None, clock=time.monotonic):
    if not phrase:
        raise ValueError("L'expression à chercher (phrase) est vide.")
    search = search or everything_backend.search
    match = match or extractors.match_file
    timeout = config.CONTENT_TIMEOUT if timeout is None else timeout

    full_query = f"{query} file:"
    candidates = search(full_query, max_results=max_candidates + 1, sort="path", descending=False)
    if len(candidates) > max_candidates:
        raise TooManyCandidates(
            f"Plus de {max_candidates} fichiers candidats : restreindre la requête "
            f"(dossier avec \"D:\\...\\\" ou path:, ext:, dm:) avant de chercher dans le contenu."
        )

    deadline = clock() + timeout
    matches, unverified, not_matching = [], [], 0
    for i, entry in enumerate(candidates):
        if clock() > deadline:
            unverified += [{"path": e.path, "reason": "délai dépassé"} for e in candidates[i:]]
            break
        if entry.is_dir:
            continue
        if not include_cloud and is_cloud_only(entry):
            unverified.append({"path": entry.path, "reason": "en ligne uniquement (OneDrive), non téléchargé"})
            continue
        try:
            result = match(entry.path, phrase, case_sensitive=case_sensitive, allow_raw=allow_raw)
        except Exception as e:
            unverified.append({"path": entry.path, "reason": f"erreur de lecture : {e}"})
            continue
        if result.matched is None:
            unverified.append({"path": entry.path, "reason": result.reason})
        elif result.matched:
            matches.append({**entry.to_dict(), "method": result.method})
        else:
            not_matching += 1

    return {
        "query": full_query,
        "phrase": phrase,
        "candidates": len(candidates),
        "matches": matches,
        "not_matching": not_matching,
        "unverified": unverified,
    }
