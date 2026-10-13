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
import zlib
from dataclasses import dataclass

import openpyxl
import xlrd
from pypdf import PdfReader

import config
import ifilter

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

_BREAKS = re.compile(r"</(?:w:p|a:p|text:p|text:h)>|<(?:w:br|w:cr|a:br|text:line-break)\b[^>]*/>")
_HIDDEN = re.compile(r"<w:(delText|instrText)\b[^>]*>.*?</w:\1>", re.DOTALL)
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
    xml = _HIDDEN.sub("", xml)  # texte supprimé (suivi des modifications) et codes de champs Word
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
        lines, size = [], 0
        for sheet in book.sheets():
            for r in range(sheet.nrows):
                line = "\t".join(_cell_text(v) for v in sheet.row_values(r))
                lines.append(line)
                size += len(line) + 1
                if size > config.TEXT_LIMIT:
                    return "\n".join(lines)
        return "\n".join(lines)
    finally:
        book.release_resources()


def _read_xlsx(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        lines, size = [], 0
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                line = "\t".join(_cell_text(v) for v in row)
                lines.append(line)
                size += len(line) + 1
                if size > config.TEXT_LIMIT:
                    return "\n".join(lines)
        return "\n".join(lines)
    finally:
        wb.close()


def _read_zip_xml(path, pattern):
    rx = re.compile(pattern)
    parts, size = [], 0
    with zipfile.ZipFile(path) as z:
        for info in sorted((i for i in z.infolist() if rx.fullmatch(i.filename)), key=lambda i: i.filename):
            remaining = config.TEXT_LIMIT - size
            if remaining <= 0:
                break
            with z.open(info) as m:
                data = m.read(remaining)  # membre trop gros : lu jusqu'au plafond seulement
            text = xml_to_text(data.decode("utf-8", "replace"))
            parts.append(text)
            size += len(text) + 1
            if info.file_size > remaining:
                break
    return "\n".join(parts)


def _read_pdf(path):
    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception as e:
            raise ProtectedFile(f"PDF chiffré : {e}")
        if not unlocked:
            raise ProtectedFile("PDF protégé par mot de passe")
    pages, size = [], 0
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)
        size += len(text) + 1
        if size > config.TEXT_LIMIT:
            break
    return "\n".join(pages)


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


RAW_CHUNK = 8 * 1024 * 1024         # taille des blocs de la recherche brute
XML_PASS_LIMIT = 50 * 1024 * 1024   # au-delà, pas de passe « texte XML » sur un membre zip


def _stream_contains(fileobj, needle, case_sensitive, limit):
    """Recherche par blocs dans un flux d'octets (au plus `limit` octets), avec recouvrement."""
    keep = 4 * len(needle) + 8  # assez pour contenir l'expression quel que soit l'encodage
    tail = b""
    total = 0
    while total < limit:
        chunk = fileobj.read(min(RAW_CHUNK, limit - total))
        if not chunk:
            break
        total += len(chunk)
        buf = tail + chunk
        if _text_contains(buf, needle, case_sensitive):
            return True
        tail = buf[-keep:]
    return False


def _raw_search(path, phrase, case_sensitive):
    """Recherche brute : (trouvé, tronqué). `tronqué` = plafond RAW_LIMIT empêchant de tout lire."""
    needle = normalize(phrase, case_sensitive)
    truncated = os.path.getsize(path) > config.RAW_LIMIT
    with open(path, "rb") as f:
        if _stream_contains(f, needle, case_sensitive, config.RAW_LIMIT):
            return True, truncated
        f.seek(0)
        if f.read(4) != b"PK":
            return False, truncated
    try:
        with zipfile.ZipFile(path) as z:
            budget = config.RAW_LIMIT
            for info in z.infolist():
                if info.is_dir():
                    continue
                if info.file_size > budget:
                    truncated = True
                    continue
                budget -= info.file_size
                try:
                    with z.open(info) as member:
                        if _stream_contains(member, needle, case_sensitive, info.file_size):
                            return True, truncated
                    if info.file_size <= XML_PASS_LIMIT:
                        xml = z.read(info).decode("utf-8", errors="ignore")
                        if needle in normalize(xml_to_text(xml), case_sensitive):
                            return True, truncated
                except (RuntimeError, zipfile.BadZipFile, NotImplementedError, zlib.error, EOFError):
                    continue  # membre chiffré, corrompu, tronqué ou compression non prise en charge
    except zipfile.BadZipFile:
        pass
    return False, truncated


def raw_contains(path, phrase, case_sensitive):
    """Recherche brute : octets du fichier, puis membres décompressés s'il s'agit d'un zip."""
    return _raw_search(path, phrase, case_sensitive)[0]


PARTIAL_REASON = "lu partiellement (plafond atteint)"
NO_TEXT_REASON = "aucun texte extrait (PDF scanné ?)"


def _native_truncated(path, text):
    """Le texte natif a-t-il été coupé au plafond TEXT_LIMIT ?"""
    if len(text) >= config.TEXT_LIMIT:
        return True
    return os.path.splitext(path)[1].lower() in TEXT_EXTS and os.path.getsize(path) > config.TEXT_LIMIT


def match_file(path, phrase, case_sensitive=False, allow_raw=True):
    """Cherche `phrase` (expression exacte) dans le fichier, par le premier niveau qui sait le lire."""
    needle = normalize(phrase, case_sensitive)
    errors = []
    native_empty = False

    try:
        text = native_text(path)
        if text is not None:
            if needle in normalize(text[: config.TEXT_LIMIT], case_sensitive):
                return MatchResult(True, "native")
            if _native_truncated(path, text):
                return MatchResult(None, "native", PARTIAL_REASON)
            is_text_file = os.path.splitext(path)[1].lower() in TEXT_EXTS
            if text.strip() or is_text_file or os.path.getsize(path) == 0:
                return MatchResult(False, "native")
            native_empty = True  # PDF scanné, classeur d'images… : le lecteur n'a rien vu, on insiste
            errors.append("lecteur natif : aucun texte")
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
        if native_empty:
            return MatchResult(None, None, NO_TEXT_REASON)
        return MatchResult(None, None, "aucun lecteur (recherche brute désactivée)" + (f" — {detail}" if detail else ""))
    try:
        found, truncated = _raw_search(path, phrase, case_sensitive)
        if found:
            return MatchResult(True, "raw")
        if native_empty:
            return MatchResult(None, None, NO_TEXT_REASON)
        if truncated:
            return MatchResult(None, "raw", PARTIAL_REASON)
        return MatchResult(False, "raw")
    except Exception as e:  # OSError, mais aussi tout échec inattendu sur un fichier illisible
        errors.append(str(e))
        return MatchResult(None, None, "erreur de lecture : " + "; ".join(errors))
