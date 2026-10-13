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
    # Exclut les faux fichiers (%TEMP%, tests unitaires) et les fichiers vides ; certains fichiers
    # portant l'extension sans être de vrais documents (ex. .msg de traduction) sont tolérés :
    # il suffit qu'un des premiers candidats réels soit lu.
    local = [e for e in entries
             if not content_search.is_cloud_only(e) and e.size and "\\temp\\" not in e.path.lower()]
    if not local:
        pytest.skip(f"aucun .{ext} local")
    for entry in local[:10]:
        try:
            if ifilter.extract_text(entry.path, timeout=60).strip():
                return
        except ifilter.IFilterError:
            continue
    pytest.fail(f"aucun des {min(len(local), 10)} premiers .{ext} n'a pu être lu par son IFilter")
