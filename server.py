"""
Passerelle MCP entre Claude et Everything (voidtools).

Claude traduit la demande en langage naturel en requête Everything,
ce serveur l'exécute localement et renvoie les résultats (chemin, taille, date).

Deux moteurs possibles (variable EVERYTHING_BACKEND) :
  - "es"   (défaut) : utilise es.exe, l'interface en ligne de commande d'Everything
  - "http"          : utilise le serveur HTTP intégré d'Everything (à activer dans les options)
"""

import csv
import io
import json
import os
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone

try:  # SDK MCP v2
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # SDK MCP v1
    from mcp.server.fastmcp import FastMCP

ES_PATH = os.environ.get("ES_PATH", r"C:\Program Files\Everything\es.exe")
BACKEND = os.environ.get("EVERYTHING_BACKEND", "es").lower()
HTTP_URL = os.environ.get("EVERYTHING_HTTP_URL", "http://127.0.0.1:8080").rstrip("/")
INSTANCE = os.environ.get("EVERYTHING_INSTANCE", "")  # ex. "1.5a" pour Everything 1.5 alpha
HARD_LIMIT = int(os.environ.get("EVERYTHING_MAX_RESULTS", "500"))
EVERYTHING_EXE = os.environ.get(
    "EVERYTHING_EXE", os.path.join(os.path.dirname(ES_PATH), "Everything.exe")
)

SORTS = ("name", "path", "size", "extension", "date-modified", "date-created")

mcp = FastMCP("everything")


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "mbcs", "cp1252"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _search_es(query, max_results, offset, sort, descending, match_path, regex):
    args = [ES_PATH]
    if INSTANCE:
        args += ["-instance", INSTANCE]
    args += [
        "-csv", "-size", "-dm",
        "-size-format", "1",   # tailles en octets
        "-date-format", "1",   # dates ISO-8601
        "-n", str(max_results),
        "-o", str(offset),
        "-sort", sort,
        "-sort-descending" if descending else "-sort-ascending",
    ]
    if match_path:
        args.append("-p")
    if regex:
        args.append("-r")
    args.append(query)

    try:
        proc = subprocess.run(
            args, capture_output=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        raise RuntimeError(f"es.exe introuvable : {ES_PATH}. Renseignez ES_PATH.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("La recherche a dépassé 60 s (une recherche content: est peut-être en cours).")

    if proc.returncode != 0:
        err = _decode(proc.stderr or proc.stdout).strip()
        hint = " Everything est-il lancé ?" if proc.returncode == 8 else ""
        raise RuntimeError(f"es.exe a échoué (code {proc.returncode}) : {err}{hint}")

    rows = list(csv.reader(io.StringIO(_decode(proc.stdout))))
    if not rows:
        return []
    header, data = rows[0], rows[1:]
    results = []
    for row in data:
        if not row:
            continue
        rec = dict(zip(header, row))
        path = row[0]
        size = rec.get("Size", "")
        results.append({
            "path": path,
            "size": int(size) if size.isdigit() else None,
            "modified": rec.get("Date Modified") or None,
        })
    return results


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
    url = f"{HTTP_URL}/?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except OSError as e:
        raise RuntimeError(f"Serveur HTTP Everything injoignable ({HTTP_URL}) : {e}")

    results = []
    for r in payload.get("results", []):
        folder = r.get("path", "")
        name = r.get("name", "")
        size = r.get("size")
        results.append({
            "path": f"{folder}\\{name}" if folder else name,
            "type": r.get("type"),
            "size": int(size) if str(size or "").isdigit() else None,
            "modified": _filetime_to_iso(r.get("date_modified")),
        })
    return results, payload.get("totalResults")


@mcp.tool()
def everything_search(
    query: str,
    max_results: int = 50,
    offset: int = 0,
    sort: str = "date-modified",
    descending: bool = True,
    match_path: bool = False,
    regex: bool = False,
) -> str:
    """Recherche instantanée de fichiers et dossiers sur le PC Windows de l'utilisateur via Everything.

    Traduire la demande de l'utilisateur en requête Everything. La syntaxe est TOUJOURS en anglais.

    Opérateurs : espace = ET, | = OU, ! = NON, < > = groupement, "..." = expression exacte.
    Jokers : * (0+ caractères), ? (1 caractère).
    Filtres utiles :
      file:  folder:                     uniquement fichiers / dossiers
      ext:pdf;docx;xlsx                  extensions (séparées par ;)
      path:"D:\\Projets"  ou  "D:\\Projets\\"  limiter à un dossier (sous-dossiers inclus)
      parent:"C:\\Docs"                  dossier exact, sans sous-dossiers
      size:>50mb   size:1mb..10mb   size:huge (16-128 Mo)  size:gigantic (>128 Mo)  size:empty
      dm:today  dm:yesterday  dm:thisweek  dm:lastmonth  dm:last2weeks  dm:2025  dm:2025-03-01..2025-03-31
      dc: (création), da: (accès) — même syntaxe que dm:
      dupe:  sizedupe:                   doublons par nom / par taille
      empty:                             dossiers vides
      startwith:  endwith:  wholeword:  case:  nodiacritics:
      width:>1920  height:  dimensions:1920x1080  orientation:portrait   (images)
      content:"texte"                    recherche DANS les fichiers — très lent, à combiner
                                         avec path: et ext: pour restreindre fortement
      childcount:  childfilecount:       nombre d'éléments dans un dossier
    Exemples :
      "les PDF du chantier Martin modifiés cette semaine" -> ext:pdf *martin* dm:thisweek
      "les gros fichiers vidéo sur D:"                    -> "D:\\" ext:mp4;mov;mkv;avi size:>500mb
      "les plans DWG qui contiennent 'R+2'"              -> ext:dwg *R+2*
      "dossiers vides dans Documents"                    -> folder: empty: path:"C:\\Users"

    Paramètres :
      query        requête Everything
      max_results  nombre de résultats (défaut 50, plafonné)
      offset       décalage pour paginer
      sort         name | path | size | extension | date-modified | date-created
      descending   tri décroissant (défaut True : plus récent / plus gros d'abord)
      match_path   faire porter les termes sur le chemin complet, pas seulement le nom
      regex        interpréter la requête comme une expression régulière

    Renvoie du JSON : liste de {path, size (octets), modified}. Si 0 résultat, essayer une
    requête moins restrictive (moins de termes, jokers *, match_path) avant de conclure.
    Pour afficher la même requête dans la fenêtre d'Everything, appeler everything_show.
    """
    max_results = max(1, min(int(max_results), HARD_LIMIT))
    offset = max(0, int(offset))
    if sort not in SORTS:
        sort = "date-modified"

    total = None
    try:
        if BACKEND == "http":
            results, total = _search_http(query, max_results, offset, sort, descending, match_path, regex)
        else:
            results = _search_es(query, max_results, offset, sort, descending, match_path, regex)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "query": query}, ensure_ascii=False)

    out = {"query": query, "returned": len(results), "offset": offset, "results": results}
    if total is not None:
        out["total"] = total
    if len(results) == max_results:
        out["note"] = "Résultats tronqués : utiliser offset pour la suite ou affiner la requête."
    return json.dumps(out, ensure_ascii=False, indent=1)


GUI_SORTS = {
    "name": "Name", "path": "Path", "size": "Size", "extension": "Extension",
    "date-modified": "Date Modified", "date-created": "Date Created",
}


@mcp.tool()
def everything_show(
    query: str,
    sort: str = "date-modified",
    descending: bool = True,
    match_path: bool = False,
    regex: bool = False,
    select: str = "",
    new_window: bool = False,
) -> str:
    """Affiche une recherche dans la fenêtre d'Everything sur le PC de l'utilisateur.

    À utiliser quand l'utilisateur veut voir ou manipuler les résultats dans l'interface
    d'Everything (« montre-moi », « ouvre dans Everything », « affiche-les »), ou en
    complément d'everything_search pour qu'il puisse trier, prévisualiser et ouvrir les
    fichiers lui-même. Même syntaxe de requête qu'everything_search.

    Paramètres :
      query       requête Everything (syntaxe anglaise)
      sort        name | path | size | extension | date-modified | date-created
      descending  tri décroissant
      match_path  faire porter les termes sur le chemin complet
      regex       requête en expression régulière
      select      chemin complet d'un fichier à sélectionner dans les résultats (optionnel)
      new_window  ouvrir une nouvelle fenêtre plutôt que réutiliser celle déjà ouverte
    """
    args = [EVERYTHING_EXE]
    if INSTANCE:
        args += ["-instance", INSTANCE]
    args.append("-newwindow" if new_window else "-nonewwindow")
    args += ["-matchpath" if match_path else "-nomatchpath"]
    args += ["-regex" if regex else "-noregex"]
    args += ["-sort", GUI_SORTS.get(sort, "Date Modified")]
    args.append("-sort-descending" if descending else "-sort-ascending")
    args += ["-s", query]
    if select:
        args += ["-select", select]

    try:
        subprocess.Popen(args, close_fds=True)
    except FileNotFoundError:
        return json.dumps({"error": f"Everything.exe introuvable : {EVERYTHING_EXE}. "
                                    "Renseignez EVERYTHING_EXE."}, ensure_ascii=False)
    except OSError as e:
        return json.dumps({"error": f"Impossible de lancer Everything : {e}"}, ensure_ascii=False)

    return json.dumps({"shown": True, "query": query}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
