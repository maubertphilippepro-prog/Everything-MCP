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
        raise IFilterError(f"délai de {timeout} s dépassé") from None
    except OSError as e:
        raise IFilterError(f"lancement du processus de lecture impossible : {e}") from e
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", "replace").strip()[:500]
        raise IFilterError(message or f"code de sortie {proc.returncode}")
    return proc.stdout.decode("utf-8", "replace")


def _read_with_ifilter(path, limit):
    if not os.path.isfile(path):  # LoadIFilter réussit même sur un fichier absent
        raise FileNotFoundError(f"fichier introuvable : {path}")
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
        sys.stderr.buffer.write(f"{type(e).__name__}: {e}".encode("utf-8"))
        sys.exit(2)
    sys.stdout.buffer.write(text.encode("utf-8"))
