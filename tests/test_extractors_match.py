import random
import zipfile
import zlib

import pytest

import extractors
import ifilter
from helpers import make_pdf, make_zip


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


def test_corrupted_deflate_member_does_not_raise(tmp_path, no_ifilter):
    p = tmp_path / "bad.zip"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("a.txt", bytes(random.Random(1).randrange(256) for _ in range(3000)).hex() * 3)
    raw = bytearray(p.read_bytes())
    for i in range(36, 39):  # données compressées du membre : flux deflate invalide
        raw[i] ^= 0xFF
    p.write_bytes(bytes(raw))
    with pytest.raises(zlib.error):
        zipfile.ZipFile(p).read("a.txt")
    r = extractors.match_file(str(p), "introuvable")
    assert (r.matched, r.method) == (False, "raw")


def test_unexpected_error_in_raw_search_is_reported(tmp_path, no_ifilter, monkeypatch):
    p = tmp_path / "a.bin"
    p.write_bytes(b"xyz")

    def boom(*a):
        raise ValueError("boum")

    monkeypatch.setattr(extractors, "_raw_search", boom)
    r = extractors.match_file(str(p), "xyz")
    assert r.matched is None and "boum" in r.reason


def test_raw_phrase_straddling_chunk_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(extractors, "RAW_CHUNK", 16)
    for enc in ("utf-8", "utf-16-le"):
        for pad in range(0, 20):
            p = tmp_path / f"c{pad}.bin"
            p.write_bytes(b"." * pad + "code secret zeta".encode(enc) + b".....")
            assert extractors.raw_contains(str(p), "secret zeta", False), (enc, pad)
    z = make_zip(tmp_path / "c.zip", {"m.bin": b"." * 13 + b"code secret zeta"})
    assert extractors.raw_contains(z, "secret zeta", False)


def test_oversized_xml_member_still_searched_natively(tmp_path, monkeypatch):
    xml = "<w:document><w:p>code secret zeta</w:p>" + "<w:p>" + "z" * 5000 + "</w:p></w:document>"
    p = make_zip(tmp_path / "gros.docx", {"word/document.xml": xml})
    monkeypatch.setattr(extractors.config, "TEXT_LIMIT", 300)
    text = extractors.native_text(p)
    assert text and len(text) <= 300
    r = extractors.match_file(p, "secret zeta")
    assert (r.matched, r.method) == (True, "native")


def test_empty_native_text_is_not_a_definitive_no_match(tmp_path, no_ifilter):
    p = make_zip(tmp_path / "scan.docx", {"word/document.xml": "<w:document><w:p></w:p></w:document>"})
    r = extractors.match_file(p, "xyz")
    assert r.matched is None and "aucun texte extrait" in r.reason


def test_empty_native_text_falls_through_to_ifilter(tmp_path, monkeypatch):
    p = make_zip(tmp_path / "scan.docx", {"word/document.xml": "<w:document><w:p></w:p></w:document>"})
    monkeypatch.setattr(ifilter, "has_filter", lambda ext: True)
    monkeypatch.setattr(ifilter, "extract_text", lambda path, timeout: "texte océrisé XYZ")
    r = extractors.match_file(p, "xyz")
    assert (r.matched, r.method) == (True, "ifilter")


def test_empty_native_text_without_ifilter_is_unverified_not_raw(tmp_path, no_ifilter):
    p = tmp_path / "scan.pdf"
    make_pdf(p, "")
    r = extractors.match_file(str(p), "xyz")
    assert r.matched is None and "aucun texte extrait" in r.reason


def test_image_only_pdf_never_matches_by_chance(tmp_path, no_ifilter):
    nl = bytes([10])
    noise = random.Random(0).randbytes(2 * 1024 * 1024)
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>",
        b"<< /Length 0 >>" + nl + b"stream" + nl + nl + b"endstream",
        b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /Length %d >>" % len(noise)
        + nl + b"stream" + nl + noise + nl + b"endstream",
    ]
    out = bytearray(b"%PDF-1.4" + nl)
    offsets = []
    for n, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj" % n + nl + body + nl + b"endobj" + nl
    xref = len(out)
    out += b"xref" + nl + b"0 %d" % (len(objs) + 1) + nl + b"0000000000 65535 f " + nl
    for off in offsets:
        out += b"%010d 00000 n " % off + nl
    out += b"trailer << /Size %d /Root 1 0 R >>" % (len(objs) + 1) + nl
    out += b"startxref" + nl + b"%d" % xref + nl + b"%%EOF" + nl
    p = tmp_path / "image.pdf"
    p.write_bytes(bytes(out))
    for phrase in ("XYZ", "A12", "B7"):
        assert extractors.match_file(str(p), phrase).matched is None


def test_empty_txt_file_stays_not_matching(tmp_path, no_ifilter):
    p = tmp_path / "vide.txt"
    p.write_bytes(b"")
    r = extractors.match_file(str(p), "xyz")
    assert (r.matched, r.method) == (False, "native")


def test_native_truncation_is_signalled(tmp_path, monkeypatch):
    p = tmp_path / "gros.txt"
    p.write_text("a" * 200 + "\nfin xyz", encoding="utf-8")
    monkeypatch.setattr(extractors.config, "TEXT_LIMIT", 100)
    r = extractors.match_file(str(p), "xyz")
    assert r.matched is None and r.method == "native" and "partiellement" in r.reason


def test_raw_truncation_is_signalled(tmp_path, monkeypatch, no_ifilter):
    p = tmp_path / "gros.bin"
    p.write_bytes(b"\x00" * 200 + b"xyz")
    monkeypatch.setattr(extractors.config, "RAW_LIMIT", 100)
    r = extractors.match_file(str(p), "xyz")
    assert r.matched is None and r.method == "raw" and "partiellement" in r.reason


def test_xml_soft_break_and_hidden_word_text():
    assert extractors.xml_to_text("<a:p><a:r><a:t>ligne un</a:t></a:r><a:br/><a:r><a:t>ligne deux</a:t></a:r></a:p>") \
        == "ligne un\nligne deux\n"
    xml = ("<w:p><w:r><w:t>garde</w:t></w:r><w:del><w:r><w:delText>supprimé</w:delText></w:r></w:del>"
          "<w:r><w:instrText> PAGE MERGEFORMAT</w:instrText></w:r></w:p>")
    assert extractors.xml_to_text(xml) == "garde\n"
