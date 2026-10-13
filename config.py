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
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value >= 1 else default


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
