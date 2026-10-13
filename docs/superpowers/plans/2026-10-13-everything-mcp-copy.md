# Serveur MCP Everything (recherche, contenu, dossiers, copie) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Étendre le serveur MCP Python existant pour piloter Everything depuis n'importe quel projet Claude Code : recherche, recherche dans le contenu de tout format, résumé de dossier, copie de fichiers et dossiers — sans jamais déplacer, renommer, supprimer ni écraser.

**Architecture:** Serveur FastMCP (`server.py`) qui ne fait que déclarer les outils et sérialiser en JSON ; la logique vit dans des modules à responsabilité unique (`everything_backend`, `extractors`, `ifilter`, `content_search`, `folder_info`, `copier`, `config`). Enregistré au niveau utilisateur dans Claude Code, accompagné d'un skill `/everything` qui guide Claude (aperçu + confirmation avant copie).

**Tech Stack:** Python 3.14 (venv `.venv`), SDK MCP 2.3 (`mcp.server.mcpserver.MCPServer`, repli v1 `FastMCP`), es.exe 1.1.0.38 / Everything 1.4.1, xlrd, openpyxl, pypdf[crypto], comtypes, pytest, xlwt (tests).

**Spec :** `docs/superpowers/specs/2026-10-13-everything-mcp-copy-design.md`

## Global Constraints

- **Aucun module serveur (`*.py` à la racine) n'appelle** `os.remove/unlink/rmdir/removedirs/rename/renames/replace/truncate/open`, `shutil.move/rmtree/copytree/copy/copy2/copyfile`, n'importe `pathlib` ni `send2trash`, ni n'appelle `open()` avec un mode contenant `w` ou `+`. Vérifié par `tests/test_guardrails.py` (tâche 10).
- Fichiers créés uniquement en mode exclusif `"xb"` / `"x"` ; manifeste en ajout `"a"` uniquement s'il porte notre en-tête.
- Suffixes de collision : `nom (2).ext`, `nom (3).ext`… ; dossiers : `Nom (2)`.
- Plafonds par défaut : `EVERYTHING_COPY_MAX_FILES`=500, `EVERYTHING_COPY_MAX_BYTES`=2147483648, `EVERYTHING_CONTENT_TIMEOUT`=300, `EVERYTHING_FOLDER_MAX_ITEMS`=500000, `EVERYTHING_MAX_RESULTS`=500 ; IFilter 30 s par fichier ; texte extrait ≤ 50 Mio caractères ; recherche brute ≤ 200 Mio octets.
- Attributs « en ligne uniquement » : `0x1000 | 0x400000 | 0x40000` (constaté : OneDrive pose 0x400000, pas `O`).
- **es.exe** : la requête est ajoutée **brute** à la ligne de commande (passée comme un seul argument, es.exe la traite comme une expression exacte → 0 résultat — bug du serveur actuel). Tout mot commençant par `-` ou `/` hors guillemets est entouré de `< >` (sinon es.exe le lit comme option, ex. `-export-csv` qui écrit un fichier).
- Manifeste : `manifest.csv`, UTF-8 avec BOM, séparateur `;`, en-tête `date_copie;source;copie;taille`.
- Messages et docstrings en français ; syntaxe Everything en anglais ; dates ISO `AAAA-MM-JJ`.
- Commandes à lancer depuis `C:\Users\pmaubert\dev\everything_mcp` (PowerShell). Python : `.\.venv\Scripts\python.exe`.
- Chaque message de commit se termine par la ligne `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Structure des fichiers

| Fichier | Rôle |
|---|---|
| `config.py` (créé) | Variables d'environnement, détection de es.exe / Everything.exe, plafonds |
| `everything_backend.py` (créé) | `Entry`, `EverythingError`, `search()` via es.exe ou HTTP, construction de la ligne de commande |
| `ifilter.py` (créé) | `has_filter()`, `extract_text()` (processus fils avec délai), code COM IFilter |
| `extractors.py` (créé) | Lecteurs natifs, recherche brute, `match_file()` (3 niveaux) |
| `content_search.py` (créé) | `find_content()` : candidats Everything → filtrage cloud → `match_file` |
| `folder_info.py` (créé) | `folder_info()` : agrégats d'un dossier depuis l'index |
| `copier.py` (créé) | `plan_copy()`, `execute()`, `copy_items()` : copie sûre + manifeste |
| `server.py` (réécrit) | Déclaration des 5 outils MCP |
| `requirements.txt`, `requirements-dev.txt`, `pytest.ini` (créés) | Dépendances, configuration pytest |
| `tests/helpers.py` + `tests/test_*.py` (créés) | Tests |
| `README.md` (réécrit) | Installation Claude Code |
| `~/.claude/skills/everything/SKILL.md` (créé, hors dépôt) + copie `skill/SKILL.md` dans le dépôt | Skill `/everything` |

---

### Task 1: Socle — dépendances, pytest, configuration

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `config.py`, `tests/test_config.py`

**Interfaces:**
- Produces: module `config` avec `first_existing(candidates) -> str`, `env_int(name, default) -> int` et les constantes `ES_PATH, EVERYTHING_EXE, BACKEND, HTTP_URL, INSTANCE, MAX_RESULTS, COPY_MAX_FILES, COPY_MAX_BYTES, CONTENT_TIMEOUT, FOLDER_MAX_ITEMS, IFILTER_TIMEOUT, TEXT_LIMIT, RAW_LIMIT`.

- [ ] **Step 1: Écrire les fichiers de dépendances et pytest.ini**

`requirements.txt` :
```
mcp>=1.10
xlrd>=2.0
openpyxl>=3.1
pypdf[crypto]>=5.0
comtypes>=1.4
```

`requirements-dev.txt` :
```
-r requirements.txt
pytest>=8
xlwt>=1.3
```

`pytest.ini` :
```ini
[pytest]
testpaths = tests
pythonpath = .
markers =
    integration: tests sur le vrai Everything et de vrais fichiers (lancer avec -m integration)
addopts = -m "not integration"
```

- [ ] **Step 2: Installer**

Run: `if (-not (Test-Path .venv)) { python -m venv .venv }; .\.venv\Scripts\python.exe -m pip install -q -r requirements-dev.txt`
Expected: aucune erreur.

- [ ] **Step 3: Écrire le test qui échoue** — `tests/test_config.py`

```python
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
```

- [ ] **Step 4: Lancer le test pour vérifier l'échec**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 5: Implémenter** — `config.py`

```python
"""Configuration du serveur, lue dans les variables d'environnement."""

import os

ES_CANDIDATES = (
    r"C:\Program Files\Everything\es.exe",
    r"C:\Program Files (x86)\Everything\es.exe",
)
EVERYTHING_EXE_CANDIDATES = (
    r"C:\Program Files\Everything\Everything.exe",
    r"C:\Program Files (x86)\Everything\Everything.exe",
)


def first_existing(candidates):
    """Premier chemin existant de la liste, sinon le premier (pour un message d'erreur clair)."""
    for path in candidates:
        if os.path.isfile(path):
            return path
    return candidates[0]


def env_int(name, default):
    try:
        return int(os.environ.get(name, ""))
    except ValueError:
        return default


ES_PATH = os.environ.get("ES_PATH") or first_existing(ES_CANDIDATES)
EVERYTHING_EXE = os.environ.get("EVERYTHING_EXE") or first_existing(EVERYTHING_EXE_CANDIDATES)
BACKEND = os.environ.get("EVERYTHING_BACKEND", "es").lower()
HTTP_URL = os.environ.get("EVERYTHING_HTTP_URL", "http://127.0.0.1:8080").rstrip("/")
INSTANCE = os.environ.get("EVERYTHING_INSTANCE", "")  # ex. "1.5a" pour Everything 1.5 alpha

MAX_RESULTS = env_int("EVERYTHING_MAX_RESULTS", 500)
COPY_MAX_FILES = env_int("EVERYTHING_COPY_MAX_FILES", 500)
COPY_MAX_BYTES = env_int("EVERYTHING_COPY_MAX_BYTES", 2 * 1024**3)
CONTENT_TIMEOUT = env_int("EVERYTHING_CONTENT_TIMEOUT", 300)
FOLDER_MAX_ITEMS = env_int("EVERYTHING_FOLDER_MAX_ITEMS", 500_000)

IFILTER_TIMEOUT = 30                # secondes par fichier
TEXT_LIMIT = 50 * 1024 * 1024       # caractères extraits au plus par fichier
RAW_LIMIT = 200 * 1024 * 1024       # octets lus au plus en recherche brute
```

- [ ] **Step 6: Lancer le test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```powershell
git add requirements.txt requirements-dev.txt pytest.ini config.py tests/test_config.py
git commit -m @'
feat: configuration, dépendances et socle de tests

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 2: Backend Everything (es.exe / HTTP)

**Files:**
- Create: `everything_backend.py`, `tests/test_backend.py`

**Interfaces:**
- Consumes: `config.ES_PATH, config.INSTANCE, config.BACKEND, config.HTTP_URL`.
- Produces:
  - `class EverythingError(RuntimeError)`
  - `@dataclass Entry(path: str, size: int | None, modified: str | None, attributes: int | None, is_dir: bool)` avec `to_dict() -> dict` (`{"path","size","modified"}` + `"type": "folder"` si dossier)
  - `neutralize_options(query: str) -> str`
  - `es_command_line(query, max_results, offset=0, sort="date-modified", descending=True, match_path=False, regex=False) -> str`
  - `parse_es_csv(text: str) -> list[Entry]`
  - `search(query, max_results=50, offset=0, sort="date-modified", descending=True, match_path=False, regex=False) -> list[Entry]` (lève `EverythingError`)
  - `SORTS = ("name", "path", "size", "extension", "date-modified", "date-created")`

- [ ] **Step 1: Écrire les tests qui échouent** — `tests/test_backend.py`

```python
import pytest

import config
import everything_backend as eb


@pytest.fixture(autouse=True)
def es_path(monkeypatch):
    monkeypatch.setattr(config, "ES_PATH", r"C:\Program Files (x86)\Everything\es.exe")
    monkeypatch.setattr(config, "INSTANCE", "")


def test_command_line_appends_raw_query():
    cmd = eb.es_command_line('ext:msg "C:\\A B\\" dm:>=2020-01-01', 10)
    assert cmd.startswith('"C:\\Program Files (x86)\\Everything\\es.exe" -csv -size -dm -attributes')
    assert "-n 10 -o 0 -sort date-modified -sort-descending" in cmd
    assert cmd.endswith(' ext:msg "C:\\A B\\" dm:>=2020-01-01')


def test_command_line_options():
    cmd = eb.es_command_line("x", 5, offset=20, sort="bogus", descending=False, match_path=True, regex=True)
    assert "-o 20 -sort date-modified -sort-ascending -p -r x" in cmd


def test_command_line_instance(monkeypatch):
    monkeypatch.setattr(config, "INSTANCE", "1.5a")
    assert "-instance 1.5a -csv" in eb.es_command_line("x", 5)


def test_option_like_terms_are_neutralized():
    assert eb.neutralize_options("-export-csv out.csv /n 5 ext:md") == "<-export-csv> out.csv </n> 5 ext:md"


def test_quoted_terms_and_newlines_preserved():
    assert eb.neutralize_options('ext:md\n"C:\\A -B\\"  !x') == 'ext:md "C:\\A -B\\" !x'


def test_parse_es_csv():
    text = (
        "Filename,Size,Date Modified,Attributes\r\n"
        '"C:\\Docs\\Plans\\",0,2026-10-13T17:42:28,16\r\n'
        '"C:\\Docs\\a.xls",37376,2007-10-05T18:31:06,5242912\r\n'
        '"C:\\",0,2026-01-01T00:00:00,22\r\n'
    )
    entries = eb.parse_es_csv(text)
    assert entries[0] == eb.Entry("C:\\Docs\\Plans", 0, "2026-10-13T17:42:28", 16, True)
    assert entries[1] == eb.Entry("C:\\Docs\\a.xls", 37376, "2007-10-05T18:31:06", 5242912, False)
    assert entries[2].path == "C:\\" and entries[2].is_dir


def test_parse_empty_output():
    assert eb.parse_es_csv("") == []


def test_entry_to_dict():
    assert eb.Entry("C:\\a", 1, None, 32, False).to_dict() == {"path": "C:\\a", "size": 1, "modified": None}
    assert eb.Entry("C:\\d", 0, None, 16, True).to_dict()["type"] == "folder"


def test_missing_es_raises(monkeypatch):
    monkeypatch.setattr(config, "BACKEND", "es")
    monkeypatch.setattr(config, "ES_PATH", r"C:\nulle-part\es.exe")
    with pytest.raises(eb.EverythingError, match="introuvable"):
        eb.search("x")
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_backend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'everything_backend'`

- [ ] **Step 3: Implémenter** — `everything_backend.py`

```python
"""Exécution des requêtes Everything, via es.exe (défaut) ou le serveur HTTP d'Everything."""

import csv
import io
import json
import subprocess
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
                    match_path=False, regex=False):
    """Ligne de commande es.exe. La requête est ajoutée brute : passée comme un seul
    argument, es.exe la traiterait comme une expression exacte."""
    args = [config.ES_PATH]
    if config.INSTANCE:
        args += ["-instance", config.INSTANCE]
    args += [
        "-csv", "-size", "-dm", "-attributes",
        "-size-format", "1",   # tailles en octets
        "-date-format", "1",   # dates ISO-8601
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
    cmd = es_command_line(query, max_results, offset, sort, descending, match_path, regex)
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
    return parse_es_csv(_decode(proc.stdout))


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
        raise EverythingError(f"Serveur HTTP Everything injoignable ({config.HTTP_URL}) : {e}")

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
```

- [ ] **Step 4: Lancer les tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_backend.py -v`
Expected: 9 passed

- [ ] **Step 5: Vérification manuelle contre le vrai Everything**

Run: `.\.venv\Scripts\python.exe -c "import everything_backend as eb; r = eb.search('ext:md \"C:\\Users\\pmaubert\\dev\\everything_mcp\\docs\\\"'); print(len(r), r[0])"`
Expected: au moins 2 résultats, un `Entry(path='C:\\Users\\pmaubert\\dev\\everything_mcp\\docs\\...md', ...)`.

- [ ] **Step 6: Commit**

```powershell
git add everything_backend.py tests/test_backend.py
git commit -m @'
feat: backend Everything (requête brute, neutralisation des options es.exe, attributs)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 3: Lecteurs natifs de contenu

**Files:**
- Create: `extractors.py` (première partie), `tests/helpers.py`, `tests/test_extractors_native.py`

**Interfaces:**
- Consumes: `config.TEXT_LIMIT`.
- Produces:
  - `OLE_MAGIC: bytes`, `class ProtectedFile(Exception)`
  - `normalize(text: str, case_sensitive: bool) -> str`
  - `xml_to_text(xml: str) -> str`
  - `native_text(path: str) -> str | None` (None = pas de lecteur natif pour l'extension ; lève `ProtectedFile` ou toute autre exception de lecture)
  - `tests/helpers.py` : `make_zip(path, members: dict[str, str]) -> str`, `make_pdf(path, text: str) -> None`

- [ ] **Step 1: Écrire les helpers de test** — `tests/helpers.py`

```python
import zipfile


def make_zip(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, content in members.items():
            z.writestr(name, content)
    return str(path)


def make_pdf(path, text):
    """PDF minimal d'une page contenant `text` (Helvetica), lisible par pypdf."""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    with open(path, "wb") as f:
        f.write(out)
```

- [ ] **Step 2: Écrire les tests qui échouent** — `tests/test_extractors_native.py`

```python
import openpyxl
import pytest
import xlwt

import extractors
from helpers import make_pdf, make_zip


def test_normalize_casefold_and_nfc():
    assert extractors.normalize("E\u0301COLE", False) == "école"
    assert extractors.normalize("ÉCOLE", True) == "ÉCOLE"


def test_xlsx_cells(tmp_path):
    p = tmp_path / "a.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"], ws["B1"], ws["A2"] = "Prix XYZ", 12.0, "autre"
    wb.save(p)
    text = extractors.native_text(str(p))
    assert "Prix XYZ\t12" in text and "autre" in text


def test_xls_cells(tmp_path):
    p = tmp_path / "a.xls"
    wb = xlwt.Workbook()
    ws = wb.add_sheet("S1")
    ws.write(0, 0, "Lot XYZ")
    ws.write(0, 1, 3.0)
    wb.save(str(p))
    assert "Lot XYZ\t3" in extractors.native_text(str(p))


def test_docx_runs_joined_and_paragraphs_split(tmp_path):
    xml = ('<w:document><w:body><w:p><w:r><w:t>Expression X</w:t></w:r><w:r><w:t>YZ ici</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Suite</w:t></w:r></w:p></w:body></w:document>')
    p = make_zip(tmp_path / "a.docx", {"word/document.xml": xml, "[Content_Types].xml": "<x/>"})
    text = extractors.native_text(p)
    assert "Expression XYZ ici" in text and "ici\nSuite" in text


def test_pptx_slides(tmp_path):
    p = make_zip(tmp_path / "a.pptx", {"ppt/slides/slide1.xml": "<p:sld><a:p><a:r><a:t>Diapo XYZ</a:t></a:r></a:p></p:sld>"})
    assert "Diapo XYZ" in extractors.native_text(p)


def test_odt_content(tmp_path):
    p = make_zip(tmp_path / "a.odt", {"content.xml": "<office:text><text:p>Texte<text:s/>XYZ &amp; co</text:p></office:text>"})
    assert "Texte XYZ & co" in extractors.native_text(p)


def test_pdf_text(tmp_path):
    p = tmp_path / "a.pdf"
    make_pdf(p, "Bonjour XYZ")
    assert "Bonjour XYZ" in extractors.native_text(str(p))


@pytest.mark.parametrize("data", [
    "Café XYZ".encode("utf-8"),
    "Café XYZ".encode("cp1252"),
    b"\xff\xfe" + "Café XYZ".encode("utf-16-le"),
    b"\xef\xbb\xbf" + "Café XYZ".encode("utf-8"),
])
def test_text_encodings(tmp_path, data):
    p = tmp_path / "a.txt"
    p.write_bytes(data)
    assert extractors.native_text(str(p)) == "Café XYZ"


def test_unknown_extension_returns_none(tmp_path):
    p = tmp_path / "a.zzz"
    p.write_bytes(b"XYZ")
    assert extractors.native_text(str(p)) is None


def test_encrypted_ooxml_is_protected(tmp_path):
    p = tmp_path / "a.xlsx"
    p.write_bytes(extractors.OLE_MAGIC + b"\x00" * 600)
    with pytest.raises(extractors.ProtectedFile):
        extractors.native_text(str(p))
```

- [ ] **Step 3: Lancer pour vérifier l'échec**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extractors_native.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'extractors'`

- [ ] **Step 4: Implémenter** — `extractors.py` (cette tâche n'en écrit que la première partie ; la tâche 5 ajoute la suite à la fin du fichier)

```python
"""Lecture du contenu des fichiers et recherche d'une expression exacte.

Trois niveaux, essayés dans l'ordre :
  1. lecteurs Python natifs (Excel, Word, PowerPoint, OpenDocument, PDF, texte) ;
  2. IFilters Windows (tout format ayant un filtre installé : .doc, .msg, .rtf…) ;
  3. recherche brute dans les octets (UTF-8, UTF-16LE, cp1252, membres d'archives zip).
"""

import html
import logging
import os
import re
import unicodedata
import zipfile

import openpyxl
import xlrd
from pypdf import PdfReader

import config

logging.getLogger("pypdf").setLevel(logging.ERROR)

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
OOXML_EXTS = {".xlsx", ".xlsm", ".docx", ".docm", ".pptx", ".pptm"}
TEXT_EXTS = {
    ".txt", ".csv", ".tsv", ".md", ".json", ".xml", ".html", ".htm", ".log", ".ini", ".cfg",
    ".conf", ".yaml", ".yml", ".py", ".js", ".ts", ".sql", ".bat", ".ps1", ".css", ".tex",
}
_WORD_PARTS = r"word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml"
_PPT_PARTS = r"ppt/(slides/slide\d+|notesSlides/notesSlide\d+)\.xml"
ZIP_XML_PARTS = {
    ".docx": _WORD_PARTS, ".docm": _WORD_PARTS,
    ".pptx": _PPT_PARTS, ".pptm": _PPT_PARTS,
    ".odt": r"content\.xml", ".ods": r"content\.xml", ".odp": r"content\.xml",
}

_BREAKS = re.compile(r"</(?:w:p|a:p|text:p|text:h)>|<(?:w:br|w:cr|text:line-break)\b[^>]*/>")
_TABS = re.compile(r"<(?:w:tab|text:tab)\b[^>]*/>")
_SPACES = re.compile(r"<text:s\b[^>]*/>")
_TAGS = re.compile(r"<[^>]+>")


class ProtectedFile(Exception):
    """Fichier chiffré ou protégé par mot de passe : contenu illisible."""


def normalize(text, case_sensitive):
    text = unicodedata.normalize("NFC", text)
    return text if case_sensitive else text.casefold()


def xml_to_text(xml):
    """Texte d'une partie XML Office/OpenDocument : un saut de ligne par paragraphe."""
    xml = _BREAKS.sub("\n", xml)
    xml = _TABS.sub("\t", xml)
    xml = _SPACES.sub(" ", xml)
    return html.unescape(_TAGS.sub("", xml))


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _is_ole(path):
    with open(path, "rb") as f:
        return f.read(8) == OLE_MAGIC


def _read_xls(path):
    try:
        book = xlrd.open_workbook(path, on_demand=True)
    except xlrd.biffh.XLRDError as e:
        if "encrypt" in str(e).lower():
            raise ProtectedFile(str(e))
        raise
    try:
        lines = []
        for sheet in book.sheets():
            for r in range(sheet.nrows):
                lines.append("\t".join(_cell_text(v) for v in sheet.row_values(r)))
        return "\n".join(lines)
    finally:
        book.release_resources()


def _read_xlsx(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        lines = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                lines.append("\t".join(_cell_text(v) for v in row))
        return "\n".join(lines)
    finally:
        wb.close()


def _read_zip_xml(path, pattern):
    rx = re.compile(pattern)
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if rx.fullmatch(n))
        return "\n".join(xml_to_text(z.read(n).decode("utf-8", "replace")) for n in names)


def _read_pdf(path):
    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception as e:
            raise ProtectedFile(f"PDF chiffré : {e}")
        if not unlocked:
            raise ProtectedFile("PDF protégé par mot de passe")
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _read_text(path):
    with open(path, "rb") as f:
        data = f.read(config.TEXT_LIMIT)
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        if len(data) == config.TEXT_LIMIT and e.start >= len(data) - 3:
            return data.decode("utf-8", errors="ignore")  # caractère coupé par la limite
        return data.decode("cp1252", errors="replace")


def native_text(path):
    """Texte du fichier par un lecteur Python, ou None si l'extension n'en a pas."""
    ext = os.path.splitext(path)[1].lower()
    if ext in OOXML_EXTS and _is_ole(path):
        raise ProtectedFile("document Office chiffré (protégé par mot de passe)")
    if ext == ".xls":
        return _read_xls(path)
    if ext in (".xlsx", ".xlsm"):
        return _read_xlsx(path)
    if ext in ZIP_XML_PARTS:
        return _read_zip_xml(path, ZIP_XML_PARTS[ext])
    if ext == ".pdf":
        return _read_pdf(path)
    if ext in TEXT_EXTS:
        return _read_text(path)
    return None
```

- [ ] **Step 5: Lancer les tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extractors_native.py -v`
Expected: 13 passed

- [ ] **Step 6: Commit**

```powershell
git add extractors.py tests/helpers.py tests/test_extractors_native.py
git commit -m @'
feat: lecteurs natifs (xls, xlsx, docx, pptx, odf, pdf, texte)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 4: IFilters Windows

**Files:**
- Create: `ifilter.py`, `tests/test_ifilter.py`

**Interfaces:**
- Consumes: `config.TEXT_LIMIT`.
- Produces: `class IFilterError(Exception)`, `has_filter(ext: str) -> bool`, `child_command(path: str) -> list[str]`, `extract_text(path: str, timeout: float) -> str` (lève `IFilterError`).

- [ ] **Step 1: Écrire les tests qui échouent** — `tests/test_ifilter.py`

```python
import sys

import pytest

import ifilter


def test_has_filter_unknown_extension():
    assert not ifilter.has_filter(".zzzinconnu")
    assert not ifilter.has_filter("")


@pytest.mark.skipif(not ifilter.has_filter(".rtf"), reason="pas d'IFilter .rtf sur ce poste")
def test_rtf_via_ifilter(tmp_path):
    p = tmp_path / "a.rtf"
    p.write_bytes(b"{\\rtf1\\ansi Bonjour IFilter XYZ\\par}")
    assert "Bonjour IFilter XYZ" in ifilter.extract_text(str(p), timeout=60)


def test_timeout_kills_child(monkeypatch):
    monkeypatch.setattr(ifilter, "child_command",
                        lambda path: [sys.executable, "-c", "import time; time.sleep(30)"])
    with pytest.raises(ifilter.IFilterError, match="délai"):
        ifilter.extract_text("x", timeout=1)


def test_child_error_is_reported(monkeypatch):
    monkeypatch.setattr(ifilter, "child_command",
                        lambda path: [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(2)"])
    with pytest.raises(ifilter.IFilterError, match="boom"):
        ifilter.extract_text("x", timeout=30)
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ifilter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ifilter'`

- [ ] **Step 3: Implémenter** — `ifilter.py`

```python
"""Lecture du texte d'un fichier via les IFilters Windows (ceux de Windows Search).

Chaque lecture s'exécute dans un processus Python séparé, avec délai : un filtre
défaillant ou bloqué ne peut pas faire tomber le serveur. Ce fichier sert aussi de
script pour ce processus fils (`python ifilter.py <chemin>`).
"""

import os
import subprocess
import sys
import winreg

FILTER_E_END_OF_CHUNKS = 0x80041700
FILTER_E_NO_MORE_TEXT = 0x80041701
FILTER_S_LAST_TEXT = 0x00041709
# Blocs sans texte, pièce jointe ou lien illisible (.msg…) : on passe au bloc suivant.
SKIPPABLE_CHUNK_ERRORS = {0x80041705, 0x80041706, 0x80041707, 0x80041708}
CHUNK_TEXT = 1
MAX_CHUNKS = 1_000_000


class IFilterError(Exception):
    pass


def has_filter(ext):
    """Vrai si un IFilter est enregistré pour cette extension (ex. ".doc")."""
    if not ext:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ext + r"\PersistentHandler"):
            return True
    except OSError:
        return False


def child_command(path):
    return [sys.executable, os.path.abspath(__file__), path]


def extract_text(path, timeout):
    """Texte du fichier lu par son IFilter, dans un processus fils limité à `timeout` s."""
    try:
        proc = subprocess.run(
            child_command(path), capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        raise IFilterError(f"délai de {timeout} s dépassé")
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", "replace").strip()
        raise IFilterError(message or f"code de sortie {proc.returncode}")
    return proc.stdout.decode("utf-8", "replace")


def _read_with_ifilter(path, limit):
    import ctypes
    from ctypes import POINTER, byref, c_int, c_ulong, wintypes

    import comtypes
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

    class PROPSPEC_U(ctypes.Union):
        _fields_ = [("propid", c_ulong), ("lpwstr", wintypes.LPWSTR)]

    class PROPSPEC(ctypes.Structure):
        _fields_ = [("ulKind", c_ulong), ("u", PROPSPEC_U)]

    class FULLPROPSPEC(ctypes.Structure):
        _fields_ = [("guidPropSet", GUID), ("psProperty", PROPSPEC)]

    class STAT_CHUNK(ctypes.Structure):
        _fields_ = [
            ("idChunk", c_ulong), ("breakType", c_int), ("flags", c_int), ("locale", c_ulong),
            ("attribute", FULLPROPSPEC), ("idChunkSource", c_ulong),
            ("cwcStartSource", c_ulong), ("cwcLenSource", c_ulong),
        ]

    class IFilter(IUnknown):
        _iid_ = GUID("{89BCB740-6119-101A-BCB7-00DD010655AF}")
        _methods_ = [
            COMMETHOD([], HRESULT, "Init",
                      (["in"], c_ulong, "grfFlags"), (["in"], c_ulong, "cAttributes"),
                      (["in"], POINTER(FULLPROPSPEC), "aAttributes"), (["out"], POINTER(c_ulong), "pFlags")),
            COMMETHOD([], HRESULT, "GetChunk", (["in"], POINTER(STAT_CHUNK), "pStat")),
            COMMETHOD([], HRESULT, "GetText",
                      (["in"], POINTER(c_ulong), "pcwcBuffer"), (["in"], ctypes.c_wchar_p, "awcBuffer")),
            COMMETHOD([], HRESULT, "GetValue", (["in"], POINTER(ctypes.c_void_p), "ppPropValue")),
            COMMETHOD([], HRESULT, "BindRegion",
                      (["in"], ctypes.c_byte * 12, "origPos"), (["in"], POINTER(GUID), "riid"),
                      (["in"], POINTER(ctypes.c_void_p), "ppunk")),
        ]

    load = ctypes.oledll.query.LoadIFilter
    load.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, POINTER(POINTER(IUnknown))]
    unknown = POINTER(IUnknown)()
    load(path, None, byref(unknown))
    flt = unknown.QueryInterface(IFilter)
    # CANON_PARAGRAPHS | HARD_LINE_BREAKS | CANON_SPACES | APPLY_INDEX_ATTRIBUTES
    flt.Init(1 | 2 | 8 | 16, 0, None)

    parts, size = [], 0
    stat = STAT_CHUNK()
    buf = ctypes.create_unicode_buffer(8192)
    for _ in range(MAX_CHUNKS):
        try:
            flt.GetChunk(byref(stat))
        except comtypes.COMError as e:
            code = e.hresult & 0xFFFFFFFF
            if code == FILTER_E_END_OF_CHUNKS:
                break
            if code in SKIPPABLE_CHUNK_ERRORS:
                continue
            raise
        if not stat.flags & CHUNK_TEXT:
            continue
        while True:
            n = c_ulong(len(buf) - 1)
            try:
                hr = flt.GetText(byref(n), buf)
            except comtypes.COMError as e:
                if (e.hresult & 0xFFFFFFFF) == FILTER_E_NO_MORE_TEXT:
                    break
                raise
            parts.append(buf[: n.value])
            size += n.value
            if size >= limit:
                return "".join(parts)[:limit]
            if hr == FILTER_S_LAST_TEXT:
                break
        parts.append("\n")
    return "".join(parts)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import config

    try:
        text = _read_with_ifilter(sys.argv[1], config.TEXT_LIMIT)
    except Exception as e:  # tout échec du filtre est rapporté au processus parent
        sys.stderr.write(f"{type(e).__name__}: {e}")
        sys.exit(2)
    sys.stdout.buffer.write(text.encode("utf-8"))
```

- [ ] **Step 4: Lancer les tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ifilter.py -v`
Expected: 4 passed (le test `.rtf` est « skipped » si aucun IFilter `.rtf` — constaté présent sur le poste cible).

- [ ] **Step 5: Commit**

```powershell
git add ifilter.py tests/test_ifilter.py
git commit -m @'
feat: lecture via IFilters Windows dans un processus fils avec délai

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 5: Recherche brute et orchestration des 3 niveaux

**Files:**
- Modify: `extractors.py` (ajout en fin de fichier + `import ifilter` et `from dataclasses import dataclass` en tête)
- Create: `tests/test_extractors_match.py`

**Interfaces:**
- Consumes: `ifilter.has_filter`, `ifilter.extract_text`, `ifilter.IFilterError`, `config.RAW_LIMIT`, `config.IFILTER_TIMEOUT`, `config.TEXT_LIMIT`, `native_text`, `normalize`, `xml_to_text`, `ProtectedFile` (tâche 3).
- Produces:
  - `@dataclass MatchResult(matched: bool | None, method: str | None, reason: str | None = None)` — `matched=None` = non vérifié ; `method` ∈ `"native" | "ifilter" | "raw"`.
  - `raw_contains(path: str, phrase: str, case_sensitive: bool) -> bool`
  - `match_file(path: str, phrase: str, case_sensitive: bool = False, allow_raw: bool = True) -> MatchResult`

- [ ] **Step 1: Écrire les tests qui échouent** — `tests/test_extractors_match.py`

```python
import pytest

import extractors
import ifilter
from helpers import make_zip


@pytest.fixture
def no_ifilter(monkeypatch):
    monkeypatch.setattr(ifilter, "has_filter", lambda ext: False)


def test_native_match_ignores_case(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("le code xyz est là", encoding="utf-8")
    r = extractors.match_file(str(p), "XYZ")
    assert (r.matched, r.method) == (True, "native")


def test_native_case_sensitive(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("le code xyz", encoding="utf-8")
    assert extractors.match_file(str(p), "XYZ", case_sensitive=True).matched is False


def test_exact_phrase_requires_same_spacing(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("prix  unitaire", encoding="utf-8")
    assert extractors.match_file(str(p), "prix unitaire").matched is False


def test_ifilter_used_when_no_native_reader(tmp_path, monkeypatch):
    p = tmp_path / "a.doc"
    p.write_bytes(b"\x00binaire")
    monkeypatch.setattr(ifilter, "has_filter", lambda ext: ext == ".doc")
    monkeypatch.setattr(ifilter, "extract_text", lambda path, timeout: "Contrat XYZ signé")
    r = extractors.match_file(str(p), "xyz")
    assert (r.matched, r.method) == (True, "ifilter")


def test_ifilter_failure_falls_back_to_raw(tmp_path, monkeypatch):
    p = tmp_path / "a.dwg"
    p.write_bytes(b"\x00\x01" + "Plan XYZ".encode("utf-16-le") + b"\x00")
    monkeypatch.setattr(ifilter, "has_filter", lambda ext: True)

    def fail(path, timeout):
        raise ifilter.IFilterError("E_FAIL")

    monkeypatch.setattr(ifilter, "extract_text", fail)
    r = extractors.match_file(str(p), "plan xyz")
    assert (r.matched, r.method) == (True, "raw")


def test_empty_ifilter_text_falls_back_to_raw(tmp_path, monkeypatch):
    p = tmp_path / "a.dwg"
    p.write_bytes(b"\x00XYZ\x00")
    monkeypatch.setattr(ifilter, "has_filter", lambda ext: True)
    monkeypatch.setattr(ifilter, "extract_text", lambda path, timeout: "  ")
    assert extractors.match_file(str(p), "XYZ").method == "raw"


def test_raw_utf16_at_odd_offset(tmp_path, no_ifilter):
    p = tmp_path / "a.bin"
    p.write_bytes(b"\x07" + "Réf XYZ".encode("utf-16-le"))
    r = extractors.match_file(str(p), "réf xyz")
    assert (r.matched, r.method) == (True, "raw")


def test_raw_cp1252(tmp_path, no_ifilter):
    p = tmp_path / "a.bin"
    p.write_bytes(b"\x00\x00" + "Coût XYZ".encode("cp1252"))
    assert extractors.match_file(str(p), "coût xyz").matched is True


def test_raw_inside_zip_member(tmp_path, no_ifilter):
    p = make_zip(tmp_path / "a.idml", {"Stories/s.xml": "<c>Mot X</c><c>YZ</c>"})
    r = extractors.match_file(p, "Mot XYZ")
    assert (r.matched, r.method) == (True, "raw")


def test_raw_no_match(tmp_path, no_ifilter):
    p = tmp_path / "a.bin"
    p.write_bytes(b"\x00rien\x00")
    r = extractors.match_file(str(p), "XYZ")
    assert (r.matched, r.method) == (False, "raw")


def test_raw_disabled_gives_unverified(tmp_path, no_ifilter):
    p = tmp_path / "a.bin"
    p.write_bytes(b"XYZ")
    r = extractors.match_file(str(p), "XYZ", allow_raw=False)
    assert r.matched is None and "désactivée" in r.reason


def test_protected_file_is_unverified(tmp_path):
    p = tmp_path / "a.docx"
    p.write_bytes(extractors.OLE_MAGIC + b"\x00" * 600)
    r = extractors.match_file(str(p), "XYZ")
    assert r.matched is None and "protégé" in r.reason


def test_corrupt_native_falls_back_to_raw(tmp_path, no_ifilter):
    p = tmp_path / "a.xlsx"
    p.write_bytes(b"pas un zip XYZ")
    r = extractors.match_file(str(p), "XYZ")
    assert (r.matched, r.method) == (True, "raw")


def test_unreadable_file_is_unverified(tmp_path, no_ifilter):
    r = extractors.match_file(str(tmp_path / "absent.bin"), "XYZ")
    assert r.matched is None and "lecture" in r.reason
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extractors_match.py -v`
Expected: FAIL — `AttributeError: module 'extractors' has no attribute 'match_file'`

- [ ] **Step 3: Implémenter** — dans `extractors.py`, remplacer le bloc d'imports par :

```python
import html
import logging
import os
import re
import unicodedata
import zipfile
from dataclasses import dataclass

import openpyxl
import xlrd
from pypdf import PdfReader

import config
import ifilter
```

puis ajouter en fin de fichier :

```python
RAW_ENCODINGS = ("utf-8", "utf-16-le", "cp1252")


@dataclass
class MatchResult:
    matched: bool | None      # None = non vérifié
    method: str | None        # "native" | "ifilter" | "raw"
    reason: str | None = None


def _text_contains(data, needle, case_sensitive):
    for enc in RAW_ENCODINGS:
        for offset in ((0, 1) if enc == "utf-16-le" else (0,)):
            if needle in normalize(data[offset:].decode(enc, errors="ignore"), case_sensitive):
                return True
    return False


def raw_contains(path, phrase, case_sensitive):
    """Recherche brute : octets du fichier, puis membres décompressés s'il s'agit d'un zip."""
    needle = normalize(phrase, case_sensitive)
    with open(path, "rb") as f:
        data = f.read(config.RAW_LIMIT)
    if _text_contains(data, needle, case_sensitive):
        return True
    if not data.startswith(b"PK\x03\x04"):
        return False
    try:
        with zipfile.ZipFile(path) as z:
            budget = config.RAW_LIMIT
            for info in z.infolist():
                if info.is_dir() or info.file_size > budget:
                    continue
                budget -= info.file_size
                try:
                    member = z.read(info)
                except (RuntimeError, zipfile.BadZipFile, NotImplementedError):
                    continue  # membre chiffré ou compression non prise en charge
                as_xml = xml_to_text(member.decode("utf-8", errors="ignore"))
                if needle in normalize(as_xml, case_sensitive) or _text_contains(member, needle, case_sensitive):
                    return True
    except zipfile.BadZipFile:
        pass
    return False


def match_file(path, phrase, case_sensitive=False, allow_raw=True):
    """Cherche `phrase` (expression exacte) dans le fichier, par le premier niveau qui sait le lire."""
    needle = normalize(phrase, case_sensitive)
    errors = []

    try:
        text = native_text(path)
        if text is not None:
            return MatchResult(needle in normalize(text[: config.TEXT_LIMIT], case_sensitive), "native")
    except ProtectedFile as e:
        return MatchResult(None, None, f"protégé par mot de passe : {e}")
    except Exception as e:
        errors.append(f"lecteur natif : {e}")

    if ifilter.has_filter(os.path.splitext(path)[1].lower()):
        try:
            text = ifilter.extract_text(path, config.IFILTER_TIMEOUT)
            if text.strip():
                return MatchResult(needle in normalize(text, case_sensitive), "ifilter")
            errors.append("IFilter : aucun texte")
        except ifilter.IFilterError as e:
            errors.append(f"IFilter : {e}")

    if not allow_raw:
        detail = "; ".join(errors)
        return MatchResult(None, None, "aucun lecteur (recherche brute désactivée)" + (f" — {detail}" if detail else ""))
    try:
        return MatchResult(raw_contains(path, phrase, case_sensitive), "raw")
    except OSError as e:
        errors.append(str(e))
        return MatchResult(None, None, "erreur de lecture : " + "; ".join(errors))
```

- [ ] **Step 4: Lancer les tests (nouveaux et tâche 3)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_extractors_match.py tests/test_extractors_native.py -v`
Expected: 27 passed

- [ ] **Step 5: Commit**

```powershell
git add extractors.py tests/test_extractors_match.py
git commit -m @'
feat: recherche dans le contenu en 3 niveaux (natif, IFilter, brut)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 6: Recherche dans le contenu (candidats Everything)

**Files:**
- Create: `content_search.py`, `tests/test_content_search.py`

**Interfaces:**
- Consumes: `everything_backend.search`, `everything_backend.Entry`, `extractors.match_file`, `extractors.MatchResult`, `config.CONTENT_TIMEOUT`.
- Produces:
  - `CLOUD_ATTRIBUTES = 0x1000 | 0x400000 | 0x40000`
  - `class TooManyCandidates(Exception)`
  - `is_cloud_only(entry: Entry) -> bool`
  - `find_content(query, phrase, case_sensitive=False, include_cloud=False, allow_raw=True, max_candidates=2000, *, search=None, match=None, timeout=None, clock=time.monotonic) -> dict` — clés `query, phrase, candidates, matches, not_matching, unverified` ; lève `ValueError` si `phrase` vide, `TooManyCandidates`, `EverythingError`.

- [ ] **Step 1: Écrire les tests qui échouent** — `tests/test_content_search.py`

```python
import pytest

import content_search
from everything_backend import Entry
from extractors import MatchResult


def E(path, attributes=32):
    return Entry(path, 10, "2024-01-01T00:00:00", attributes, False)


def fake_search(entries, calls):
    def search(query, max_results, **kwargs):
        calls.append((query, max_results, kwargs))
        return entries[:max_results]
    return search


def never_called(*args, **kwargs):
    pytest.fail("aucune lecture de fichier attendue")


def test_classifies_results():
    entries = [E(r"C:\a.xls"), E(r"C:\b.xls"), E(r"C:\c.xls")]
    results = {
        r"C:\a.xls": MatchResult(True, "native"),
        r"C:\b.xls": MatchResult(False, "native"),
        r"C:\c.xls": MatchResult(None, None, "protégé par mot de passe"),
    }
    calls = []
    out = content_search.find_content(
        "ext:xls", "XYZ", search=fake_search(entries, calls),
        match=lambda path, phrase, **kw: results[path],
    )
    assert out["query"] == "ext:xls file:"
    assert out["candidates"] == 3
    assert out["matches"] == [{"path": r"C:\a.xls", "size": 10, "modified": "2024-01-01T00:00:00", "method": "native"}]
    assert out["not_matching"] == 1
    assert out["unverified"] == [{"path": r"C:\c.xls", "reason": "protégé par mot de passe"}]
    assert calls[0][1] == 2001


def test_too_many_candidates():
    entries = [E(f"C:\\{i}.txt") for i in range(4)]
    with pytest.raises(content_search.TooManyCandidates, match="restreindre"):
        content_search.find_content("ext:txt", "x", max_candidates=3,
                                    search=fake_search(entries, []), match=never_called)


def test_cloud_only_files_skipped_without_reading():
    out = content_search.find_content("ext:pdf", "x", search=fake_search([E(r"C:\od.pdf", 0x500020)], []),
                                      match=never_called)
    assert out["unverified"][0]["reason"].startswith("en ligne uniquement")


def test_cloud_only_files_included_on_request():
    out = content_search.find_content("ext:pdf", "x", include_cloud=True,
                                      search=fake_search([E(r"C:\od.pdf", 0x500020)], []),
                                      match=lambda path, phrase, **kw: MatchResult(True, "native"))
    assert len(out["matches"]) == 1


def test_timeout_marks_remaining_files():
    ticks = iter([0, 0, 10])
    entries = [E(r"C:\1.txt"), E(r"C:\2.txt"), E(r"C:\3.txt")]
    out = content_search.find_content("ext:txt", "x", timeout=5, clock=lambda: next(ticks),
                                      search=fake_search(entries, []),
                                      match=lambda path, phrase, **kw: MatchResult(False, "native"))
    assert out["not_matching"] == 1
    assert [u["reason"] for u in out["unverified"]] == ["délai dépassé", "délai dépassé"]


def test_unexpected_reader_error_is_unverified():
    def boom(path, phrase, **kw):
        raise RuntimeError("boum")
    out = content_search.find_content("ext:txt", "x", search=fake_search([E(r"C:\1.txt")], []), match=boom)
    assert "boum" in out["unverified"][0]["reason"]


def test_empty_phrase_refused():
    with pytest.raises(ValueError):
        content_search.find_content("ext:txt", "", search=fake_search([], []), match=never_called)


def test_is_cloud_only_reads_stat_when_attributes_missing(tmp_path):
    p = tmp_path / "local.txt"
    p.write_text("x")
    assert content_search.is_cloud_only(Entry(str(p), 1, None, None, False)) is False
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_content_search.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'content_search'`

- [ ] **Step 3: Implémenter** — `content_search.py`

```python
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
```

- [ ] **Step 4: Lancer les tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_content_search.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```powershell
git add content_search.py tests/test_content_search.py
git commit -m @'
feat: recherche d'expression exacte dans les fichiers candidats (cloud exclu par défaut)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 7: Résumé de dossier

**Files:**
- Create: `folder_info.py`, `tests/test_folder_info.py`

**Interfaces:**
- Consumes: `everything_backend.search`, `everything_backend.Entry`, `config.FOLDER_MAX_ITEMS`.
- Produces: `folder_info(path: str, depth: int = 1, *, search=None, max_items=None) -> dict` — clés `path, files, folders, size, latest_modified, truncated, subfolders` (liste de `{path, relative, files, folders, size}`), `by_extension` (liste de `{extension, files, size}`, 30 max, par taille décroissante) ; lève `ValueError` si le chemin n'est pas un dossier absolu existant.

- [ ] **Step 1: Écrire les tests qui échouent** — `tests/test_folder_info.py`

```python
import pytest

import folder_info
from everything_backend import Entry


def build(root):
    return [
        Entry(root + r"\A", 0, None, 16, True),
        Entry(root + r"\A\B", 0, None, 16, True),
        Entry(root + r"\A\f1.xls", 100, "2024-01-01T00:00:00", 32, False),
        Entry(root + r"\A\B\f2.XLS", 50, "2025-06-01T00:00:00", 32, False),
        Entry(root + r"\f3.pdf", 10, "2023-01-01T00:00:00", 32, False),
        Entry(root + r"\README", 1, None, 32, False),
        Entry(r"D:\ailleurs\x.txt", 999, None, 32, False),  # hors du dossier : ignoré
    ]


def fake_search(entries, calls):
    def search(query, max_results, **kwargs):
        calls.append((query, max_results))
        return entries[:max_results]
    return search


def test_aggregates_depth_1(tmp_path):
    root = str(tmp_path)
    calls = []
    out = folder_info.folder_info(root, search=fake_search(build(root), calls))
    assert calls[0][0] == f'"{root}\\"'
    assert (out["files"], out["folders"], out["size"]) == (4, 2, 161)
    assert out["latest_modified"] == "2025-06-01T00:00:00"
    assert out["truncated"] is False
    assert out["subfolders"] == [{"path": root + r"\A", "relative": "A", "files": 2, "folders": 1, "size": 150}]
    by_ext = {d["extension"]: d for d in out["by_extension"]}
    assert by_ext[".xls"] == {"extension": ".xls", "files": 2, "size": 150}
    assert by_ext["(sans extension)"]["files"] == 1
    assert out["by_extension"][0]["extension"] == ".xls"


def test_depth_2_lists_nested_folders(tmp_path):
    root = str(tmp_path)
    out = folder_info.folder_info(root, depth=2, search=fake_search(build(root), []))
    nested = {s["relative"]: s for s in out["subfolders"]}
    assert nested["A\\B"] == {"path": root + r"\A\B", "relative": "A\\B", "files": 1, "folders": 0, "size": 50}


def test_truncated(tmp_path):
    root = str(tmp_path)
    out = folder_info.folder_info(root, search=fake_search(build(root), []), max_items=2)
    assert out["truncated"] is True


def test_invalid_path(tmp_path):
    with pytest.raises(ValueError):
        folder_info.folder_info(str(tmp_path / "absent"), search=fake_search([], []))
    with pytest.raises(ValueError):
        folder_info.folder_info("relatif", search=fake_search([], []))
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_folder_info.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'folder_info'`

- [ ] **Step 3: Implémenter** — `folder_info.py`

```python
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
```

- [ ] **Step 4: Lancer les tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_folder_info.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```powershell
git add folder_info.py tests/test_folder_info.py
git commit -m @'
feat: résumé de dossier depuis l'index Everything

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 8: Copie — vérifications et planification

**Files:**
- Create: `copier.py` (première partie), `tests/test_copier_plan.py`

**Interfaces:**
- Produces:
  - `class CopyRefused(Exception)`
  - `is_within(path: str, parent: str) -> bool`
  - `check_destination(destination: str) -> str` (chemin normalisé ; lève `CopyRefused`)
  - `@dataclass FileJob(source: str, parent: str, name: str, size: int)`
  - `@dataclass DirJob(source: str, parent: str, name: str, files: list[tuple[str, str, int]], subdirs: list[str])` — `files` = `(chemin source, chemin relatif, taille)`
  - `@dataclass Plan(destination: str, mode: str, jobs: list, skipped: list, tree_dirs: list)` avec propriétés `file_count: int`, `total_bytes: int`
  - `plan_copy(paths: list[str], destination: str, preserve_tree_from: str = "") -> Plan` — **ne crée rien**
  - Raisons de `skipped` (textes exacts) : `"chemin non absolu"`, `"en double dans la liste"`, `"introuvable"`, `"déjà dans la destination"`, `"hors de la racine preserve_tree_from"`, `"lien symbolique ou jonction non suivi"`, `"dossier illisible : …"`.

- [ ] **Step 1: Écrire les tests qui échouent** — `tests/test_copier_plan.py`

```python
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
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_copier_plan.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'copier'`

- [ ] **Step 3: Implémenter** — `copier.py` (première partie)

```python
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
```

- [ ] **Step 4: Lancer les tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_copier_plan.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```powershell
git add copier.py tests/test_copier_plan.py
git commit -m @'
feat: planification de copie (vérifications de destination, dossiers, arborescence)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 9: Copie — exécution sans écrasement et manifeste

**Files:**
- Modify: `copier.py` (imports en tête + ajout en fin de fichier)
- Create: `tests/test_copier_execute.py`

**Interfaces:**
- Consumes: `plan_copy`, `Plan`, `FileJob`, `DirJob`, `CopyRefused` (tâche 8), `config.COPY_MAX_FILES`, `config.COPY_MAX_BYTES`.
- Produces:
  - `MANIFEST_NAME = "manifest.csv"`, `MANIFEST_HEADER = ["date_copie", "source", "copie", "taille"]`
  - `class PartialCopyError(Exception)` (attribut `target`)
  - `copy_file_exclusive(source: str, parent: str, name: str) -> str` (chemin créé)
  - `execute(plan: Plan, max_files: int | None = None, max_bytes: int | None = None) -> dict`
  - `copy_items(paths, destination, preserve_tree_from="", max_files=None, max_bytes=None) -> dict` — clés `destination, mode, copied_files, copied_bytes, copied (200 premiers {source, copy, size}), skipped, errors ({source, error}), manifest`.

- [ ] **Step 1: Écrire les tests qui échouent** — `tests/test_copier_execute.py`

```python
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
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_copier_execute.py -v`
Expected: FAIL — `AttributeError: module 'copier' has no attribute 'copy_items'`

- [ ] **Step 3: Implémenter** — dans `copier.py`, remplacer les imports par :

```python
import csv
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime

import config
```

puis ajouter en fin de fichier :

```python
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
```

- [ ] **Step 4: Lancer tous les tests de copie**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_copier_execute.py tests/test_copier_plan.py -v`
Expected: 20 passed

- [ ] **Step 5: Commit**

```powershell
git add copier.py tests/test_copier_execute.py
git commit -m @'
feat: exécution de copie sans écrasement, plafonds et manifeste

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 10: Garde-fou statique

**Files:**
- Create: `tests/test_guardrails.py`

**Interfaces:**
- Consumes: tous les `*.py` à la racine du dépôt.
- Produces: `violations(source: str) -> list[str]` (dans le fichier de test).

- [ ] **Step 1: Écrire le test** — `tests/test_guardrails.py`

```python
"""Le serveur ne doit contenir aucune opération destructrice : ni suppression, ni déplacement,
ni renommage, ni écrasement. Ce test analyse le code source de chaque module serveur."""

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER_MODULES = sorted(ROOT.glob("*.py"))

FORBIDDEN_ATTRS = {
    "os": {"remove", "unlink", "rmdir", "removedirs", "rename", "renames", "replace", "truncate", "open"},
    "shutil": {"move", "rmtree", "copytree", "copy", "copy2", "copyfile"},
}
FORBIDDEN_MODULES = {"pathlib", "send2trash"}


def _open_mode(call):
    if len(call.args) > 1:
        return call.args[1]
    return next((k.value for k in call.keywords if k.arg == "mode"), None)


def violations(source):
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.attr in FORBIDDEN_ATTRS.get(node.value.id, ()):
                found.append(f"{node.value.id}.{node.attr} (ligne {node.lineno})")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in FORBIDDEN_MODULES:
                found.append(f"import {node.module} (ligne {node.lineno})")
            for alias in node.names:
                if alias.name in FORBIDDEN_ATTRS.get(node.module, ()):
                    found.append(f"from {node.module} import {alias.name} (ligne {node.lineno})")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_MODULES:
                    found.append(f"import {alias.name} (ligne {node.lineno})")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            mode = _open_mode(node)
            if mode is None:
                continue
            if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
                found.append(f"open() avec un mode non littéral (ligne {node.lineno})")
            elif "w" in mode.value or "+" in mode.value:
                found.append(f"open(..., {mode.value!r}) (ligne {node.lineno})")
    return found


def test_all_server_modules_are_checked():
    names = {p.name for p in SERVER_MODULES}
    assert {"server.py", "copier.py", "extractors.py", "ifilter.py", "content_search.py",
            "folder_info.py", "everything_backend.py", "config.py"} <= names


@pytest.mark.parametrize("module", SERVER_MODULES, ids=lambda p: p.name)
def test_no_destructive_operation(module):
    assert violations(module.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("snippet", [
    "import os\nos.remove('x')",
    "import os\nos.replace('a', 'b')",
    "import shutil\nshutil.copy2('a', 'b')",
    "import shutil\nshutil.move('a', 'b')",
    "from os import rename",
    "import pathlib",
    "open('f', 'w')",
    "open('f', mode='r+b')",
])
def test_checker_detects(snippet):
    assert violations(snippet)


def test_checker_allows_safe_calls():
    assert violations("open('f', 'xb')\nopen('m', 'a')\nopen('s', 'rb')\nimport shutil\nshutil.copyfileobj(a, b)") == []
```

- [ ] **Step 2: Lancer le test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_guardrails.py -v`
Expected: `test_all_server_modules_are_checked` passe ; **`test_no_destructive_operation[server.py]` passe aussi** (l'ancien `server.py` n'utilise que `subprocess`) ; tous les autres passent. Si un module échoue, corriger le module (jamais le test).

- [ ] **Step 3: Commit**

```powershell
git add tests/test_guardrails.py
git commit -m @'
test: garde-fou statique contre toute opération destructrice

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 11: Serveur MCP — les 5 outils

**Files:**
- Modify (réécriture complète): `server.py`
- Create: `tests/test_server.py`

**Interfaces:**
- Consumes: `config`, `everything_backend.search/EverythingError/SORTS`, `content_search.find_content/TooManyCandidates`, `folder_info.folder_info`, `copier.copy_items/CopyRefused`.
- Produces: `mcp` (instance serveur) et les fonctions-outils `everything_search`, `everything_show`, `everything_find_content`, `everything_folder_info`, `everything_copy`, toutes `-> str` (JSON).

- [ ] **Step 1: Écrire les tests qui échouent** — `tests/test_server.py`

```python
import asyncio
import json

import everything_backend
import server
from everything_backend import Entry

TOOLS = ["everything_copy", "everything_find_content", "everything_folder_info", "everything_search", "everything_show"]


def tool_names():
    return sorted(t.name for t in asyncio.run(server.mcp.list_tools()))


def test_tools_registered():
    assert tool_names() == TOOLS


def test_no_destructive_tool():
    for name in tool_names():
        assert not any(word in name for word in ("move", "delete", "remove", "rename", "write"))


def test_search_formats_results(monkeypatch):
    monkeypatch.setattr(everything_backend, "search",
                        lambda q, **kw: [Entry(r"C:\a.pdf", 3, "2025-01-01T00:00:00", 32, False)])
    out = json.loads(server.everything_search("ext:pdf"))
    assert out["results"] == [{"path": r"C:\a.pdf", "size": 3, "modified": "2025-01-01T00:00:00"}]
    assert out["returned"] == 1 and "note" not in out


def test_search_error_is_reported(monkeypatch):
    def boom(q, **kw):
        raise everything_backend.EverythingError("Everything n'est pas lancé")
    monkeypatch.setattr(everything_backend, "search", boom)
    assert "lancé" in json.loads(server.everything_search("x"))["error"]


def test_find_content_error_is_reported(monkeypatch):
    monkeypatch.setattr(everything_backend, "search", lambda q, **kw: [Entry(f"C:\\{i}", 1, None, 32, False) for i in range(5)])
    out = json.loads(server.everything_find_content("ext:txt", "x", max_candidates=2))
    assert "restreindre" in out["error"]


def test_folder_info_error_is_reported(tmp_path):
    assert "introuvable" in json.loads(server.everything_folder_info(str(tmp_path / "absent")))["error"]


def test_copy_refusal_is_reported():
    assert "absolu" in json.loads(server.everything_copy([], "extract"))["error"]


def test_copy_end_to_end(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("x")
    out = json.loads(server.everything_copy([str(src)], str(tmp_path / "out")))
    assert out["copied_files"] == 1 and (tmp_path / "out" / "a.txt").exists()
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_server.py -v`
Expected: FAIL — `test_tools_registered` (outils manquants) et erreurs d'attributs (`everything_copy`…).

- [ ] **Step 3: Réécrire** — `server.py`

```python
"""Serveur MCP entre Claude Code et Everything (voidtools).

Outils : recherche, affichage dans Everything, recherche dans le contenu, résumé de dossier,
copie de fichiers et de dossiers. Garde-fou : aucun outil ne déplace, ne renomme, ne supprime
ni n'écrase quoi que ce soit — seule la création de nouvelles copies est possible.
"""

import json
import subprocess

try:  # SDK MCP v2
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # SDK MCP v1
    from mcp.server.fastmcp import FastMCP

import config
import content_search
import copier
import everything_backend
import folder_info as folder_info_module

mcp = FastMCP("everything")

GUI_SORTS = {
    "name": "Name", "path": "Path", "size": "Size", "extension": "Extension",
    "date-modified": "Date Modified", "date-created": "Date Created",
}


def _json(data):
    return json.dumps(data, ensure_ascii=False, indent=1)


def _error(message, **extra):
    return _json({"error": message, **extra})


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
    """Recherche instantanée de fichiers et dossiers sur le PC Windows via Everything 1.4.

    Traduire la demande en requête Everything. La syntaxe est TOUJOURS en anglais ; les dates
    TOUJOURS au format ISO AAAA-MM-JJ (jamais jour/mois/année, ambigu).

    Opérateurs : espace = ET, | = OU, ! = NON, < > = groupement, "..." = expression exacte.
    Jokers : * (0+ caractères), ? (1 caractère).
    Filtres utiles :
      file:  folder:                       uniquement fichiers / dossiers
      ext:pdf;docx;xlsx                    extensions (séparées par ;)
      "D:\\Projets\\"                      tout ce qui est sous ce dossier (sous-dossiers inclus)
      infolder:"C:\\Docs"  parent:...      dans ce dossier exactement (sans sous-dossiers)
      size:>50mb  size:1mb..10mb  size:huge (16-128 Mo)  size:gigantic (>128 Mo)  size:empty
      dm:>=2020-01-01  dm:2024-01-01..2024-06-30  dm:today  dm:thisweek  dm:last2weeks  dm:thisyear
      dc: (création), da: (accès) — même syntaxe que dm:
      dupe:  sizedupe:  empty:  child:<nom>  childcount:  attrib:<lettres>  type:<type>  count:<n>
      startwith:  endwith:  wholeword:  case:  nodiacritics:  width:  height:  orientation:portrait
    Ne pas utiliser content: (lent et aveugle aux fichiers Office) : utiliser everything_find_content.
    Exemples :
      "les PDF du chantier Martin modifiés cette semaine" -> ext:pdf *martin* dm:thisweek
      "les gros fichiers vidéo sur D:"                    -> "D:\\" ext:mp4;mov;mkv;avi size:>500mb
      "les Excel depuis le 1er janvier 2020"              -> ext:xls;xlsx;xlsm dm:>=2020-01-01
      "dossiers vides dans Documents"                     -> folder: empty: "C:\\Users\\moi\\Documents\\"
    Référence complète : docs/everything-syntax-1.4.md dans le dépôt du serveur.

    Paramètres :
      query        requête Everything
      max_results  nombre de résultats (défaut 50, plafonné)
      offset       décalage pour paginer
      sort         name | path | size | extension | date-modified | date-created
      descending   tri décroissant (défaut True : plus récent / plus gros d'abord)
      match_path   faire porter les termes sur le chemin complet, pas seulement le nom
      regex        interpréter la requête comme une expression régulière (sur le nom)

    Renvoie du JSON : liste de {path, size (octets), modified, type="folder" pour un dossier}.
    Si 0 résultat, essayer une requête moins restrictive avant de conclure.
    """
    max_results = max(1, min(int(max_results), config.MAX_RESULTS))
    offset = max(0, int(offset))
    try:
        entries = everything_backend.search(
            query, max_results=max_results, offset=offset, sort=sort,
            descending=descending, match_path=match_path, regex=regex,
        )
    except everything_backend.EverythingError as e:
        return _error(str(e), query=query)
    out = {"query": query, "returned": len(entries), "offset": offset, "results": [e.to_dict() for e in entries]}
    if len(entries) == max_results:
        out["note"] = "Résultats tronqués : utiliser offset pour la suite ou affiner la requête."
    return _json(out)


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
    d'Everything (« montre-moi », « ouvre dans Everything », « affiche-les »). Même syntaxe de
    requête qu'everything_search.

    Paramètres :
      query       requête Everything (syntaxe anglaise)
      sort        name | path | size | extension | date-modified | date-created
      descending  tri décroissant
      match_path  faire porter les termes sur le chemin complet
      regex       requête en expression régulière
      select      chemin complet d'un fichier à sélectionner dans les résultats (optionnel)
      new_window  ouvrir une nouvelle fenêtre plutôt que réutiliser celle déjà ouverte
    """
    args = [config.EVERYTHING_EXE]
    if config.INSTANCE:
        args += ["-instance", config.INSTANCE]
    args.append("-newwindow" if new_window else "-nonewwindow")
    args.append("-matchpath" if match_path else "-nomatchpath")
    args.append("-regex" if regex else "-noregex")
    args += ["-sort", GUI_SORTS.get(sort, "Date Modified")]
    args.append("-sort-descending" if descending else "-sort-ascending")
    args += ["-s", query]
    if select:
        args += ["-select", select]
    try:
        subprocess.Popen(args, close_fds=True)
    except FileNotFoundError:
        return _error(f"Everything.exe introuvable : {config.EVERYTHING_EXE}. Renseignez EVERYTHING_EXE.")
    except OSError as e:
        return _error(f"Impossible de lancer Everything : {e}")
    return _json({"shown": True, "query": query})


@mcp.tool()
def everything_find_content(
    query: str,
    phrase: str,
    case_sensitive: bool = False,
    include_cloud: bool = False,
    allow_raw: bool = True,
    max_candidates: int = 2000,
) -> str:
    """Trouve les fichiers dont le CONTENU contient exactement une expression, quel que soit le format.

    Everything sélectionne d'abord les candidats avec `query` (même syntaxe qu'everything_search ;
    file: est ajouté automatiquement), puis le serveur ouvre chaque fichier et cherche `phrase`.
    La requête DOIT être restrictive : un dossier ("D:\\Chantiers\\") et/ou ext:, dm:… Au-delà de
    max_candidates fichiers, l'outil refuse et demande d'affiner.

    Lecture : lecteurs natifs (xls, xlsx, docx, pptx, odt/ods/odp, pdf, texte), puis IFilters
    Windows (doc, msg, rtf…), puis recherche brute dans les octets (method="raw", moins fiable).
    Les fichiers OneDrive « en ligne uniquement » sont ignorés (non téléchargés) sauf include_cloud.

    Paramètres :
      query           requête Everything des candidats, ex. ext:xls dm:>=2020-01-01 "D:\\Chantiers\\"
      phrase          expression exacte à trouver (espaces compris)
      case_sensitive  respecter la casse (défaut non)
      include_cloud   inclure les fichiers OneDrive non présents en local (déclenche leur téléchargement)
      allow_raw       autoriser la recherche brute pour les formats sans lecteur
      max_candidates  plafond de fichiers à examiner (défaut 2000)

    Renvoie du JSON : candidates, matches [{path, size, modified, method}], not_matching (nombre),
    unverified [{path, reason}] — un fichier non vérifié n'est jamais compté comme correspondant.
    """
    try:
        return _json(content_search.find_content(
            query, phrase, case_sensitive=case_sensitive, include_cloud=include_cloud,
            allow_raw=allow_raw, max_candidates=max(1, int(max_candidates)),
        ))
    except (everything_backend.EverythingError, content_search.TooManyCandidates, ValueError) as e:
        return _error(str(e), query=query)


@mcp.tool()
def everything_folder_info(path: str, depth: int = 1) -> str:
    """Résume le contenu d'un dossier depuis l'index Everything (sans parcourir le disque).

    Paramètres :
      path   chemin absolu du dossier
      depth  profondeur des sous-dossiers détaillés (1 à 5, défaut 1)

    Renvoie du JSON : files, folders, size (octets, récursif), latest_modified, subfolders
    [{path, relative, files, folders, size}], by_extension [{extension, files, size}] (30 plus
    volumineuses), truncated (True si le dossier dépasse le plafond d'éléments).
    """
    try:
        return _json(folder_info_module.folder_info(path, depth))
    except (everything_backend.EverythingError, ValueError) as e:
        return _error(str(e), path=path)


@mcp.tool()
def everything_copy(paths: list[str], destination: str, preserve_tree_from: str = "") -> str:
    """COPIE des fichiers et/ou dossiers vers un dossier de destination. Ne déplace, ne renomme,
    ne supprime et n'écrase JAMAIS rien.

    AVANT d'appeler cet outil : montrer à l'utilisateur la liste (nombre, taille totale) et
    obtenir sa confirmation explicite.

    Paramètres :
      paths               chemins ABSOLUS de fichiers et/ou dossiers (un dossier est copié en entier)
      destination         chemin ABSOLU du dossier de destination (créé au besoin). Une destination
                          relative donnée par l'utilisateur (ex. "extract/") se résout depuis le
                          dossier du projet Claude Code courant.
      preserve_tree_from  optionnel : dossier racine dont l'arborescence relative est recréée dans
                          la destination (ex. "D:\\Chantiers" -> extract\\A\\B\\f.xls). Vide = à plat.

    Règles : nom déjà pris -> suffixe " (2)", " (3)"… ; dossier homonyme existant -> "Nom (2)"
    (jamais de fusion) ; plafonds en nombre de fichiers et en volume vérifiés avant toute écriture
    (dépassement = rien n'est copié) ; liens et jonctions non suivis ; dossiers système refusés.
    Chaque copie est consignée dans manifest.csv (date_copie;source;copie;taille) à la racine de
    la destination.

    Renvoie du JSON : copied_files, copied_bytes, copied [{source, copy, size}] (200 premiers),
    skipped [{source, reason}], errors [{source, error}], manifest.
    """
    try:
        return _json(copier.copy_items(paths, destination, preserve_tree_from))
    except copier.CopyRefused as e:
        return _error(str(e), destination=destination)


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 4: Lancer toute la suite**

Run: `.\.venv\Scripts\python.exe -m pytest -v`
Expected: tous les tests passent (≈ 90), dont `tests/test_guardrails.py` sur le nouveau `server.py`.

- [ ] **Step 5: Vérifier le démarrage du serveur**

Run: `.\.venv\Scripts\python.exe -c "import asyncio, server; print(sorted(t.name for t in asyncio.run(server.mcp.list_tools())))"`
Expected: `['everything_copy', 'everything_find_content', 'everything_folder_info', 'everything_search', 'everything_show']`

- [ ] **Step 6: Commit**

```powershell
git add server.py tests/test_server.py
git commit -m @'
feat: serveur MCP à 5 outils (recherche, affichage, contenu, dossier, copie)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 12: Skill, README, enregistrement dans Claude Code, tests d'intégration

**Files:**
- Create: `skill/SKILL.md` (source versionnée), `~/.claude/skills/everything/SKILL.md` (copie installée), `tests/test_integration.py`
- Modify (réécriture complète): `README.md`

**Interfaces:**
- Consumes: les 5 outils (tâche 11), `everything_backend.search`, `content_search.is_cloud_only`, `ifilter.extract_text`, `ifilter.has_filter`.

- [ ] **Step 1: Écrire le skill** — `skill/SKILL.md`

```markdown
---
name: everything
description: Recherche, exploration et COPIE de fichiers et dossiers sur ce PC Windows via Everything (voidtools), y compris recherche dans le contenu de tout format. Utiliser quand l'utilisateur tape /everything suivi de sa demande en langage naturel, ou demande de trouver, lister, explorer ou copier/extraire des fichiers sur son PC.
---

# /everything — fichiers du PC via Everything

L'utilisateur tape `/everything <demande en langage naturel>`. Les outils viennent du serveur MCP `everything` (préfixe `mcp__everything__`). S'ils sont différés, les charger en un seul appel ToolSearch : `select:mcp__everything__everything_search,mcp__everything__everything_show,mcp__everything__everything_find_content,mcp__everything__everything_folder_info,mcp__everything__everything_copy`.

## Garde-fou absolu

**Interdit de déplacer, renommer, supprimer ou écraser un fichier ou un dossier** — ni avec ces outils, ni avec Bash/PowerShell (`mv`, `rm`, `rmdir`, `del`, `ren`, `Move-Item`, `Remove-Item`, `Rename-Item`, `robocopy /MOV /MOVE /MIR /PURGE`, `Copy-Item -Force` sur un fichier existant…). Si l'utilisateur le demande, refuser en une phrase et proposer une copie à la place. Toute duplication passe par `everything_copy`, jamais par une commande shell.

## 1. Traduire la demande

- Syntaxe Everything **en anglais** ; dates **toujours ISO** : « plus récent que le 1er janvier 2020 » → `dm:>=2020-01-01`.
- Dossier : `"D:\Chantiers\"` (avec antislash final, entre guillemets) = tout ce qui est dessous.
- Cas inhabituels : lire `C:\Users\pmaubert\dev\everything_mcp\docs\everything-syntax-1.4.md`.

## 2. Choisir l'outil

| Demande | Outil |
|---|---|
| trouver / lister des fichiers ou dossiers par nom, extension, date, taille | `everything_search` |
| « montre », « affiche », « ouvre dans Everything » | `everything_show` |
| « que contient ce dossier », taille, types de fichiers d'un dossier | `everything_folder_info` |
| un critère porte sur le **contenu** (« contenant », « qui mentionne ») | `everything_find_content` |
| « copie », « extrais », « duplique », « sauvegarde dans » | recherche puis `everything_copy` |

- Recherche dans le contenu : **exiger un dossier**. S'il n'y en a pas dans la demande, demander lequel avant de lancer. Mettre l'expression exacte dans `phrase`, les autres critères (extension, date, dossier) dans `query`.
- Si 0 résultat : réessayer une requête moins restrictive (jokers `*`, moins de termes, `match_path`) avant de conclure.

## 3. Copier — toujours en deux temps

1. **Rechercher** les éléments à copier (`everything_search` ou `everything_find_content`).
2. **Résoudre la destination** : un chemin relatif (`extract/`) se résout depuis le dossier du projet courant (répertoire de travail de Claude Code) → chemin absolu Windows.
3. **Choisir le mode** : à plat par défaut ; `preserve_tree_from=<dossier racine>` si l'utilisateur veut « garder la structure / les sous-dossiers ».
4. **Présenter l'aperçu** et **attendre une confirmation explicite** :
   - nombre de fichiers et taille totale (dossiers : utiliser `everything_folder_info` pour les compter) ;
   - les 20 premiers éléments ;
   - destination absolue et mode ;
   - fichiers non vérifiés (`unverified`) et correspondances `method: "raw"` (moins fiables), s'il y en a.
5. Après le « oui » : appeler `everything_copy` avec les chemins absolus.
6. **Rendre compte** : nombre copié, volume, éléments ignorés (`skipped`) et erreurs, chemin du `manifest.csv`.

Des fichiers OneDrive « en ligne uniquement » dans un dossier à copier seront téléchargés : le signaler dans l'aperçu.

## Présentation des résultats

- Tableau compact : nom, dossier, taille lisible (Ko/Mo/Go), date de modification.
- Indiquer la requête Everything utilisée, sur une ligne.
- Beaucoup de résultats : afficher les 20 plus pertinents, proposer la suite (`offset`) ou `everything_show`.

## Si les outils sont introuvables ou en erreur

Everything doit être lancé (icône dans la zone de notification). Vérifier la connexion du serveur avec `/mcp`. Le dire simplement à l'utilisateur.
```

- [ ] **Step 2: Installer le skill**

Run: `New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills\everything" | Out-Null; Copy-Item skill\SKILL.md "$env:USERPROFILE\.claude\skills\everything\SKILL.md"; Get-Item "$env:USERPROFILE\.claude\skills\everything\SKILL.md" | Select FullName, Length`
Expected: le fichier existe (taille > 0). (Destination neuve : aucun fichier existant n'est écrasé ; vérifier avant que le dossier n'existe pas déjà, sinon arrêter et demander.)

- [ ] **Step 3: Réécrire** — `README.md`

```markdown
# Everything ↔ Claude Code

Serveur MCP local qui permet à Claude Code, dans n'importe quel projet, de chercher des fichiers avec Everything (voidtools), d'explorer des dossiers, de chercher une expression dans le contenu des fichiers (tous formats) et de **copier** des fichiers ou dossiers.

**Garde-fou :** aucun outil ne déplace, renomme, supprime ou écrase quoi que ce soit. Les copies sont créées sous un nom libre (`nom (2).ext`) et consignées dans `manifest.csv`.

## Utilisation

Dans Claude Code : `/everything <demande>`, par exemple :

- `/everything les PDF du chantier Martin modifiés cette semaine`
- `/everything que contient D:\Chantiers\Martin ?`
- `/everything les xls de D:\Chantiers qui contiennent exactement "XYZ"`
- `/everything copie dans extract/ tous les .xls de D:\Chantiers contenant "XYZ" plus récents que le 01/01/2020`
- `/everything copie le dossier D:\Chantiers\Martin dans sauvegarde/ en gardant la structure`

Avant toute copie, Claude montre un aperçu et attend votre accord.

## Outils exposés

| Outil | Rôle |
|---|---|
| `everything_search` | Recherche par nom, chemin, extension, date, taille… |
| `everything_show` | Affiche la recherche dans la fenêtre d'Everything |
| `everything_find_content` | Expression exacte dans le contenu (lecteurs natifs, IFilters Windows, recherche brute) |
| `everything_folder_info` | Résumé d'un dossier : sous-dossiers, nombre de fichiers, tailles, extensions |
| `everything_copy` | Copie de fichiers et dossiers, à plat ou en conservant l'arborescence |

## Installation

Prérequis : Everything lancé, `es.exe` (CLI d'Everything) présent dans `C:\Program Files\Everything\` ou `C:\Program Files (x86)\Everything\`, Python 3.10+.

```powershell
cd C:\Users\pmaubert\dev\everything_mcp
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
claude mcp add --scope user everything -- "C:\Users\pmaubert\dev\everything_mcp\.venv\Scripts\python.exe" "C:\Users\pmaubert\dev\everything_mcp\server.py"
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills\everything"
Copy-Item skill\SKILL.md "$env:USERPROFILE\.claude\skills\everything\SKILL.md"
```

Claude Code lance le serveur automatiquement à chaque session. Vérification : `/mcp` doit afficher `everything` connecté.

## Options (variables d'environnement, à passer avec `-e NOM=valeur` dans `claude mcp add`)

| Variable | Rôle | Défaut |
|---|---|---|
| `ES_PATH` | Chemin de es.exe | détecté automatiquement |
| `EVERYTHING_EXE` | Chemin d'Everything.exe | détecté automatiquement |
| `EVERYTHING_INSTANCE` | Instance, ex. `1.5a` | vide |
| `EVERYTHING_MAX_RESULTS` | Plafond de résultats par recherche | `500` |
| `EVERYTHING_COPY_MAX_FILES` | Plafond de fichiers par copie | `500` |
| `EVERYTHING_COPY_MAX_BYTES` | Plafond de volume par copie (octets) | `2147483648` |
| `EVERYTHING_CONTENT_TIMEOUT` | Durée max d'une recherche dans le contenu (s) | `300` |
| `EVERYTHING_FOLDER_MAX_ITEMS` | Éléments max analysés par résumé de dossier | `500000` |
| `EVERYTHING_BACKEND` | `es` ou `http` | `es` |
| `EVERYTHING_HTTP_URL` | Serveur HTTP d'Everything | `http://127.0.0.1:8080` |

## Développement

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest                 # tests unitaires
.\.venv\Scripts\python.exe -m pytest -m integration  # tests sur le vrai Everything
```

Le test `tests/test_guardrails.py` échoue si un module du serveur introduit une opération destructrice (suppression, déplacement, renommage, écrasement).

## Dépannage

- **« es.exe a échoué (code 8) »** : Everything n'est pas lancé (ou instance 1.5 alpha : `-e EVERYTHING_INSTANCE=1.5a`).
- **« es.exe introuvable »** : renseigner `ES_PATH`.
- **Fichiers OneDrive ignorés** dans une recherche de contenu : ils ne sont pas en local ; demander explicitement de les inclure (téléchargement).
- **`method: "raw"`** : le format n'a ni lecteur ni IFilter ; correspondance trouvée dans les octets bruts, à vérifier.
```

- [ ] **Step 4: Écrire les tests d'intégration** — `tests/test_integration.py`

```python
"""Tests sur le vrai Everything et de vrais fichiers du poste : `pytest -m integration`."""

import os

import pytest

import content_search
import everything_backend
import ifilter

pytestmark = pytest.mark.integration
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")


def test_finds_repo_docs_with_quoted_folder():
    entries = everything_backend.search(f'ext:md "{REPO}\\docs\\"', max_results=50)
    assert any(e.path.endswith("everything-syntax-1.4.md") for e in entries)


def test_option_like_term_writes_nothing(tmp_path):
    out = tmp_path / "export.csv"
    everything_backend.search(f"-export-csv {out} zzz_inexistant_42", max_results=5)
    everything_backend.search(f"/export-csv {out} zzz_inexistant_42", max_results=5)
    assert not out.exists()


def test_cloud_only_attribute_is_reported():
    entries = everything_backend.search(f'"{HOME}\\" file: ext:pdf;docx;xlsx', max_results=5000)
    cloud = [e for e in entries if e.attributes and e.attributes & 0x400000]
    if not cloud:
        pytest.skip("aucun fichier OneDrive en ligne uniquement trouvé")
    assert content_search.is_cloud_only(cloud[0])


@pytest.mark.parametrize("ext", ["doc", "msg"])
def test_ifilter_on_real_files(ext):
    if not ifilter.has_filter(f".{ext}"):
        pytest.skip(f"pas d'IFilter .{ext}")
    entries = everything_backend.search(f'"{HOME}\\" file: ext:{ext} size:<2mb', max_results=50)
    local = [e for e in entries if not content_search.is_cloud_only(e)]
    if not local:
        pytest.skip(f"aucun .{ext} local")
    assert ifilter.extract_text(local[0].path, timeout=60).strip()
```

- [ ] **Step 5: Lancer les tests d'intégration**

Run: `.\.venv\Scripts\python.exe -m pytest -m integration -v`
Expected: passed (certains peuvent être « skipped » selon les fichiers présents ; aucun « failed »).

- [ ] **Step 6: Enregistrer le serveur dans Claude Code (niveau utilisateur)**

Run: `claude mcp add --scope user everything -- "C:\Users\pmaubert\dev\everything_mcp\.venv\Scripts\python.exe" "C:\Users\pmaubert\dev\everything_mcp\server.py"; claude mcp list`
Expected: une ligne `everything: ... - √ Connected`.

- [ ] **Step 7: Vérification manuelle de bout en bout (avec l'utilisateur, dans une nouvelle session Claude Code ouverte sur un autre projet)**

1. `/mcp` → `everything` connecté, 5 outils.
2. `/everything les fichiers .md de C:\Users\pmaubert\dev\everything_mcp\docs` → résultats.
3. `/everything montre dans Everything les .md de C:\Users\pmaubert\dev\everything_mcp\docs` → la fenêtre d'Everything affiche bien la requête **avec le chemin entre guillemets** (vérifie le passage de guillemets à Everything.exe ; si la recherche affichée est vide ou tronquée, le signaler et corriger `everything_show`).
4. `/everything copie dans extract/ les .md de C:\Users\pmaubert\dev\everything_mcp\docs contenant "garde-fou"` → aperçu, confirmation, puis `extract\` créé dans le projet courant avec les copies et `manifest.csv`.
5. Relancer la même copie → nouvelles copies suffixées ` (2)`, originaux intacts.
6. `/everything supprime extract/` → refus.

- [ ] **Step 8: Commit**

```powershell
git add skill/SKILL.md README.md tests/test_integration.py
git commit -m @'
feat: skill /everything, README Claude Code et tests d'intégration

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```
