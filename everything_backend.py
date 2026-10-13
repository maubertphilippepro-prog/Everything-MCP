"""Exécution des requêtes Everything, via es.exe (défaut) ou le serveur HTTP d'Everything."""

import csv
import io
import json
import os
import subprocess
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

import config

SORTS = ("name", "path", "size", "extension", "date-modified", "date-created")
FILE_ATTRIBUTE_DIRECTORY = 0x10


class EverythingError(RuntimeError):
    """Everything injoignable ou requête refusée."""


@dataclass
class Entry:
    path: str
    size: int | None
    modified: str | None
    attributes: int | None
    is_dir: bool

    def to_dict(self):
        data = {"path": self.path, "size": self.size, "modified": self.modified}
        if self.is_dir:
            data["type"] = "folder"
        return data


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "mbcs", "cp1252"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def neutralize_options(query):
    """Entoure de < > les mots commençant par - ou / (hors guillemets).

    es.exe lit ces mots comme des options (dont -export-csv, qui écrit un fichier) ;
    entre < >, Everything les traite comme de simples termes de recherche.
    """
    tokens, token, in_quotes = [], "", False
    for ch in query:
        if ch == '"':
            in_quotes = not in_quotes
        if ch.isspace() and not in_quotes:
            if token:
                tokens.append(token)
                token = ""
            continue
        token += ch
    if token:
        tokens.append(token)
    return " ".join(f"<{t}>" if t[0] in "-/" else t for t in tokens)


def es_command_line(query, max_results, offset=0, sort="date-modified", descending=True,
                    match_path=False, regex=False, export_path=None):
    """Ligne de commande es.exe. La requête est ajoutée brute : passée comme un seul
    argument, es.exe la traiterait comme une expression exacte.

    Avec export_path, es.exe écrit le CSV en UTF-8 dans ce fichier : sur stdout il
    emploie la page de code OEM de la console, qui perd les caractères hors page (œ...)."""
    args = [config.ES_PATH]
    if config.INSTANCE:
        args += ["-instance", config.INSTANCE]
    args += [
        "-csv", "-size", "-dm", "-attributes",
        "-size-format", "1",   # tailles en octets
        "-date-format", "1",   # dates ISO-8601
    ]
    if export_path:
        args += ["-export-csv", export_path, "-utf8-bom"]
    args += [
        "-n", str(max_results),
        "-o", str(offset),
        "-sort", sort if sort in SORTS else "date-modified",
        "-sort-descending" if descending else "-sort-ascending",
    ]
    if match_path:
        args.append("-p")
    if regex:
        args.append("-r")
    return subprocess.list2cmdline(args) + " " + neutralize_options(query)


def parse_es_csv(text):
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    header, data = rows[0], rows[1:]
    entries = []
    for row in data:
        if not row:
            continue
        rec = dict(zip(header, row))
        path = row[0]
        size = rec.get("Size", "")
        attrs = rec.get("Attributes", "")
        attributes = int(attrs) if attrs.isdigit() else None
        is_dir = path.endswith("\\") or bool(attributes and attributes & FILE_ATTRIBUTE_DIRECTORY)
        if path.endswith("\\") and len(path) > 3:
            path = path.rstrip("\\")
        entries.append(Entry(
            path=path,
            size=int(size) if size.isdigit() else None,
            modified=rec.get("Date Modified") or None,
            attributes=attributes,
            is_dir=is_dir,
        ))
    return entries


def _search_es(query, max_results, offset, sort, descending, match_path, regex):
    fd, export_path = tempfile.mkstemp(suffix=".csv", prefix="everything_mcp_")
    os.close(fd)
    try:
        cmd = es_command_line(query, max_results, offset, sort, descending, match_path, regex,
                              export_path=export_path)
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError:
            raise EverythingError(f"es.exe introuvable : {config.ES_PATH}. Renseignez ES_PATH.")
        except subprocess.TimeoutExpired:
            raise EverythingError("La recherche Everything a dépassé 120 s.")

        if proc.returncode != 0:
            err = _decode(proc.stderr or proc.stdout).strip()
            hint = " Everything est-il lancé ?" if proc.returncode == 8 else ""
            raise EverythingError(f"es.exe a échoué (code {proc.returncode}) : {err}{hint}")
        with open(export_path, "rb") as f:
            return parse_es_csv(f.read().decode("utf-8-sig", errors="replace"))
    finally:
        try:
            os.remove(export_path)
        except OSError:
            pass


def _filetime_to_iso(ft):
    try:
        ts = (int(ft) - 116444736000000000) / 10_000_000
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return None


def _search_http(query, max_results, offset, sort, descending, match_path, regex):
    http_sort = {"date-modified": "date_modified", "date-created": "date_created"}.get(sort, sort)
    params = {
        "search": query, "json": 1, "count": max_results, "offset": offset,
        "path_column": 1, "size_column": 1, "date_modified_column": 1,
        "sort": http_sort, "ascending": 0 if descending else 1,
        "path": 1 if match_path else 0, "regex": 1 if regex else 0,
    }
    url = f"{config.HTTP_URL}/?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except OSError as e:
        raise EverythingError(f"Serveur HTTP Everything injoignable ({config.HTTP_URL}) : {e}") from e
    except ValueError as e:
        raise EverythingError(f"Réponse invalide du serveur HTTP Everything : {e}") from e
    if not isinstance(payload, dict):
        raise EverythingError("Réponse invalide du serveur HTTP Everything : objet JSON attendu.")

    entries = []
    for r in payload.get("results", []):
        folder, name, size = r.get("path", ""), r.get("name", ""), r.get("size")
        entries.append(Entry(
            path=f"{folder}\\{name}" if folder else name,
            size=int(size) if str(size or "").isdigit() else None,
            modified=_filetime_to_iso(r.get("date_modified")),
            attributes=None,
            is_dir=r.get("type") == "folder",
        ))
    return entries


def search(query, max_results=50, offset=0, sort="date-modified", descending=True,
           match_path=False, regex=False):
    """Exécute une requête Everything et renvoie une liste d'Entry."""
    backend = _search_http if config.BACKEND == "http" else _search_es
    return backend(query, max_results, offset, sort, descending, match_path, regex)
