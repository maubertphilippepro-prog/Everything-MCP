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
