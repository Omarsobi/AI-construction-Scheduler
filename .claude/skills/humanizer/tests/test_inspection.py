#!/usr/bin/env python3
"""Report-only inspection suite (AI Fix Rev36).

Proves two inspections: embedded image metadata, and revisions and hidden
content. Both must find what is there, say plainly what they could not read,
and change nothing: not the image, not the revisions, not the hidden text, not
the file being inspected.

Every fixture is generated here or held as a constant. The base JPEG is a
2 x 2 pixel image with no metadata. Four Rev35 constants (two TIFF, one
two-page TIFF, one WebP) were written by Pillow and confirmed separately with
exiftool, so the TIFF and WebP cases do not depend only on this file's own
builders. The suite needs no imaging library. No project document is used
or shipped. GPS values and location text are synthetic test values, selected
for software testing only and not intended to identify any real-world
location or any real project, organization or document.

    python tests/test_inspection.py

Exit status 0 when every case passes, 1 otherwise.
"""

import base64
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
HYGIENE = os.path.join(SCRIPTS, "metadata_hygiene.py")
INSPECT = os.path.join(SCRIPTS, "inspect_content.py")

from test_annotations import docx_with_comment, read_zip, write_zip, xlsx_with_comment  # noqa
from test_delivery import pptx_parts  # noqa: E402
import inspect_content as ic  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
SS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"

BASE_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYWGDEjJR0oOjM9PDkzODdASFxO"
    "QERXRTc4UG1RV19iZ2hnPk1xeXBkeFxlZ2P/2wBDARESEhgVGC8aGi9jQjhCY2NjY2NjY2NjY2NjY2NjY2Nj"
    "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2P/wAARCAACAAIDASIAAhEBAxEB/8QAHwAAAQUBAQEB"
    "AQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKB"
    "kaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1"
    "dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl"
    "5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcF"
    "BAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5"
    "OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0"
    "tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwCSiiivGPWP/9k=")

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(script, *args):
    p = subprocess.run([sys.executable, script] + list(args), capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    return p.returncode, p.stdout + p.stderr


# ---------------------------------------------------------------- EXIF builders

def tiff(ifd0, exif=None, gps=None):
    """A little-endian TIFF/EXIF block. Each IFD is a list of
    (tag, type, count, packed-bytes)."""
    ifds = [("ifd0", list(ifd0))]
    if exif:
        ifds.append(("exif", list(exif)))
    if gps:
        ifds.append(("gps", list(gps)))
    # offsets are laid out: header, IFD0, EXIF IFD, GPS IFD, then data
    sizes = {name: 2 + 12 * (len(entries) + (1 if name == "ifd0" else 0) * 0) + 4
             for name, entries in ifds}
    # IFD0 gains pointer entries for the sub-IFDs
    extra = (1 if exif else 0) + (1 if gps else 0)
    sizes["ifd0"] = 2 + 12 * (len(ifd0) + extra) + 4
    off = 8
    starts = {}
    for name, _ in ifds:
        starts[name] = off
        off += sizes[name]
    data_off = off
    blob_data = b""

    def pack_ifd(entries, pointers):
        nonlocal blob_data
        allent = list(entries) + pointers
        allent.sort(key=lambda e: e[0])
        out = struct.pack("<H", len(allent))
        for tag, typ, count, raw in allent:
            if len(raw) <= 4:
                out += struct.pack("<HHI", tag, typ, count) + raw.ljust(4, b"\x00")
            else:
                out += struct.pack("<HHI", tag, typ, count) + struct.pack(
                    "<I", data_off + len(blob_data))
                blob_data += raw + (b"\x00" if len(raw) % 2 else b"")
        return out + struct.pack("<I", 0)

    pointers = []
    if exif:
        pointers.append((0x8769, 4, 1, struct.pack("<I", starts["exif"])))
    if gps:
        pointers.append((0x8825, 4, 1, struct.pack("<I", starts["gps"])))
    body = pack_ifd(ifd0, pointers)
    for name, entries in ifds[1:]:
        body += pack_ifd(entries, [])
    return b"II*\x00" + struct.pack("<I", 8) + body + blob_data


def ascii_tag(tag, text):
    raw = text.encode() + b"\x00"
    return (tag, 2, len(raw), raw)


def rational(*vals):
    return b"".join(struct.pack("<II", int(v * 10000), 10000) for v in vals)


# Synthetic coordinate test values, selected for software testing only and not
# intended to identify any real-world location (Rev36). Every GPS value in this
# suite, valid or malformed, is built from them.
DMS_LAT = 12 + 34 / 60 + 56 / 3600      # 12,34,56 N
DMS_LON = 123 + 45 / 60 + 6 / 3600      # 123,45,6 E


def gps_ifd(lat=(12, 34, 56.0), lon=(123, 45, 6.0)):
    return [(0x0001, 2, 2, b"N\x00"), (0x0002, 5, 3, rational(*lat)),
            (0x0003, 2, 2, b"E\x00"), (0x0004, 5, 3, rational(*lon))]


def jpeg_with(*segments):
    """Insert APPn segments after SOI of the base JPEG."""
    out = BASE_JPEG[:2]
    for marker, payload in segments:
        out += bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload
    return out + BASE_JPEG[2:]


def exif_segment(block):
    return (0xE1, b"Exif\x00\x00" + block)


def xmp_segment(inner):
    packet = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
              'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
              '<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/" '
              'xmlns:dc="http://purl.org/dc/elements/1.1/" %s</rdf:Description>'
              '</rdf:RDF></x:xmpmeta>' % inner).encode()
    return (0xE1, b"http://ns.adobe.com/xap/1.0/\x00" + packet)


def iptc_segment(records):
    iim = b"".join(b"\x1c\x02" + bytes([ds]) + struct.pack(">H", len(v)) + v
                   for ds, v in records)
    res = b"8BIM" + struct.pack(">H", 0x0404) + b"\x00\x00" + struct.pack(">I", len(iim)) + iim
    if len(iim) % 2:
        res += b"\x00"
    return (0xED, b"Photoshop 3.0\x00" + res)


def png_with(*chunks):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
    for t, d in chunks:
        out += chunk(t, d)
    return out + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def docx_with_images(images):
    parts = dict(docx_with_comment())
    for name, data in images.items():
        parts[name] = data
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].decode().replace(
        "</Types>", '<Default Extension="jpeg" ContentType="image/jpeg"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '<Default Extension="gif" ContentType="image/gif"/></Types>').encode()
    return parts


def statuses(parts):
    return {r["part"]: r for r in ic.inspect_images(parts)}


def cats(rec):
    return {c for c, _, _ in rec["items"]}


# ---------------------------------------------------------------- image cases

@case("I1. GPS position in an embedded JPEG is a review finding, shown rounded")
def i1(tmp):
    img = jpeg_with(exif_segment(tiff([ascii_tag(0x010F, "PhoneMaker")], gps=gps_ifd())))
    rec = statuses({"word/media/image1.jpeg": img})["word/media/image1.jpeg"]
    lines = "\n".join(ic.report_lines([rec], [], []))
    return (rec["status"] == "review" and ic.LOCATION in cats(rec)
            and "12.58, 123.75 (rounded)" in lines and "REVIEW" in lines), lines


@case("I2. camera make and model are reported as present, not as a concern by themselves")
def i2(tmp):
    img = jpeg_with(exif_segment(tiff([ascii_tag(0x010F, "PhoneMaker"),
                                       ascii_tag(0x0110, "Model X2")])))
    rec = statuses({"word/media/image1.jpeg": img})["word/media/image1.jpeg"]
    return rec["status"] == "present" and cats(rec) == {ic.DEVICE}, repr(rec)


@case("I3. capture timestamps are reported as present and marked as possible evidence")
def i3(tmp):
    img = jpeg_with(exif_segment(tiff([ascii_tag(0x0132, "2026:08:14 09:12:00")],
                                      exif=[ascii_tag(0x9003, "2026:08:14 09:11:58")])))
    rec = statuses({"word/media/image1.jpeg": img})["word/media/image1.jpeg"]
    lines = "\n".join(ic.report_lines([rec], [], []))
    return (rec["status"] == "present" and cats(rec) == {ic.TIMESTAMP}
            and "2026:08:14 09:11:58" in lines and "project evidence" in lines), lines


@case("I4. software, creator and copyright in EXIF, XMP and IPTC are all read")
def i4(tmp):
    img = jpeg_with(
        exif_segment(tiff([ascii_tag(0x0131, "PhotoEditor 5"), ascii_tag(0x013B, "J. Surveyor"),
                           ascii_tag(0x8298, "Example Co")])),
        xmp_segment('xmp:CreatorTool="LayoutTool 2"><dc:creator><rdf:Seq><rdf:li>A. Drafter'
                    '</rdf:li></rdf:Seq></dc:creator>'),
        iptc_segment([(80, b"B. Photographer"), (90, b"Riverside")]))
    rec = statuses({"word/media/image1.jpeg": img})["word/media/image1.jpeg"]
    vals = {v for _, _, v in rec["items"]}
    ok = ({"PhotoEditor 5", "J. Surveyor", "Example Co", "LayoutTool 2", "A. Drafter",
           "B. Photographer", "Riverside"} <= vals and rec["status"] == "review"
          and {"EXIF", "XMP", "IPTC"} <= set(rec["note"].replace(",", " ").split()))
    return ok, repr(rec)


@case("I5. an image with no metadata block is 'inspected, no relevant metadata found'")
def i5(tmp):
    rec = statuses({"word/media/image1.jpeg": BASE_JPEG})["word/media/image1.jpeg"]
    return rec["status"] == "none" and not rec["items"], repr(rec)


@case("I6. multiple images each get their own status, PNG included")
def i6(tmp):
    png = png_with((b"tEXt", b"Author\x00C. Engineer"),
                   (b"eXIf", tiff([ascii_tag(0x0131, "ScanApp")])))
    parts = {"word/media/image1.jpeg": jpeg_with(exif_segment(tiff([], gps=gps_ifd()))),
             "word/media/image2.jpeg": BASE_JPEG,
             "word/media/image3.png": png}
    st = statuses(parts)
    return (st["word/media/image1.jpeg"]["status"] == "review"
            and st["word/media/image2.jpeg"]["status"] == "none"
            and st["word/media/image3.png"]["status"] == "review"
            and {"C. Engineer", "ScanApp"} <= {v for _, _, v in st["word/media/image3.png"]["items"]}), \
        repr({k: v["status"] for k, v in st.items()})


@case("I7. a malformed JPEG is 'inspection incomplete', never clean")
def i7(tmp):
    bad = BASE_JPEG[:2] + b"\xff\xe1\x7f\xff" + b"Exif\x00\x00II*\x00"
    rec = statuses({"word/media/image1.jpeg": bad})["word/media/image1.jpeg"]
    return rec["status"] == "incomplete" and "could not be completed" in rec["note"], repr(rec)


@case("I8. an unsupported format is 'format not inspected', never clean")
def i8(tmp):
    gif = b"GIF89a\x01\x00\x01\x00\x00\x00\x00;"
    rec = statuses({"word/media/image1.gif": gif})["word/media/image1.gif"]
    lines = "\n".join(ic.report_lines([rec], [], []))
    return (rec["status"] == "not inspected" and "format not inspected" in lines
            and "not inspected 1" in lines), lines


@case("I9. inspection leaves the image and the whole file byte-identical, in scan and clean")
def i9(tmp):
    img = jpeg_with(exif_segment(tiff([ascii_tag(0x010F, "PhoneMaker")], gps=gps_ifd())))
    src = os.path.join(tmp, "report.docx")
    base = os.path.join(tmp, "base.docx")
    write_zip(src, docx_with_images({"word/media/image1.jpeg": img}))
    shutil.copy(src, base)
    before = sha(open(src, "rb").read())
    c1, o1 = run(HYGIENE, src, "--baseline", base)
    c2, o2 = run(INSPECT, src)
    out = os.path.join(tmp, "clean.docx")
    c3, o3 = run(HYGIENE, src, "--clean", "--baseline", base, "-o", out)
    after = sha(open(src, "rb").read())
    same_img = read_zip(out).get("word/media/image1.jpeg") == img
    log = open(os.path.join(tmp, "report_metahygiene.md"), encoding="utf-8").read()
    return (before == after and same_img and c2 == 0 and c3 == 0
            and "Pre-delivery review findings (report only)" in log
            and "[REVIEW] location" in log and "PASS" in o3), \
        "unchanged %s, image kept %s, clean %s" % (before == after, same_img, c3)


@case("I10. a document thumbnail is inspected like any other image")
def i10(tmp):
    img = jpeg_with(exif_segment(tiff([ascii_tag(0x013B, "D. Author")])))
    st = statuses({"docProps/thumbnail.jpeg": img})
    return st.get("docProps/thumbnail.jpeg", {}).get("status") == "review", repr(st)


@case("I11. a malformed XMP packet in one image does not hide findings in another")
def i11(tmp):
    bad = jpeg_with((0xE1, b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta><rdf:RDF><broken"
                           b"</x:xmpmeta>"))
    good = jpeg_with(exif_segment(tiff([], gps=gps_ifd())))
    st = statuses({"word/media/a.jpeg": bad, "word/media/b.jpeg": good})
    return (st["word/media/a.jpeg"]["status"] == "incomplete"
            and st["word/media/b.jpeg"]["status"] == "review"), \
        repr({k: v["status"] for k, v in st.items()})


# ---------------------------------------------------------------- revision cases

def revision_docx(body, styles=None, settings=None):
    parts = dict(docx_with_comment())
    parts["word/document.xml"] = ('<?xml version="1.0" encoding="UTF-8"?><w:document '
                                  'xmlns:w="%s" xmlns:wp="%s"><w:body>%s</w:body></w:document>'
                                  % (W, WP, body)).encode()
    if styles:
        parts["word/styles.xml"] = ('<?xml version="1.0"?><w:styles xmlns:w="%s">%s</w:styles>'
                                    % (W, styles)).encode()
    if settings:
        parts["word/settings.xml"] = ('<?xml version="1.0"?><w:settings xmlns:w="%s">%s'
                                      '</w:settings>' % (W, settings)).encode()
    return parts


ATTR = 'w:author="Reviewer One" w:date="2026-09-01T00:00:00Z"'
INS = '<w:p><w:r><w:t>Base </w:t></w:r><w:ins w:id="1" %s><w:r><w:t>added text</w:t></w:r></w:ins></w:p>' % ATTR
DEL = '<w:p><w:del w:id="2" %s><w:r><w:delText>removed text</w:delText></w:r></w:del></w:p>' % ATTR
HIDDEN = '<w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>secret note</w:t></w:r></w:p>'


def rev_findings(parts, ptype="docx"):
    f, p = ic.inspect_revisions(parts, ptype)
    return f, p, "\n".join(ic.report_lines([], f, p))


@case("R1. an unaccepted tracked insertion is found, with location and author")
def r1(tmp):
    f, p, text = rev_findings(revision_docx(INS))
    return ("tracked insertion at word/document.xml paragraph 1" in text
            and "added text" in text and "Reviewer One" in text
            and ic.WORKING in text and not p), text


@case("R2. a tracked deletion is found with its deleted text")
def r2(tmp):
    f, p, text = rev_findings(revision_docx(DEL))
    return "tracked deletion" in text and "removed text" in text, text


@case("R3. several revisions, moves and formatting changes are each reported")
def r3(tmp):
    move = ('<w:p><w:moveFrom w:id="3" %s><w:r><w:t>moved</w:t></w:r></w:moveFrom></w:p>'
            '<w:p><w:moveTo w:id="4" %s><w:r><w:t>moved</w:t></w:r></w:moveTo></w:p>'
            '<w:p><w:r><w:rPr><w:b/><w:rPrChange w:id="5" %s><w:rPr/></w:rPrChange>'
            '</w:rPr><w:t>bolded</w:t></w:r></w:p>' % (ATTR, ATTR, ATTR))
    f, p, text = rev_findings(revision_docx(INS + DEL + move))
    kinds = [k for k, _, _, _, _ in f]
    return (kinds.count("tracked insertion") == 1 and kinds.count("tracked deletion") == 1
            and "tracked move (from)" in kinds and "tracked move (to)" in kinds
            and "tracked formatting changes (1)" in kinds), repr(kinds)


@case("R4. hidden text, a hidden drawing, a hiding style and tracking-on are reported")
def r4(tmp):
    drawing = ('<w:p><w:r><w:drawing><wp:inline><wp:docPr id="7" name="Old logo" hidden="1"/>'
               '</wp:inline></w:drawing></w:r></w:p>')
    styles = ('<w:style w:type="character" w:styleId="HiddenNote"><w:rPr><w:vanish/></w:rPr>'
              '</w:style>')
    f, p, text = rev_findings(revision_docx(HIDDEN + drawing, styles,
                                            '<w:trackRevisions/>'))
    return ("hidden text at word/document.xml paragraph 1" in text and "secret note" in text
            and ic.UNINTENDED in text and "hidden drawing object: Old logo" in text
            and "style hides its text: HiddenNote" in text
            and "revision tracking is switched on" in text), text


@case("R5. a document with none of these reports 'inspected, none found'")
def r5(tmp):
    parts = revision_docx('<w:p><w:r><w:t>Plain</w:t></w:r></w:p>')
    parts.pop("word/comments.xml", None)
    f, p, text = rev_findings(parts)
    return not f and not p and "inspected, none found" in text, text


@case("R6. inspection leaves revisions unaccepted and hidden text unchanged, in scan and clean")
def r6(tmp):
    src = os.path.join(tmp, "draft.docx")
    base = os.path.join(tmp, "base.docx")
    parts = revision_docx(INS + DEL + HIDDEN, settings='<w:trackRevisions/>')
    write_zip(src, parts)
    shutil.copy(src, base)
    before = sha(open(src, "rb").read())
    c1, _ = run(HYGIENE, src, "--baseline", base)
    run(INSPECT, src)
    out = os.path.join(tmp, "clean.docx")
    c3, o3 = run(HYGIENE, src, "--clean", "--baseline", base, "-o", out)
    cand = read_zip(out)
    ok = (sha(open(src, "rb").read()) == before
          and cand.get("word/document.xml") == parts["word/document.xml"]
          and cand.get("word/settings.xml") == parts["word/settings.xml"]
          and b"<w:ins " in cand["word/document.xml"] and b"<w:vanish/>" in cand["word/document.xml"])
    return ok and c3 == 0, "unchanged %s, clean %s: %s" % (ok, c3, o3[-200:])


@case("R7. a document part that will not parse is reported as INSPECTION INCOMPLETE")
def r7(tmp):
    parts = revision_docx(INS)
    parts["word/header1.xml"] = b"<w:hdr xmlns:w='%s'><w:p>" % W.encode()
    f, p, text = rev_findings(parts)
    return p and "INSPECTION INCOMPLETE: word/header1.xml will not parse" in text, text


@case("R8. workbook: hidden and very hidden sheets, hidden rows and columns, revision logs")
def r8(tmp):
    parts = dict(xlsx_with_comment())
    parts["xl/workbook.xml"] = ('<?xml version="1.0"?><workbook xmlns="%s" xmlns:r="x"><sheets>'
                                '<sheet name="Summary" sheetId="1" r:id="rId1"/>'
                                '<sheet name="Calc" sheetId="2" state="hidden" r:id="rId2"/>'
                                '<sheet name="Old rates" sheetId="3" state="veryHidden" r:id="rId3"/>'
                                '</sheets></workbook>' % SS).encode()
    parts["xl/worksheets/sheet1.xml"] = ('<?xml version="1.0"?><worksheet xmlns="%s"><cols>'
                                         '<col min="3" max="4" hidden="1"/></cols><sheetData>'
                                         '<row r="5" hidden="1"/></sheetData></worksheet>'
                                         % SS).encode()
    parts["xl/revisions/revisionHeaders.xml"] = b"<headers/>"
    f, p, text = rev_findings(parts, "xlsx")
    return ("hidden sheet: Calc" in text and "very hidden sheet: Old rates" in text
            and "hidden rows (1): 5" in text and "hidden columns (1)" in text
            and "shared-workbook revision history" in text), text


@case("R9. presentation: hidden slide, hidden shape and speaker notes")
def r9(tmp):
    parts = dict(pptx_parts())
    parts["ppt/slides/slide2.xml"] = ('<?xml version="1.0"?><p:sld xmlns:p="%s" xmlns:a="%s" '
                                      'show="0"><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="4" '
                                      'name="Draft stamp" hidden="1"/></p:nvSpPr></p:sp>'
                                      '</p:spTree></p:cSld></p:sld>' % (P, A)).encode()
    parts["ppt/notesSlides/notesSlide2.xml"] = ('<?xml version="1.0"?><p:notes xmlns:p="%s" '
                                                'xmlns:a="%s"><a:t>Do not mention the claim</a:t>'
                                                '</p:notes>' % (P, A)).encode()
    f, p, text = rev_findings(parts, "pptx")
    return ("hidden slide at ppt/slides/slide2.xml" in text
            and "hidden shape: Draft stamp" in text and "speaker notes" in text), text


@case("R10. findings never claim AI use and the hygiene result is unchanged by them")
def r10(tmp):
    src = os.path.join(tmp, "draft.docx")
    base = os.path.join(tmp, "base.docx")
    write_zip(src, revision_docx(INS + HIDDEN))
    shutil.copy(src, base)
    out = os.path.join(tmp, "clean.docx")
    code, output = run(HYGIENE, src, "--clean", "--baseline", base, "-o", out)
    log = open(os.path.join(tmp, "draft_metahygiene.md"), encoding="utf-8").read()
    section = log.split("## Pre-delivery review findings (report only)")[1]
    return (code == 0 and "None of these findings is evidence of AI use" in section
            and "review findings (report only)" in output), output[-300:]


@case("R11. if the inspection itself fails, the log says INSPECTION INCOMPLETE, never clean")
def r11(tmp):
    scripts = os.path.join(tmp, "scripts")
    os.mkdir(scripts)
    shutil.copy(HYGIENE, scripts)
    with open(os.path.join(scripts, "inspect_content.py"), "w") as f:
        f.write("def inspect_images(parts):\n    raise RuntimeError('simulated failure')\n")
    src = os.path.join(tmp, "doc.docx")
    base = os.path.join(tmp, "base.docx")
    write_zip(src, revision_docx(INS))
    shutil.copy(src, base)
    code, output = run(os.path.join(scripts, "metadata_hygiene.py"), src, "--baseline", base)
    log = open(os.path.join(tmp, "doc_metahygiene.md"), encoding="utf-8").read()
    return ("INSPECTION INCOMPLETE" in log and "simulated failure" in log
            and "inspection could not run" in output), output[-300:]


# ---------------------------------------------------------------- Rev35 corrections (F1-F5)
#
# The four constants below were written by Pillow 12.2.0, not by the builders in this
# file, and their metadata was confirmed separately with exiftool 12.76:
#   TIFF_XMP700       dc:creator "Q. Inspector" in TIFF tag 700 only
#   TIFF_XMP700_IPTC  the same, plus IPTC By-line "R. Iptcwriter" in TIFF tag 33723
#   TIFF_TWO_PAGES    two image directories, no metadata of interest
#   WEBP_XMP          extended WebP with an XMP chunk, dc:creator "Q. Inspector"
# Each Rev35 case reports its subchecks; see main() for the separate count.

TIFF_XMP700 = base64.b64decode(
    "SUkqAAgAAAALAAABBAABAAAABAAAAAEBBAABAAAABAAAAAIBAwADAAAAkgAAAAMBAwABAAAAAQAAAAYBAwABAAAA"
    "AgAAABEBBAABAAAAKgIAABUBAwABAAAAAwAAABYBBAABAAAABAAAABcBBAABAAAAMAAAABwBAwABAAAAAQAAALwC"
    "AQCRAQAAmAAAAAAAAAAIAAgACAA8P3hwYWNrZXQgYmVnaW49IiIgaWQ9Ilc1TTBNcENlaGlIenJlU3pOVGN6a2M5"
    "ZCI/Pjx4OnhtcG1ldGEgeG1sbnM6eD0iYWRvYmU6bnM6bWV0YS8iPjxyZGY6UkRGIHhtbG5zOnJkZj0iaHR0cDov"
    "L3d3dy53My5vcmcvMTk5OS8wMi8yMi1yZGYtc3ludGF4LW5zIyI+PHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9"
    "IiIgeG1sbnM6ZGM9Imh0dHA6Ly9wdXJsLm9yZy9kYy9lbGVtZW50cy8xLjEvIiB4bWxuczpleGlmPSJodHRwOi8v"
    "bnMuYWRvYmUuY29tL2V4aWYvMS4wLyIgPjxkYzpjcmVhdG9yPjxyZGY6U2VxPjxyZGY6bGk+US4gSW5zcGVjdG9y"
    "PC9yZGY6bGk+PC9yZGY6U2VxPjwvZGM6Y3JlYXRvcj48L3JkZjpEZXNjcmlwdGlvbj48L3JkZjpSREY+PC94Onht"
    "cG1ldGE+PD94cGFja2V0IGVuZD0idyI/PgB4PB54PB54PB54PB54PB54PB54PB54PB54PB54PB54PB54PB54PB54"
    "PB54PB54PB4=")
TIFF_XMP700_IPTC = base64.b64decode(
    "SUkqAAgAAAAMAAABBAABAAAABAAAAAEBBAABAAAABAAAAAIBAwADAAAAngAAAAMBAwABAAAAAQAAAAYBAwABAAAA"
    "AgAAABEBBAABAAAASAIAABUBAwABAAAAAwAAABYBBAABAAAABAAAABcBBAABAAAAMAAAABwBAwABAAAAAQAAALwC"
    "AQCRAQAApAAAALuDBwASAAAANgIAAAAAAAAIAAgACAA8P3hwYWNrZXQgYmVnaW49IiIgaWQ9Ilc1TTBNcENlaGlI"
    "enJlU3pOVGN6a2M5ZCI/Pjx4OnhtcG1ldGEgeG1sbnM6eD0iYWRvYmU6bnM6bWV0YS8iPjxyZGY6UkRGIHhtbG5z"
    "OnJkZj0iaHR0cDovL3d3dy53My5vcmcvMTk5OS8wMi8yMi1yZGYtc3ludGF4LW5zIyI+PHJkZjpEZXNjcmlwdGlv"
    "biByZGY6YWJvdXQ9IiIgeG1sbnM6ZGM9Imh0dHA6Ly9wdXJsLm9yZy9kYy9lbGVtZW50cy8xLjEvIiB4bWxuczpl"
    "eGlmPSJodHRwOi8vbnMuYWRvYmUuY29tL2V4aWYvMS4wLyIgPjxkYzpjcmVhdG9yPjxyZGY6U2VxPjxyZGY6bGk+"
    "US4gSW5zcGVjdG9yPC9yZGY6bGk+PC9yZGY6U2VxPjwvZGM6Y3JlYXRvcj48L3JkZjpEZXNjcmlwdGlvbj48L3Jk"
    "ZjpSREY+PC94OnhtcG1ldGE+PD94cGFja2V0IGVuZD0idyI/PgAcAlAADVIuIElwdGN3cml0ZXJ4PB54PB54PB54"
    "PB54PB54PB54PB54PB54PB54PB54PB54PB54PB54PB54PB54PB4=")
TIFF_TWO_PAGES = base64.b64decode(
    "SUkqAAgAAAAKAAABBAABAAAABAAAAAEBBAABAAAABAAAAAIBAwADAAAAhgAAAAMBAwABAAAAAQAAAAYBAwABAAAA"
    "AgAAABEBBAABAAAAjAAAABUBAwABAAAAAwAAABYBBAABAAAABAAAABcBBAABAAAAMAAAABwBAwABAAAAAQAAAMgA"
    "AAAIAAgACAB4PB54PB54PB54PB54PB54PB54PB54PB54PB54PB54PB54PB54PB54PB54PB54PB4AAAAASUkqAAgA"
    "AAAKAAABBAABAAAABAAAAAEBBAABAAAABAAAAAIBAwADAAAARgEAAAMBAwABAAAAAQAAAAYBAwABAAAAAgAAABEB"
    "BAABAAAATAEAABUBAwABAAAAAwAAABYBBAABAAAABAAAABcBBAABAAAAMAAAABwBAwABAAAAAQAAAAAAAAAIAAgA"
    "CAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
WEBP_XMP = base64.b64decode(
    "UklGRsoBAABXRUJQVlA4WAoAAAAEAAAAAwAAAwAAVlA4TBEAAAAvA8AAAAdQnuLVo/+BiOh/AABYTVAgkQEAADw/"
    "eHBhY2tldCBiZWdpbj0iIiBpZD0iVzVNME1wQ2VoaUh6cmVTek5UY3prYzlkIj8+PHg6eG1wbWV0YSB4bWxuczp4"
    "PSJhZG9iZTpuczptZXRhLyI+PHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIy"
    "LXJkZi1zeW50YXgtbnMjIj48cmRmOkRlc2NyaXB0aW9uIHJkZjphYm91dD0iIiB4bWxuczpkYz0iaHR0cDovL3B1"
    "cmwub3JnL2RjL2VsZW1lbnRzLzEuMS8iIHhtbG5zOmV4aWY9Imh0dHA6Ly9ucy5hZG9iZS5jb20vZXhpZi8xLjAv"
    "IiA+PGRjOmNyZWF0b3I+PHJkZjpTZXE+PHJkZjpsaT5RLiBJbnNwZWN0b3I8L3JkZjpsaT48L3JkZjpTZXE+PC9k"
    "YzpjcmVhdG9yPjwvcmRmOkRlc2NyaXB0aW9uPjwvcmRmOlJERj48L3g6eG1wbWV0YT48P3hwYWNrZXQgZW5kPSJ3"
    "Ij8+AA==")

SUBCHECKS = [0]


def checks(*pairs):
    """Each (label, ok) is one subcheck; the case passes only when all pass."""
    SUBCHECKS[0] += len(pairs)
    failed = [label for label, ok in pairs if not ok]
    return not failed, ("failed: " + "; ".join(failed)) if failed else ""


def one(parts):
    return list(statuses(parts).values())[0]


def text_of(recs):
    return "\n".join(ic.report_lines(recs, [], []) + [ic.summary(recs, [], [])])


def riff(chunks, size_adjust=0, pad=True):
    body = b"WEBP"
    for t, d in chunks:
        body += t + struct.pack("<I", len(d)) + d + (b"\x00" if len(d) % 2 and pad else b"")
    return b"RIFF" + struct.pack("<I", len(body) - 0 + size_adjust) + body


XMP_TYPE = WEBP_XMP.find(b"XMP ")
NS_EXIF = "http://ns.adobe.com/exif/1.0/"


@case("I12. F1: TIFF XMP in tag 700 is read and reported (independent Pillow fixture)")
def i12(tmp):
    rec = one({"word/media/image1.tif": TIFF_XMP700})
    text = text_of([rec])
    ok, why = checks(
        ("fixture hash", sha(TIFF_XMP700).startswith("7eab997594f5e6d2")),
        ("status review", rec["status"] == "review"),
        ("creator read", ("identity", "creator", "Q. Inspector") in rec["items"]),
        ("tag 700 named as read", "XMP (TIFF tag 700)" in rec["note"]),
        ("complete", rec["complete"] is True),
        ("not reported as clean", "no relevant metadata found" not in text),
        ("summary", "1 image(s) needing review, 0 image(s) not fully inspected" in text))
    return ok, why + " " + text


@case("I13. F1: TIFF IPTC (tag 33723) and Photoshop resources (tag 34377) are 'not read', never absent")
def i13(tmp):
    rec = one({"word/media/image1.tif": TIFF_XMP700_IPTC})
    iim = b"\x1c\x02\x50\x00\x04Name"
    only_iptc = one({"word/media/a.tif": tiff([(33723, 7, len(iim), iim)])})
    only_ps = one({"word/media/b.tif": tiff([(34377, 7, 12, b"8BIM" + b"\x00" * 8)])})
    text = text_of([rec])
    ok, why = checks(
        ("fixture hash", sha(TIFF_XMP700_IPTC).startswith("0cb6906cc41cdc26")),
        ("XMP finding kept", ("identity", "creator", "Q. Inspector") in rec["items"]),
        ("IPTC named as not read", "present but not read: IPTC in TIFF tag 33723" in rec["note"]),
        ("IPTC value not claimed", "R. Iptcwriter" not in text),
        ("not complete", rec["complete"] is False),
        ("line flags incomplete", "review finding; inspection incomplete" in text),
        ("summary counts it", "1 image(s) not fully inspected" in text),
        ("IPTC only: incomplete, not none", only_iptc["status"] == "incomplete"),
        ("Photoshop only: incomplete, not none", only_ps["status"] == "incomplete"
         and "TIFF tag 34377" in only_ps["note"]))
    return ok, why + " " + text


@case("I14. F1: further TIFF image directories are 'not read', never absent")
def i14(tmp):
    rec = one({"word/media/image1.tif": TIFF_TWO_PAGES})
    single = one({"word/media/image2.tif": TIFF_XMP700})
    ok, why = checks(
        ("fixture hash", sha(TIFF_TWO_PAGES).startswith("7653dc3520050ea5")),
        ("status incomplete", rec["status"] == "incomplete"),
        ("reason given", "further TIFF image directories" in rec["note"]),
        ("single-page TIFF not affected", single["complete"] is True))
    return ok, why + " " + repr(rec)


@case("I15. F2: WebP cut after the 4-byte XMP chunk type is 'inspection incomplete' (QA case)")
def i15(tmp):
    cut = WEBP_XMP[:XMP_TYPE + 4]
    rec = one({"word/media/image1.webp": cut})
    text = text_of([rec])
    ok, why = checks(
        ("fixture hash", sha(WEBP_XMP).startswith("f7fbdb028eeb44bb")),
        ("ends on the chunk type", cut.endswith(b"XMP ")),
        ("status incomplete", rec["status"] == "incomplete"),
        ("not complete", rec["complete"] is False),
        ("unfinished header named", "chunk header at byte %d is incomplete" % XMP_TYPE in rec["note"]),
        ("declared size named", "declares %d bytes but %d are present" % (len(WEBP_XMP), len(cut))
         in rec["note"]),
        ("never 'none'", "no relevant metadata found" not in text),
        ("summary counts it", "1 image(s) not fully inspected" in text))
    return ok, why + " " + text


@case("I16. F2: WebP container, chunk header, payload and padding boundaries")
def i16(tmp):
    def st(data):
        return one({"word/media/x.webp": data})
    exif = tiff([ascii_tag(0x013B, "E. Webpauthor")])
    good_exif = riff([(b"EXIF", exif)])
    mid_header = st(WEBP_XMP[:XMP_TYPE + 6])
    payload = st(WEBP_XMP[:XMP_TYPE + 8 + 10])
    unpadded = riff([(b"VP8L", b"\x00" * 5)], pad=False)
    no_pad = st(unpadded)
    oversize = st(WEBP_XMP[:4] + struct.pack("<I", len(WEBP_XMP) - 8 + 2) + WEBP_XMP[8:])
    trailing = st(WEBP_XMP + b"\x00\x00\x00\x00")
    tiny = st(b"RIFF" + struct.pack("<I", 2) + b"WEBP")
    header_only = st(b"RIFF\x04\x00")
    later_break = st(riff([(b"EXIF", exif)], size_adjust=20) + b"XMP " + struct.pack("<I", 40) + b"<x")
    ok, why = checks(
        ("control: EXIF-only WebP complete", st(good_exif)["complete"] is True),
        ("header cut mid-length", mid_header["status"] == "incomplete"
         and "chunk header" in mid_header["note"]),
        ("payload shorter than declared", payload["status"] == "incomplete"
         and "runs past the end" in payload["note"]),
        ("odd chunk missing its padding byte", no_pad["status"] == "incomplete"
         and "padding byte" in no_pad["note"]),
        ("container declares more than present: not complete, findings kept",
         oversize["complete"] is False and oversize["status"] == "review"
         and "declares %d bytes but %d are present" % (len(WEBP_XMP) + 2, len(WEBP_XMP))
         in oversize["note"]),
        ("bytes after the container: not read, findings kept", trailing["complete"] is False
         and trailing["status"] == "review" and "after the WebP container" in trailing["note"]),
        ("container size below header", tiny["status"] == "incomplete"),
        ("header itself truncated: not recognized as WebP, never clean",
         header_only["status"] == "not inspected" and header_only["complete"] is False),
        ("findings before a broken chunk kept", later_break["status"] == "review"
         and later_break["complete"] is False
         and ("identity", "Artist", "E. Webpauthor") in later_break["items"]))
    return ok, why


@case("I17. F2: valid WebP positive controls are read completely")
def i17(tmp):
    rec = one({"word/media/image1.webp": WEBP_XMP})
    exif = tiff([ascii_tag(0x013B, "E. Webpauthor")]) + b"\x00"      # odd length, padded
    xmp = xmp_segment('><dc:creator><rdf:Seq><rdf:li>F. Second</rdf:li></rdf:Seq></dc:creator>')[1]
    built = riff([(b"VP8L", b"\x00" * 5), (b"EXIF", exif), (b"XMP ", xmp[29:])])
    rec2 = one({"word/media/image2.webp": built})
    vals = {v for _, _, v in rec2["items"]}
    ok, why = checks(
        ("Pillow WebP: review", rec["status"] == "review"),
        ("Pillow WebP: creator", ("identity", "creator", "Q. Inspector") in rec["items"]),
        ("Pillow WebP: complete", rec["complete"] is True),
        ("built WebP odd chunks padded", len(exif) % 2 == 1),
        ("built WebP: both blocks read", {"E. Webpauthor", "F. Second"} <= vals),
        ("built WebP: complete", rec2["complete"] is True and rec2["note"]
         == "metadata blocks read: EXIF, XMP"))
    return ok, why + " " + repr(rec2)


EXT_XMP = (0xE1, b"http://ns.adobe.com/xmp/extension/\x00" + b"0" * 32
           + struct.pack(">II", 20, 0) + b"<x:xmpmeta>...</x:x>")


@case("I18. F3: an image with a finding and an unread block is counted as not fully inspected (QA case)")
def i18(tmp):
    img = jpeg_with(xmp_segment('><dc:creator><rdf:Seq><rdf:li>Q. Inspector</rdf:li></rdf:Seq>'
                                '</dc:creator>'), EXT_XMP)
    rec = one({"word/media/image1.jpeg": img})
    broken = (BASE_JPEG[:2] + b"\xff\xe1" + struct.pack(">H", 2 + len(exif_segment(tiff(
        [ascii_tag(0x013B, "D. Author")]))[1])) + exif_segment(tiff([ascii_tag(0x013B, "D. Author")]))[1]
        + b"\xff\xe2\x7f\xff" + b"short")
    rec_b = one({"word/media/image2.jpeg": broken})
    mixed = [one({"word/media/a.jpeg": jpeg_with(exif_segment(tiff([], gps=gps_ifd())))}),
             rec, one({"word/media/c.jpeg": BASE_JPEG}),
             one({"word/media/d.gif": b"GIF89a\x01\x00\x01\x00\x00\x00\x00;"})]
    text, mtext = text_of([rec]), text_of(mixed)
    ok, why = checks(
        ("finding kept", ("identity", "creator", "Q. Inspector") in rec["items"]),
        ("status review", rec["status"] == "review"),
        ("not complete", rec["complete"] is False),
        ("detail names the unread block", "present but not read: extended XMP" in rec["note"]),
        ("line flags incomplete", "review finding; inspection incomplete" in text),
        ("count line", "Not fully inspected: 1, of which 1 also have findings" in text),
        ("summary", "1 image(s) needing review, 1 image(s) not fully inspected" in text),
        ("finding before a malformed segment kept", rec_b["status"] == "review"
         and ("identity", "Artist", "D. Author") in rec_b["items"] and not rec_b["complete"]
         and "read before the failure: EXIF" in rec_b["note"]),
        ("mixed set: count line", "review findings 2, metadata present 0, none found 1, "
         "not inspected 1, incomplete 0. Not fully inspected: 2, of which 1" in mtext),
        ("mixed set: summary agrees", "2 image(s) needing review, 2 image(s) not fully inspected"
         in mtext))
    return ok, why + " " + mtext


def gps_xmp(lat, lon, element=False):
    if element:
        return xmp_segment('xmlns:exif="%s"><exif:GPSLatitude>%s</exif:GPSLatitude>'
                           '<exif:GPSLongitude>%s</exif:GPSLongitude>' % (NS_EXIF, lat, lon))
    return xmp_segment('xmlns:exif="%s" exif:GPSLatitude="%s" exif:GPSLongitude="%s">'
                       % (NS_EXIF, lat, lon))


@case("I19. F5: XMP GPS in degrees,minutes and degrees,minutes,seconds with N/S/E/W")
def i19(tmp):
    rec = one({"word/media/image1.jpeg": jpeg_with(gps_xmp("12,34.800000N", "123,45.600000E"))})
    text = text_of([rec])
    el = text_of([one({"word/media/image2.jpeg": jpeg_with(gps_xmp("12,34,56S", "123,45,6W",
                                                                   element=True))})])

    def val(v, axis):
        c = ic.xmp_coordinate(v, axis)
        return c.lat if axis == "lat" else c.lon
    ok, why = checks(
        ("QA case form, latitude", "GPSLatitude = 12.58 (rounded)" in text),
        ("QA case form, longitude", "GPSLongitude = 123.76 (rounded)" in text),
        ("raw minutes not shown", "34.8" not in text and "45.6" not in text),
        ("D,M.m N", abs(val("12,34.800000N", "lat") - 12.58) < 1e-9),
        ("D,M.m E", abs(val("123,45.600000E", "lon") - 123.76) < 1e-9),
        ("D,M,S N", abs(val("12,34,56N", "lat") - DMS_LAT) < 1e-9),
        ("D,M,S S negative", abs(val("12,34,56S", "lat") + DMS_LAT) < 1e-9),
        ("D,M,S E", abs(val("123,45,6E", "lon") - DMS_LON) < 1e-9),
        ("D,M,S W negative", abs(val("123,45,6W", "lon") + DMS_LON) < 1e-9),
        ("D,M.m S negative", abs(val("45,12.6S", "lat") + 45.21) < 1e-9),
        ("D,M.m W negative", abs(val("67,8.4W", "lon") + 67.14) < 1e-9),
        ("whole minutes", abs(val("12,34N", "lat") - (12 + 34 / 60)) < 1e-9),
        ("lower-case direction", abs(val("12,34,56n", "lat") - DMS_LAT) < 1e-9),
        ("element form, S and W", "GPSLatitude = -12.58 (rounded)" in el
         and "GPSLongitude = -123.75 (rounded)" in el))
    return ok, why + " " + text + el


@case("I20. F5: malformed XMP GPS values are withheld, never shown raw")
def i20(tmp):
    bad = [("12.582222N", "lat"), ("12,34.8", "lat"), ("12,34.8X", "lat"), ("12,75.0N", "lat"),
           ("12,34,75N", "lat"), ("95,0.0N", "lat"), ("181,0.0E", "lon"), ("123,45.6N", "lon"),
           ("12,34.8E", "lat"), ("-12,34.8N", "lat"), ("abc", "lat"), ("12,34.8.1N", "lat"),
           ("12,34.5,10N", "lat"), ("", "lat")]
    results = [(v, a, ic.xmp_coordinate(v, a)) for v, a in bad]
    rec = one({"word/media/image1.jpeg": jpeg_with(gps_xmp("12.582222N", "123,45.6N"))})
    text = text_of([rec])
    ok, why = checks(
        *[("withheld: %r as %s" % (v, a), isinstance(r, ic.Withheld)) for v, a, r in results],
        ("finding still reported", rec["status"] == "review" and "[REVIEW] location, GPSLatitude"
         in text and "[REVIEW] location, GPSLongitude" in text),
        ("value withheld in the log", text.count("value withheld") == 2),
        ("no raw value in the log", "12.5822" not in text and "123,45" not in text
         and "45.6" not in text),
        ("reasons contain no digits", not any(ch.isdigit() for _, _, r in results
                                              for ch in r.reason)))
    return ok, why + " " + text


@case("I21. F5: EXIF GPS reporting is unchanged; S and W are negative; bad values are withheld")
def i21(tmp):
    ne = text_of([one({"word/media/a.jpeg": jpeg_with(exif_segment(tiff([], gps=gps_ifd())))})])
    sw_gps = [(0x0001, 2, 2, b"S\x00"), (0x0002, 5, 3, rational(12, 34, 56.0)),
              (0x0003, 2, 2, b"W\x00"), (0x0004, 5, 3, rational(123, 45, 6.0))]
    sw = text_of([one({"word/media/b.jpeg": jpeg_with(exif_segment(tiff([], gps=sw_gps)))})])
    bad_gps = [(0x0001, 2, 2, b"N\x00"), ascii_tag(0x0002, "12.5822 N"),
               (0x0003, 2, 2, b"E\x00"), (0x0004, 5, 3, rational(123, 45, 6.0))]
    bad = text_of([one({"word/media/c.jpeg": jpeg_with(exif_segment(tiff([], gps=bad_gps)))})])
    saved = ic.INSPECTORS["JPEG"]

    def leaky(b, items, sources):
        raise ValueError("could not convert string to float: '12.582222 N'")
    ic.INSPECTORS["JPEG"] = leaky
    try:
        err = one({"word/media/d.jpeg": BASE_JPEG})
    finally:
        ic.INSPECTORS["JPEG"] = saved
    ok, why = checks(
        ("parser error text not shown", err["status"] == "incomplete" and "12.5822" not in
         err["note"] and "(ValueError)" in err["note"]),
        ("N/E as before (I1)", "GPS position = 12.58, 123.75 (rounded)" in ne),
        ("S/W negative", "GPS position = -12.58, -123.75 (rounded)" in sw),
        ("uninterpretable EXIF GPS withheld", "GPS position = value withheld" in bad),
        ("no raw EXIF value", "12.5822" not in bad),
        ("still a review finding", "review findings 1" in bad))
    return ok, why + " " + ne + sw + bad


def defaults_docx(vanish, styles_extra="", body=None):
    rpr = "<w:rPr>%s</w:rPr>" % vanish if vanish is not None else "<w:rPr/>"
    styles = ('<w:docDefaults><w:rPrDefault>%s</w:rPrDefault></w:docDefaults>%s'
              % (rpr, styles_extra))
    return revision_docx(body or '<w:p><w:r><w:t>Plain</w:t></w:r></w:p>', styles)


DEFAULT_KIND = "document default formatting hides text"


@case("R12. F4: hiding through w:docDefaults/w:rPrDefault/w:rPr/w:vanish is reported (QA case)")
def r12(tmp):
    forms = ['<w:vanish/>', '<w:vanish w:val="true"/>', '<w:vanish w:val="1"/>',
             '<w:vanish w:val="on"/>']
    res = [(f, rev_findings(defaults_docx(f))) for f in forms]
    ok, why = checks(
        *[("enabled %s" % f, any(k.startswith(DEFAULT_KIND) and c == ic.UNCLASSIFIED
                                 for k, _, c, _, _ in fl))
          for f, (fl, _, _) in res],
        ("owner review action", "the owner checks which text inherits this default" in res[0][1][2]),
        ("does not claim all text is hidden", "all text" not in res[0][1][2]
         and "was not resolved" in res[0][1][2]),
        ("counted once", sum(1 for k, _, _, _, _ in res[0][1][0] if k.startswith(DEFAULT_KIND)) == 1))
    return ok, why + " " + res[0][1][2]


@case("R13. F4: default hiding switched off, or absent, is not reported")
def r13(tmp):
    forms = ['<w:vanish w:val="0"/>', '<w:vanish w:val="false"/>', '<w:vanish w:val="off"/>',
             None, '<w:b/>']
    res = [(f, rev_findings(defaults_docx(f))[0]) for f in forms]
    para = revision_docx('<w:p><w:r><w:t>Plain</w:t></w:r></w:p>',
                         '<w:docDefaults><w:pPrDefault><w:pPr><w:rPr><w:vanish/></w:rPr></w:pPr>'
                         '</w:pPrDefault></w:docDefaults>')
    return checks(
        *[("disabled or absent: %s" % f, not any(k.startswith(DEFAULT_KIND) for k, _, _, _, _ in fl))
          for f, fl in res],
        ("paragraph-mark default is not run default",
         not any(k.startswith(DEFAULT_KIND) for k, _, _, _, _ in rev_findings(para)[0])))


@case("R14. F4: explicit overrides are counted, and a run set visible is not reported as hidden")
def r14(tmp):
    styles = ('<w:style w:type="paragraph" w:styleId="Visible"><w:rPr><w:vanish w:val="0"/>'
              '</w:rPr></w:style><w:style w:type="character" w:styleId="StillHidden"><w:rPr>'
              '<w:vanish/></w:rPr></w:style>')
    body = ('<w:p><w:r><w:rPr><w:vanish w:val="false"/></w:rPr><w:t>shown on purpose</w:t></w:r>'
            '<w:r><w:rPr><w:vanish/></w:rPr><w:t>hidden on purpose</w:t></w:r></w:p>')
    f, p, text = rev_findings(defaults_docx('<w:vanish/>', styles, body))
    kinds = [k for k, _, _, _, _ in f]
    return checks(
        ("default reported", any(k.startswith(DEFAULT_KIND) for k in kinds)),
        ("style override counted and named", "1 style(s) (Visible)" in text),
        ("run override counted", "and 1 run(s)" in text),
        ("explicit hidden run still reported", kinds.count("hidden text") == 1
         and "hidden on purpose" in text),
        ("visible run not reported as hidden", "shown on purpose" not in text),
        ("hiding style still reported", "style hides its text: StillHidden" in text))


@case("R15. F4: default hiding through metadata_hygiene.py is reported, report-only and PASS")
def r15(tmp):
    src = os.path.join(tmp, "defaults.docx")
    base = os.path.join(tmp, "base.docx")
    parts = defaults_docx('<w:vanish/>')
    write_zip(src, parts)
    shutil.copy(src, base)
    before = sha(open(src, "rb").read())
    out = os.path.join(tmp, "clean.docx")
    c1, o1 = run(HYGIENE, src, "--baseline", base)
    log_scan = open(os.path.join(tmp, "defaults_metahygiene.md"), encoding="utf-8").read()
    c2, o2 = run(HYGIENE, src, "--clean", "--baseline", base, "-o", out)
    cand = read_zip(out)
    return checks(
        ("scan logs the finding", DEFAULT_KIND in log_scan),
        ("scan summary counts it", "1 revision or hidden-content finding(s)" in o1),
        ("clean PASS", c2 == 0 and "hygiene result: PASS" in o2),
        ("styles.xml unchanged", cand.get("word/styles.xml") == parts["word/styles.xml"]),
        ("document.xml unchanged", cand.get("word/document.xml") == parts["word/document.xml"]),
        ("source unchanged", sha(open(src, "rb").read()) == before))


@case("I22. F1-F3, F5 through metadata_hygiene.py: logged, counted, report-only, PASS")
def i22(tmp):
    imgs = {"word/media/f1.tif": TIFF_XMP700,
            "word/media/f2.webp": WEBP_XMP[:XMP_TYPE + 4],
            "word/media/f3.jpeg": jpeg_with(xmp_segment(
                '><dc:creator><rdf:Seq><rdf:li>Q. Inspector</rdf:li></rdf:Seq></dc:creator>'),
                EXT_XMP),
            "word/media/f5.jpeg": jpeg_with(gps_xmp("12,34.800000N", "123,45.600000E"))}
    parts = docx_with_images(imgs)
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        b"</Types>", b'<Default Extension="tif" ContentType="image/tiff"/>'
        b'<Default Extension="webp" ContentType="image/webp"/></Types>')
    src = os.path.join(tmp, "images.docx")
    base = os.path.join(tmp, "base.docx")
    write_zip(src, parts)
    shutil.copy(src, base)
    before = sha(open(src, "rb").read())
    c1, o1 = run(HYGIENE, src, "--baseline", base)
    log = open(os.path.join(tmp, "images_metahygiene.md"), encoding="utf-8").read()
    out = os.path.join(tmp, "clean.docx")
    c2, o2 = run(HYGIENE, src, "--clean", "--baseline", base, "-o", out)
    cand = read_zip(out)
    return checks(
        ("F1 tag 700 read", "f1.tif (TIFF): review finding. metadata blocks read: EXIF, "
         "XMP (TIFF tag 700)" in log),
        ("F2 truncation incomplete", "f2.webp (WebP): inspection incomplete" in log),
        ("F3 finding plus incomplete", "f3.jpeg (JPEG): review finding; inspection incomplete"
         in log),
        ("F5 rounded", "GPSLatitude = 12.58 (rounded)" in log and "12,34" not in log),
        ("count line", "review findings 3, metadata present 0, none found 0, not inspected 0, "
         "incomplete 1. Not fully inspected: 2, of which 1" in log),
        ("stdout summary agrees", "3 image(s) needing review, 2 image(s) not fully inspected"
         in o1),
        ("clean PASS despite findings", c2 == 0 and "hygiene result: PASS" in o2),
        ("images byte-identical", all(cand.get(k) == v for k, v in imgs.items())),
        ("source unchanged", sha(open(src, "rb").read()) == before))


# ---------------------------------------------------------------- Rev36 correction
#
# Free-text location metadata is text. Coordinate handling applies only to the
# fields a schema defines as GPS coordinates. All values below are synthetic
# test values, selected for software testing only and not intended to identify
# any real-world location, project, organization or document.

GENERIC_LOCATIONS = [
    "Building A, Section B", "Zone Alpha, Building Beta", "Example City, Example Country",
    "Area A; Package B", "Plot A, Zone B", "Level A, Building B", "Block 12, Level 3",
    "Unit 4; Floor 2", "Zone 7, Gate 9", "Area 1.5, Zone 2.25", "Site 3, 4", "12, 34",
    "Facility 7-B; Gate 2", "Region X, Country Y 10", "Section 5 N, Plot 6 E", "10.5; 20.25"]

IPTC_LOCATION_FIELDS = [(90, "City"), (92, "Sub-location"), (95, "Province-State"),
                        (100, "Country Code"), (101, "Country")]
XMP_LOCATION_FIELDS = [("photoshop", "http://ns.adobe.com/photoshop/1.0/", "City"),
                       ("photoshop", "http://ns.adobe.com/photoshop/1.0/", "State"),
                       ("photoshop", "http://ns.adobe.com/photoshop/1.0/", "Country"),
                       ("Iptc4xmpCore", "http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/", "Location"),
                       ("Iptc4xmpCore", "http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/", "CountryCode")]


def xmp_fields(pairs):
    """An XMP segment with (prefix, uri, local, value) attributes."""
    decl = {}
    attrs = []
    for prefix, uri, local, value in pairs:
        decl[prefix] = uri
        attrs.append('%s:%s="%s"' % (prefix, local, value))
    return xmp_segment(" ".join('xmlns:%s="%s"' % kv for kv in decl.items()) + " "
                       + " ".join(attrs) + ">")


def location_lines(rec):
    return [ln for ln in ic.report_lines([rec], [], []) if "[REVIEW] location" in ln]


@case("I23. Rev36: generic IPTC and XMP location text with numbers and punctuation stays text")
def i23(tmp):
    results = []
    for ds, name in IPTC_LOCATION_FIELDS:
        rows = []
        for v in GENERIC_LOCATIONS:
            rec = one({"word/media/i.jpeg": jpeg_with(iptc_segment([(ds, v.encode())]))})
            rows.append((v, rec))
        results.append(("IPTC " + name, rows))
    for prefix, uri, local in XMP_LOCATION_FIELDS:
        rows = []
        for v in GENERIC_LOCATIONS:
            rec = one({"word/media/x.jpeg": jpeg_with(xmp_fields([(prefix, uri, local, v)]))})
            rows.append((v, rec))
        results.append(("XMP %s:%s" % (prefix, local), rows))
    pairs = []
    for field, rows in results:
        pairs.append(("%s: never a coordinate value" % field, all(
            len(r["items"]) == 1 and isinstance(r["items"][0][2], str)
            and not isinstance(r["items"][0][2], (ic.Coordinates, ic.Withheld)) for _, r in rows)))
        pairs.append(("%s: no fabricated coordinate" % field, all(
            "(rounded)" not in " ".join(location_lines(r)) for _, r in rows)))
        pairs.append(("%s: text preserved exactly" % field, all(
            len(location_lines(r)) == 1 and ("= %s; " % v) in location_lines(r)[0]
            for v, r in rows)))
    long_text = "Level A, Building B, Zone C, Area D, Plot E, Section F, Unit 12, Floor 3"
    long_rec = one({"word/media/l.jpeg": jpeg_with(iptc_segment([(92, long_text.encode())]))})
    long_line = location_lines(long_rec)[0]
    pairs.append(("existing 60-character control still applies to long text",
                  ("= %s...; " % long_text[:57]) in long_line and "(rounded)" not in long_line))
    return checks(*pairs)


@case("I24. Rev36: explicit GPS fields keep the F5 handling; generic text never enters the GPS parser")
def i24(tmp):
    ps = ("photoshop", "http://ns.adobe.com/photoshop/1.0/")
    core = ("Iptc4xmpCore", "http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/")
    ex = ("exif", NS_EXIF)
    img = jpeg_with(exif_segment(tiff([], gps=gps_ifd())),
                    iptc_segment([(90, b"Block 12, Level 3")]),
                    xmp_fields([ps + ("City", "12, 34"), core + ("Location", "Area 1.5, Zone 2.25"),
                                ex + ("GPSLatitude", "12,34.800000N"),
                                ex + ("GPSLongitude", "123,45.600000E")]))
    rec = one({"word/media/m.jpeg": img})
    text = "\n".join(location_lines(rec))
    by_field = {f: v for _, f, v in rec["items"]}
    wrong = one({"word/media/w.jpeg": jpeg_with(xmp_fields([
        ex + ("GPSLatitude", "Block 12, Level 3"), ex + ("GPSLongitude", "181,0.0E")]))})
    wtext = "\n".join(location_lines(wrong))
    range_bad = ic.xmp_coordinate("95,0.0N", "lat")
    axis_bad = ic.xmp_coordinate("123,45.6N", "lon")
    calls = []
    real = ic.xmp_coordinate

    def spy(value, axis):
        calls.append(value)
        return real(value, axis)
    ic.xmp_coordinate = spy
    try:
        ic.parse_xmp(xmp_fields([ps + ("City", "12, 34"), ps + ("State", "10.5; 20.25"),
                                 core + ("Location", "Section 5 N, Plot 6 E")])[1])
        generic_calls = len(calls)
        ic.parse_xmp(xmp_fields([ex + ("GPSLatitude", "12,34.800000N"),
                                 ex + ("GPSLongitude", "123,45.600000E")])[1])
        gps_calls = len(calls) - generic_calls
    finally:
        ic.xmp_coordinate = real
    return checks(
        ("EXIF GPS rounded", "GPS position = 12.58, 123.75 (rounded)" in text),
        ("XMP GPS latitude rounded", "GPSLatitude = 12.58 (rounded)" in text),
        ("XMP GPS longitude rounded", "GPSLongitude = 123.76 (rounded)" in text),
        ("only the three explicit GPS values are rounded", text.count("(rounded)") == 3),
        ("explicit GPS values are Coordinates", isinstance(by_field["GPS position"], ic.Coordinates)
         and isinstance(by_field["GPSLatitude"], ic.Coordinates)),
        ("IPTC City stays text", "IPTC City = Block 12, Level 3; " in text),
        ("XMP City stays text", "City = 12, 34; " in text and by_field["City"] == "12, 34"),
        ("XMP Location stays text", "Location = Area 1.5, Zone 2.25; " in text),
        ("text in a GPS field is withheld, not shown", "GPSLatitude = value withheld" in wtext
         and "Block 12" not in wtext),
        ("out-of-range longitude withheld", "GPSLongitude = value withheld" in wtext),
        ("out-of-range latitude not accepted", isinstance(range_bad, ic.Withheld)),
        ("wrong direction for the axis not accepted", isinstance(axis_bad, ic.Withheld)),
        ("generic fields never reach the GPS parser", generic_calls == 0),
        ("GPS fields do reach it", gps_calls == 2),
        ("safe_value keeps location text", ic.safe_value(ic.LOCATION, "12, 34") == "12, 34"
         and ic.safe_value(ic.LOCATION, "10.5; 20.25") == "10.5; 20.25"),
        ("safe_value rounds only Coordinates", ic.safe_value(
            ic.LOCATION, ic.Coordinates(DMS_LAT, DMS_LON)) == "12.58, 123.75 (rounded)"),
        ("safe_value never shows a Withheld value", ic.safe_value(
            ic.LOCATION, ic.Withheld("coordinate format not recognized")).startswith("value withheld")))


@case("I25. Rev36: through metadata_hygiene.py, location text is logged as written and GPS rounded")
def i25(tmp):
    img = jpeg_with(iptc_segment([(90, b"Block 12, Level 3"), (95, b"Unit 4; Floor 2")]),
                    xmp_fields([("exif", NS_EXIF, "GPSLatitude", "12,34.800000N"),
                                ("exif", NS_EXIF, "GPSLongitude", "123,45.600000E")]))
    parts = docx_with_images({"word/media/image1.jpeg": img})
    src = os.path.join(tmp, "loc.docx")
    base = os.path.join(tmp, "base.docx")
    write_zip(src, parts)
    shutil.copy(src, base)
    before = sha(open(src, "rb").read())
    c1, o1 = run(HYGIENE, src, "--baseline", base)
    log = open(os.path.join(tmp, "loc_metahygiene.md"), encoding="utf-8").read()
    out = os.path.join(tmp, "clean.docx")
    c2, o2 = run(HYGIENE, src, "--clean", "--baseline", base, "-o", out)
    return checks(
        ("City logged as written", "IPTC City = Block 12, Level 3; " in log),
        ("Province-State logged as written", "IPTC Province-State = Unit 4; Floor 2; " in log),
        ("no fabricated coordinate (the Rev35 output)", "12.00, 3.00" not in log
         and "4.00, 2.00" not in log),
        ("GPS rounded", "GPSLatitude = 12.58 (rounded)" in log
         and "GPSLongitude = 123.76 (rounded)" in log),
        ("no raw GPS value", "12,34.8" not in log and "123,45.6" not in log),
        ("clean PASS", c2 == 0 and "hygiene result: PASS" in o2),
        ("image byte-identical", read_zip(out).get("word/media/image1.jpeg") == img),
        ("source and baseline unchanged", sha(open(src, "rb").read()) == before
         and sha(open(base, "rb").read()) == before))


def main():
    failures = 0
    for name, fn in CASES:
        tmp = tempfile.mkdtemp(prefix="inspecttest_")
        try:
            ok, detail = fn(tmp)
        except Exception as e:
            ok, detail = False, "raised %r" % e
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print("%s  %s%s" % ("pass" if ok else "FAIL", name, "" if ok else "  [%s]" % str(detail)[:400]))
        failures += 0 if ok else 1
    print("\n%d case(s) run, %d failure(s)" % (len(CASES), failures))
    print("%d subcheck(s) within the 18 Rev35 and Rev36 cases (I12-I25, R12-R15); the 22 "
          "earlier cases each return one combined assertion" % SUBCHECKS[0])
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
