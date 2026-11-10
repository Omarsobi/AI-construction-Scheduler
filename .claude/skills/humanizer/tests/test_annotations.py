#!/usr/bin/env python3
"""Permanent regression suite for the annotation rule in metadata_hygiene.py.

Every fixture is generated here from scratch. No project document is used and
none is shipped. Run from anywhere:

    python tests/test_annotations.py            # AI Fix copy
    python tests/test_annotations.py --docx     # the Word subset only

Exit status 0 when every case passes, 1 otherwise.
"""

import argparse
import importlib.util
import io
import xml.etree.ElementTree as ET
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "metadata_hygiene.py")

SS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
OFF = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
TC = "http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
W15 = "http://schemas.microsoft.com/office/word/2012/wordml"


def strip_comments(parts):
    """Remove the comment parts and everything that declares or references them."""
    parts = dict(parts)
    for part in ("word/comments.xml", "word/commentsExtended.xml",
                 "word/commentsIds.xml", "word/commentsExtensible.xml"):
        parts.pop(part, None)
    raw = parts["word/document.xml"]
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = raw.decode("utf-16")
        parts["word/document.xml"] = re.sub(
            r"<w:commentRange\w+ w:id=\"1\"/>|<w:r><w:commentReference w:id=\"1\"/></w:r>",
            "", text).encode("utf-16")
    else:
        parts["word/document.xml"] = re.sub(
            r"<w:commentRange\w+ w:id=\"1\"/>|<w:r><w:commentReference w:id=\"1\"/></w:r>",
            "", raw.decode()).encode()
    parts["word/_rels/document.xml.rels"] = (
        '<?xml version="1.0"?><Relationships xmlns="%s"></Relationships>' % PKG).encode()
    ct = parts["[Content_Types].xml"].decode()
    ct = re.sub(r'<Override PartName="/word/comments[^>]*?/>', "", ct)
    parts["[Content_Types].xml"] = ct.encode()
    return parts


def local(tag):
    return tag.split(":")[-1]


def write_zip(path, parts):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)


def read_zip(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def xlsx_with_comment(text="Reviewer note", author="Reviewer", shape_id="_x0000_s1026"):
    """A minimal workbook with one legacy cell comment on Sheet1!A1."""
    parts = {
        "[Content_Types].xml":
            ('<?xml version="1.0"?><Types xmlns="%s">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
             'relationships+xml"/>'
             '<Default Extension="vml" ContentType="application/vnd.openxmlformats-'
             'officedocument.vmlDrawing"/>'
             '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
             'officedocument.spreadsheetml.sheet.main+xml"/>'
             '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.'
             'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
             '<Override PartName="/xl/comments1.xml" ContentType="application/vnd.'
             'openxmlformats-officedocument.spreadsheetml.comments+xml"/>'
             '</Types>' % CT),
        "_rels/.rels":
            ('<?xml version="1.0"?><Relationships xmlns="%s">'
             '<Relationship Id="rId1" Type="%s/officeDocument" Target="xl/workbook.xml"/>'
             '</Relationships>' % (PKG, OFF)),
        "xl/workbook.xml":
            ('<?xml version="1.0"?><workbook xmlns="%s" xmlns:r="%s"><sheets>'
             '<sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % (SS, OFF)),
        "xl/_rels/workbook.xml.rels":
            ('<?xml version="1.0"?><Relationships xmlns="%s">'
             '<Relationship Id="rId1" Type="%s/worksheet" Target="worksheets/sheet1.xml"/>'
             '</Relationships>' % (PKG, OFF)),
        "xl/worksheets/sheet1.xml":
            ('<?xml version="1.0"?><worksheet xmlns="%s" xmlns:r="%s"><sheetData>'
             '<row r="1"><c r="A1"><v>1</v></c></row>'
             '<row r="2"><c r="A2"><f>A1*2</f></c></row></sheetData>'
             '<legacyDrawing r:id="rId2"/></worksheet>' % (SS, OFF)),
        "xl/worksheets/_rels/sheet1.xml.rels":
            ('<?xml version="1.0"?><Relationships xmlns="%s">'
             '<Relationship Id="rId1" Type="%s/comments" Target="../comments1.xml"/>'
             '<Relationship Id="rId2" Type="%s/vmlDrawing" Target="../drawings/vml1.vml"/>'
             '</Relationships>' % (PKG, OFF, OFF)),
        "xl/comments1.xml":
            ('<?xml version="1.0"?><comments xmlns="%s"><authors><author>%s</author></authors>'
             '<commentList><comment ref="A1" authorId="0"><text><t>%s</t></text></comment>'
             '</commentList></comments>' % (SS, author, text)),
        "xl/drawings/vml1.vml":
            ('<xml xmlns:v="urn:schemas-microsoft-com:vml" '
             'xmlns:x="urn:schemas-microsoft-com:office:excel">'
             '<v:shape id="%s" type="#_x0000_t202"><x:ClientData ObjectType="Note">'
             '<x:Row>0</x:Row><x:Column>0</x:Column></x:ClientData></v:shape></xml>' % shape_id),
    }
    return {k: v.encode("utf-8") for k, v in parts.items()}


def xlsx_threaded(display="Reviewer", provider="pvd1", text="Existing thread"):
    parts = xlsx_with_comment()
    parts["xl/persons/person.xml"] = (
        '<?xml version="1.0"?><personList xmlns="%s">'
        '<person displayName="%s" id="{P1}" userId="u1" providerId="%s"/></personList>'
        % (TC, display, provider)).encode()
    parts["xl/threadedComments/tc1.xml"] = (
        '<?xml version="1.0"?><ThreadedComments xmlns="%s">'
        '<threadedComment ref="C1" dT="2026-09-01T00:00:00" personId="{P1}" id="{T1}">'
        '<text>%s</text></threadedComment></ThreadedComments>' % (TC, text)).encode()
    rels = parts["xl/worksheets/_rels/sheet1.xml.rels"].decode().replace(
        "</Relationships>",
        '<Relationship Id="rId3" Type="%s/threadedComment" '
        'Target="../threadedComments/tc1.xml"/></Relationships>' % OFF)
    parts["xl/worksheets/_rels/sheet1.xml.rels"] = rels.encode()
    return parts


def docx_with_comment(done="0", body_text="Body text"):
    parts = {
        "[Content_Types].xml":
            ('<?xml version="1.0"?><Types xmlns="%s">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
             'relationships+xml"/>'
             '<Override PartName="/word/document.xml" ContentType="application/vnd.'
             'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
             '<Override PartName="/word/comments.xml" ContentType="application/vnd.'
             'openxmlformats-officedocument.wordprocessingml.comments+xml"/>'
             '</Types>' % CT),
        "_rels/.rels":
            ('<?xml version="1.0"?><Relationships xmlns="%s">'
             '<Relationship Id="rId1" Type="%s/officeDocument" Target="word/document.xml"/>'
             '</Relationships>' % (PKG, OFF)),
        "word/document.xml":
            ('<?xml version="1.0"?><w:document xmlns:w="%s"><w:body><w:p><w:r><w:t>%s</w:t>'
             '</w:r></w:p><w:commentRangeStart w:id="1"/><w:commentRangeEnd w:id="1"/>'
             '<w:r><w:commentReference w:id="1"/></w:r></w:body></w:document>' % (W, body_text)),
        "word/_rels/document.xml.rels":
            ('<?xml version="1.0"?><Relationships xmlns="%s">'
             '<Relationship Id="rIdC" Type="%s/comments" Target="comments.xml"/>'
             '</Relationships>' % (PKG, OFF)),
        "word/comments.xml":
            ('<?xml version="1.0"?><w:comments xmlns:w="%s" xmlns:w14="%s">'
             '<w:comment w:id="1" w:author="Reviewer"><w:p w14:paraId="AAAA1111">'
             '<w:r><w:t>Reviewer note</w:t></w:r></w:p></w:comment></w:comments>' % (W, W14)),
        "word/commentsExtended.xml":
            ('<?xml version="1.0"?><w15:commentsEx xmlns:w15="%s" xmlns:w14="%s">'
             '<w15:commentEx w14:paraId="AAAA1111" w15:done="%s"/></w15:commentsEx>'
             % (W15, W14, done)),
        "word/commentsIds.xml":
            ('<?xml version="1.0"?><w16cid:commentsIds xmlns:w16cid="http://x" xmlns:w14="%s">'
             '<w16cid:commentId w14:paraId="AAAA1111" w16cid:durableId="11111111"/>'
             '</w16cid:commentsIds>' % W14),
        "word/commentsExtensible.xml":
            ('<?xml version="1.0"?><w16cex:commentsExtensible xmlns:w16cex="http://y">'
             '<w16cex:commentExtensible w16cex:durableId="11111111"/>'
             '</w16cex:commentsExtensible>'),
    }
    return {k: v.encode("utf-8") for k, v in parts.items()}


def run(path, baseline=None, clean=True, out=None):
    cmd = [sys.executable, SCRIPT, path]
    if clean:
        cmd.append("--clean")
    if out:
        cmd += ["-o", out]
    if baseline:
        cmd += ["--baseline", baseline]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    return p.returncode, p.stdout + p.stderr


CASES = []


def case(name, docx_only=False):
    def deco(fn):
        CASES.append((name, fn, docx_only))
        return fn
    return deco


@case("1. whitespace inside an existing comment is preserved exactly")
def case_whitespace(tmp):
    base = os.path.join(tmp, "b.xlsx")
    work = os.path.join(tmp, "w.xlsx")
    out = os.path.join(tmp, "o.xlsx")
    write_zip(base, xlsx_with_comment(text="Hello  world"))
    write_zip(work, xlsx_with_comment(text="Hello world"))
    code, log = run(work, base, out=out)
    got = read_zip(out)["xl/comments1.xml"].decode()
    return code == 0 and "Hello  world" in got, "exit %s" % code


@case("2. person providerId altered is restored")
def case_provider(tmp):
    base = os.path.join(tmp, "b.xlsx")
    work = os.path.join(tmp, "w.xlsx")
    out = os.path.join(tmp, "o.xlsx")
    write_zip(base, xlsx_threaded(provider="pvd1"))
    write_zip(work, xlsx_threaded(provider="Claude"))
    code, log = run(work, base, out=out)
    got = read_zip(out)["xl/persons/person.xml"].decode()
    return code == 0 and "Claude" not in got and "pvd1" in got, "exit %s" % code


@case("3. Word commentsExtended record altered is restored", docx_only=True)
def case_support(tmp):
    base = os.path.join(tmp, "b.docx")
    work = os.path.join(tmp, "w.docx")
    out = os.path.join(tmp, "o.docx")
    write_zip(base, docx_with_comment(done="0"))
    write_zip(work, docx_with_comment(done="1"))
    code, log = run(work, base, out=out)
    got = read_zip(out)["word/commentsExtended.xml"].decode()
    return code == 0 and 'done="0"' in got, "exit %s" % code


@case("4. VML note shape altered is restored")
def case_vml(tmp):
    base = os.path.join(tmp, "b.xlsx")
    work = os.path.join(tmp, "w.xlsx")
    out = os.path.join(tmp, "o.xlsx")
    write_zip(base, xlsx_with_comment(shape_id="_x0000_s1026"))
    write_zip(work, xlsx_with_comment(shape_id="CHANGED_BY_TOOL"))
    code, log = run(work, base, out=out)
    got = read_zip(out)["xl/drawings/vml1.vml"].decode()
    return code == 0 and "CHANGED_BY_TOOL" not in got, "exit %s" % code


@case("5. person displayName changed to a tool name is restored")
def case_display(tmp):
    base = os.path.join(tmp, "b.xlsx")
    work = os.path.join(tmp, "w.xlsx")
    out = os.path.join(tmp, "o.xlsx")
    write_zip(base, xlsx_threaded(display="Reviewer"))
    write_zip(work, xlsx_threaded(display="Claude"))
    code, log = run(work, base, out=out)
    got = read_zip(out)["xl/persons/person.xml"].decode()
    return code == 0 and "Claude" not in got, "exit %s" % code


@case("6. legacy author table reordered raises no false failure")
def case_reorder(tmp):
    base = os.path.join(tmp, "b.xlsx")
    work = os.path.join(tmp, "w.xlsx")
    out = os.path.join(tmp, "o.xlsx")
    write_zip(base, xlsx_with_comment())
    parts = xlsx_with_comment()
    parts["xl/comments1.xml"] = parts["xl/comments1.xml"].decode().replace(
        "<authors><author>Reviewer</author></authors>",
        "<authors><author>Someone Else</author><author>Reviewer</author></authors>").replace(
        'authorId="0"', 'authorId="1"').encode()
    write_zip(work, parts)
    code, log = run(work, base, out=out)
    return code == 0, "exit %s" % code


@case("7. a comment created during processing is removed with its infrastructure")
def case_added(tmp):
    base = os.path.join(tmp, "b.xlsx")
    work = os.path.join(tmp, "w.xlsx")
    out = os.path.join(tmp, "o.xlsx")
    bare = xlsx_with_comment()
    for part in ("xl/comments1.xml", "xl/drawings/vml1.vml"):
        bare.pop(part)
    bare["xl/worksheets/sheet1.xml"] = bare["xl/worksheets/sheet1.xml"].decode().replace(
        '<legacyDrawing r:id="rId2"/>', "").encode()
    bare["xl/worksheets/_rels/sheet1.xml.rels"] = (
        '<?xml version="1.0"?><Relationships xmlns="%s"></Relationships>' % PKG).encode()
    bare["[Content_Types].xml"] = bare["[Content_Types].xml"].decode().replace(
        '<Default Extension="vml" ContentType="application/vnd.openxmlformats-'
        'officedocument.vmlDrawing"/>', "").replace(
        '<Override PartName="/xl/comments1.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.comments+xml"/>', "").encode()
    write_zip(base, bare)
    write_zip(work, xlsx_with_comment(author="Claude", text="Added during processing"))
    code, log = run(work, base, out=out)
    got = read_zip(out)
    ok = (code == 0
          and "xl/comments1.xml" not in got
          and "xl/drawings/vml1.vml" not in got
          and "legacyDrawing" not in got["xl/worksheets/sheet1.xml"].decode()
          and 'Extension="vml"' not in got["[Content_Types].xml"].decode())
    return ok, "exit %s" % code


@case("8. a pre-existing comment is preserved untouched")
def case_kept(tmp):
    base = os.path.join(tmp, "b.xlsx")
    out = os.path.join(tmp, "o.xlsx")
    write_zip(base, xlsx_with_comment())
    work = os.path.join(tmp, "w.xlsx")
    shutil.copy(base, work)
    code, log = run(work, base, out=out)
    got = read_zip(out)["xl/comments1.xml"].decode()
    return code == 0 and "Reviewer note" in got, "exit %s" % code


@case("9. no inventory is never a pass, even with no annotation")
def case_no_baseline(tmp):
    work = os.path.join(tmp, "w.xlsx")
    out = os.path.join(tmp, "o.xlsx")
    parts = xlsx_with_comment()
    for part in ("xl/comments1.xml", "xl/drawings/vml1.vml"):
        parts.pop(part)
    write_zip(work, parts)
    code, log = run(work, None, out=out)
    return code == 2, "exit %s" % code


@case("10. a Word comment created during processing is removed with its anchors",
      docx_only=True)
def case_docx_added(tmp):
    base = os.path.join(tmp, "b.docx")
    work = os.path.join(tmp, "w.docx")
    out = os.path.join(tmp, "o.docx")
    write_zip(base, strip_comments(docx_with_comment()))
    write_zip(work, docx_with_comment())
    code, log = run(work, base, out=out)
    got = read_zip(out)
    ok = (code == 0
          and "word/comments.xml" not in got
          and "commentReference" not in got["word/document.xml"].decode()
          and "Body text" in got["word/document.xml"].decode())
    return ok, "exit %s" % code


@case("11. a deleted Word support part is restored", docx_only=True)
def case_support_deleted_part(tmp):
    base = os.path.join(tmp, "b.docx")
    work = os.path.join(tmp, "w.docx")
    out = os.path.join(tmp, "o.docx")
    write_zip(base, docx_with_comment())
    parts = docx_with_comment()
    parts.pop("word/commentsExtended.xml")
    write_zip(work, parts)
    code, log = run(work, base, out=out)
    got = read_zip(out)
    return (code == 0 and "word/commentsExtended.xml" in got
            and b'paraId="AAAA1111"' in got["word/commentsExtended.xml"]), "exit %s" % code


@case("12. a deleted VML note shape is restored")
def case_vml_deleted(tmp):
    base = os.path.join(tmp, "b.xlsx")
    work = os.path.join(tmp, "w.xlsx")
    out = os.path.join(tmp, "o.xlsx")
    write_zip(base, xlsx_with_comment())
    parts = xlsx_with_comment()
    parts["xl/drawings/vml1.vml"] = re.sub(
        r"<v:shape.*?</v:shape>", "", parts["xl/drawings/vml1.vml"].decode(),
        flags=re.S).encode()
    write_zip(work, parts)
    code, log = run(work, base, out=out)
    got = read_zip(out)["xl/drawings/vml1.vml"].decode()
    return code == 0 and 'ObjectType="Note"' in got, "exit %s" % code


@case("13. a support record added to an existing annotation is removed", docx_only=True)
def case_support_added(tmp):
    base = os.path.join(tmp, "b.docx")
    work = os.path.join(tmp, "w.docx")
    out = os.path.join(tmp, "o.docx")
    parts = docx_with_comment()
    bare = dict(parts)
    bare.pop("word/commentsExtensible.xml")
    bare["[Content_Types].xml"] = bare["[Content_Types].xml"]
    write_zip(base, bare)
    write_zip(work, parts)
    code, log = run(work, base, out=out)
    got = read_zip(out)
    return (code == 0 and "word/commentsExtensible.xml" not in got), "exit %s" % code


@case("14. a deleted legacyDrawing and its whole VML chain are restored")
def case_legacy_drawing(tmp):
    base = os.path.join(tmp, "b.xlsx")
    work = os.path.join(tmp, "w.xlsx")
    out = os.path.join(tmp, "o.xlsx")
    write_zip(base, xlsx_with_comment())
    parts = xlsx_with_comment()
    parts.pop("xl/drawings/vml1.vml")
    parts["xl/worksheets/sheet1.xml"] = parts["xl/worksheets/sheet1.xml"].decode().replace(
        '<legacyDrawing r:id="rId2"/>', "").encode()
    parts["xl/worksheets/_rels/sheet1.xml.rels"] = (
        '<?xml version="1.0"?><Relationships xmlns="%s">'
        '<Relationship Id="rId1" Type="%s/comments" Target="../comments1.xml"/>'
        '</Relationships>' % (PKG, OFF)).encode()
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].decode().replace(
        '<Default Extension="vml" ContentType="application/vnd.openxmlformats-'
        'officedocument.vmlDrawing"/>', "").encode()
    write_zip(work, parts)
    code, log = run(work, base, out=out)
    got = read_zip(out)
    sheet = got["xl/worksheets/sheet1.xml"].decode()
    rels = got["xl/worksheets/_rels/sheet1.xml.rels"].decode()
    ok = (code == 0
          and "xl/drawings/vml1.vml" in got
          and 'ObjectType="Note"' in got["xl/drawings/vml1.vml"].decode()
          and "legacyDrawing" in sheet
          and 'Id="rId2"' in rels
          and 'Extension="vml"' in got["[Content_Types].xml"].decode())
    return ok, "exit %s" % code


@case("15. a deleted legacyDrawing is restored at its baseline position")
def case_legacy_position(tmp):
    base = os.path.join(tmp, "b.xlsx")
    work = os.path.join(tmp, "w.xlsx")
    out = os.path.join(tmp, "o.xlsx")
    with_ext = xlsx_with_comment()
    with_ext["xl/worksheets/sheet1.xml"] = with_ext["xl/worksheets/sheet1.xml"].decode().replace(
        '<legacyDrawing r:id="rId2"/></worksheet>',
        '<legacyDrawing r:id="rId2"/><extLst><ext uri="{X}"/></extLst></worksheet>').encode()
    write_zip(base, with_ext)
    parts = dict(with_ext)
    parts["xl/worksheets/sheet1.xml"] = parts["xl/worksheets/sheet1.xml"].decode().replace(
        '<legacyDrawing r:id="rId2"/>', "").encode()
    write_zip(work, parts)
    code, log = run(work, base, out=out)
    sheet = read_zip(out)["xl/worksheets/sheet1.xml"].decode()
    order = [local(t) for t in re.findall(r"<([A-Za-z0-9_.:]+)[ />]", sheet)]
    try:
        ok = (code == 0
              and order.index("legacyDrawing") < order.index("extLst"))
    except ValueError:
        ok = False
    return ok, "exit %s, order %s" % (code, order[:8])


@case("16. a namespace named in mc:Ignorable stays declared", docx_only=True)
def case_ignorable(tmp):
    base = os.path.join(tmp, "b.docx")
    work = os.path.join(tmp, "w.docx")
    out = os.path.join(tmp, "o.docx")
    def make(with_comment):
        parts = docx_with_comment()
        doc = parts["word/document.xml"].decode().replace(
            '<w:document xmlns:w="%s">' % W,
            '<w:document xmlns:w="%s" xmlns:mc="http://schemas.openxmlformats.org/'
            'markup-compatibility/2006" xmlns:w14="%s" mc:Ignorable="w14">' % (W, W14))
        parts["word/document.xml"] = doc.encode()
        if not with_comment:
            parts = strip_comments(parts)
        return parts
    write_zip(base, make(False))
    write_zip(work, make(True))
    code, log = run(work, base, out=out)
    doc = read_zip(out)["word/document.xml"].decode()
    return code == 0 and 'xmlns:w14=' in doc and 'mc:Ignorable="w14"' in doc, "exit %s" % code


@case("17. other content in the reference run is kept", docx_only=True)
def case_run_content(tmp):
    base = os.path.join(tmp, "b.docx")
    work = os.path.join(tmp, "w.docx")
    out = os.path.join(tmp, "o.docx")
    bare = strip_comments(docx_with_comment())
    bare["word/document.xml"] = bare["word/document.xml"].decode().replace(
        "<w:p><w:r><w:t>Body text</w:t></w:r></w:p>",
        "<w:p><w:r><w:t>Body text</w:t></w:r><w:r><w:br/></w:r></w:p>").encode()
    write_zip(base, bare)
    parts = docx_with_comment()
    parts["word/document.xml"] = parts["word/document.xml"].decode().replace(
        "<w:r><w:commentReference w:id=\"1\"/></w:r>",
        "<w:r><w:br/><w:commentReference w:id=\"1\"/></w:r>").encode()
    write_zip(work, parts)
    code, log = run(work, base, out=out)
    doc = read_zip(out)["word/document.xml"].decode()
    return (code == 0 and "<w:br" in doc and "commentReference" not in doc), "exit %s" % code


@case("18. a deleted comment anchor is not certified", docx_only=True)
def case_anchor_deleted(tmp):
    base = os.path.join(tmp, "b.docx")
    work = os.path.join(tmp, "w.docx")
    out = os.path.join(tmp, "o.docx")
    write_zip(base, docx_with_comment())
    parts = docx_with_comment()
    raw = parts["word/document.xml"]
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = raw.decode("utf-16")
        parts["word/document.xml"] = re.sub(
            r"<w:commentRange\w+ w:id=\"1\"/>|<w:r><w:commentReference w:id=\"1\"/></w:r>",
            "", text).encode("utf-16")
    else:
        parts["word/document.xml"] = re.sub(
            r"<w:commentRange\w+ w:id=\"1\"/>|<w:r><w:commentReference w:id=\"1\"/></w:r>",
            "", raw.decode()).encode()
    write_zip(work, parts)
    code, log = run(work, base, out=out)
    return code == 2, "exit %s" % code


@case("19. an unusable baseline authorizes nothing", docx_only=True)
def case_bad_baseline(tmp):
    base = os.path.join(tmp, "b.docx")
    work = os.path.join(tmp, "w.docx")
    out = os.path.join(tmp, "o.docx")
    write_zip(base, {})                       # an empty package is no baseline
    write_zip(work, docx_with_comment())
    code, log = run(work, base, out=out)
    got = read_zip(out) if os.path.exists(out) else {}
    kept = "word/comments.xml" in got and b"Reviewer note" in got.get("word/comments.xml", b"")
    return code == 2 and kept, "exit %s" % code


@case("20. a package missing its content-type manifest never passes", docx_only=True)
def case_missing_ct(tmp):
    base = os.path.join(tmp, "b.docx")
    work = os.path.join(tmp, "w.docx")
    out = os.path.join(tmp, "o.docx")
    write_zip(base, docx_with_comment())
    parts = docx_with_comment()
    parts.pop("[Content_Types].xml")
    write_zip(work, parts)
    code, log = run(work, base, out=out)
    return code == 2, "exit %s" % code


@case("21. scan mode reports an annotation added since the baseline", docx_only=True)
def case_scan_added(tmp):
    base = os.path.join(tmp, "b.docx")
    work = os.path.join(tmp, "w.docx")
    write_zip(base, strip_comments(docx_with_comment()))
    write_zip(work, docx_with_comment())
    code, log = run(work, base, clean=False)
    return code == 2, "exit %s" % code


MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def docx_with_compat(encoding=None, requires=True, bad_prefix=False):
    """A .docx whose document.xml names prefixes by value, not by use."""
    parts = docx_with_comment()
    ns = ('xmlns:w="%s" xmlns:mc="%s" xmlns:w14="%s" xmlns:wp14="http://wp14" '
          'mc:Ignorable="%s"' % (W, MC, W14, "zz" if bad_prefix else "w14 wp14"))
    body = ('<w:p><w:r><w:t>Body text</w:t></w:r></w:p>'
            '<w:commentRangeStart w:id="1"/><w:commentRangeEnd w:id="1"/>'
            '<w:r><w:commentReference w:id="1"/></w:r>')
    if requires:
        body += ('<mc:AlternateContent><mc:Choice xmlns:x15="http://x15" Requires="x15">'
                 '<w:p><w:r><w:t>choice</w:t></w:r></w:p></mc:Choice></mc:AlternateContent>')
    doc = '<w:document %s><w:body>%s</w:body></w:document>' % (ns, body)
    if encoding == "utf-16":
        parts["word/document.xml"] = (
            '<?xml version="1.0" encoding="UTF-16"?>' + doc).encode("utf-16")
    else:
        parts["word/document.xml"] = ('<?xml version="1.0"?>' + doc).encode("utf-8")
    return parts


@case("22. a prefix named only by mc:Choice Requires survives cleanup", docx_only=True)
def case_requires(tmp):
    base = os.path.join(tmp, "b.docx")
    work = os.path.join(tmp, "w.docx")
    out = os.path.join(tmp, "o.docx")
    write_zip(base, strip_comments(docx_with_compat()))
    write_zip(work, docx_with_compat())
    code, log = run(work, base, out=out)
    doc = read_zip(out)["word/document.xml"].decode()
    return (code == 0 and 'xmlns:x15' in doc and 'Requires="x15"' in doc
            and "AlternateContent" in doc), "exit %s" % code


@case("23. UTF-16 markup keeps its compatibility bindings", docx_only=True)
def case_utf16_ns(tmp):
    base = os.path.join(tmp, "b.docx")
    work = os.path.join(tmp, "w.docx")
    out = os.path.join(tmp, "o.docx")
    write_zip(base, strip_comments(docx_with_compat(encoding="utf-16")))
    write_zip(work, docx_with_compat(encoding="utf-16"))
    code, log = run(work, base, out=out)
    doc = read_zip(out)["word/document.xml"]
    text = doc.decode("utf-16") if doc[:2] in (b"\xff\xfe", b"\xfe\xff") else doc.decode("utf-8")
    return (code == 0 and "xmlns:w14" in text and "xmlns:wp14" in text
            and "xmlns:x15" in text), "exit %s" % code


@case("24. an unresolved required prefix prevents a pass", docx_only=True)
def case_bad_prefix(tmp):
    base = os.path.join(tmp, "b.docx")
    work = os.path.join(tmp, "w.docx")
    out = os.path.join(tmp, "o.docx")
    write_zip(base, strip_comments(docx_with_compat(bad_prefix=True)))
    write_zip(work, docx_with_compat(bad_prefix=True))
    code, log = run(work, base, out=out)
    return code == 2, "exit %s" % code


def docx_two_paragraphs(anchor_para=0):
    """Two paragraphs, with the comment anchored on whichever one is named."""
    parts = docx_with_comment()
    anchors = ('<w:commentRangeStart w:id="1"/><w:commentRangeEnd w:id="1"/>'
               '<w:r><w:commentReference w:id="1"/></w:r>')
    first = "<w:p><w:r><w:t>First paragraph</w:t></w:r>%s</w:p>" % (
        anchors if anchor_para == 0 else "")
    second = "<w:p><w:r><w:t>Second paragraph</w:t></w:r>%s</w:p>" % (
        anchors if anchor_para == 1 else "")
    parts["word/document.xml"] = (
        '<?xml version="1.0"?><w:document xmlns:w="%s"><w:body>%s%s</w:body></w:document>'
        % (W, first, second)).encode()
    return parts


@case("25. moving an existing comment to another paragraph fails", docx_only=True)
def case_moved(tmp):
    base = os.path.join(tmp, "b.docx")
    work = os.path.join(tmp, "w.docx")
    out = os.path.join(tmp, "o.docx")
    write_zip(base, docx_two_paragraphs(0))
    write_zip(work, docx_two_paragraphs(1))
    code, log = run(work, base, out=out)
    got = read_zip(out)["word/document.xml"].decode() if os.path.exists(out) else ""
    moved_still_there = "Second paragraph</w:t></w:r><w:commentRangeStart" in got
    return code == 2 and moved_still_there, "exit %s" % code


@case("26. re-serialized but unchanged markup still passes", docx_only=True)
def case_reserialized(tmp):
    base = os.path.join(tmp, "b.docx")
    work = os.path.join(tmp, "w.docx")
    out = os.path.join(tmp, "o.docx")
    write_zip(base, docx_two_paragraphs(0))
    parts = docx_two_paragraphs(0)
    parts["word/document.xml"] = parts["word/document.xml"].decode().replace(
        'xmlns:w="%s"' % W, 'xmlns:ww="%s"' % W).replace("<w:", "<ww:").replace(
        "</w:", "</ww:").replace("w:id=", "ww:id=").encode()
    write_zip(work, parts)
    code, log = run(work, base, out=out)
    return code == 0, "exit %s" % code


@case("27. a baseline that promises a comments part it lacks authorizes nothing",
      docx_only=True)
def case_broken_chain(tmp):
    base = os.path.join(tmp, "b.docx")
    work = os.path.join(tmp, "w.docx")
    out = os.path.join(tmp, "o.docx")
    broken = docx_with_comment()
    broken.pop("word/comments.xml")          # relationship and declaration remain
    write_zip(base, broken)
    write_zip(work, docx_with_comment())
    code, log = run(work, base, out=out)
    got = read_zip(out) if os.path.exists(out) else {}
    kept = b"Reviewer note" in got.get("word/comments.xml", b"")
    return code == 2 and kept, "exit %s" % code


@case("28. scan mode reports an annotation deleted since the baseline", docx_only=True)
def case_scan_missing(tmp):
    base = os.path.join(tmp, "b.docx")
    work = os.path.join(tmp, "w.docx")
    write_zip(base, docx_with_comment())
    write_zip(work, strip_comments(docx_with_comment()))
    code, log = run(work, base, clean=False)
    return code == 2, "exit %s" % code


@case("29. scan mode passes an unchanged inventory", docx_only=True)
def case_scan_clean(tmp):
    base = os.path.join(tmp, "b.docx")
    work = os.path.join(tmp, "w.docx")
    write_zip(base, docx_with_comment())
    shutil.copy(base, work)
    code, log = run(work, base, clean=False)
    return code == 0, "exit %s" % code


def docx_anchor_span(target="Alpha", split=False, end_on_beta=False, break_side=None):
    """A valid paragraph with one comment range and its reference."""
    parts = docx_with_comment()
    alpha = '<w:r><w:t>Alpha</w:t></w:r>'
    if split:
        alpha = '<w:r><w:t>Al</w:t></w:r><w:r><w:t>pha</w:t></w:r>'
    beta = '<w:r><w:t>Beta</w:t></w:r>'
    gap = '<w:r><w:t xml:space="preserve"> and </w:t></w:r>'
    start = '<w:commentRangeStart w:id="1"/>'
    finish = '<w:commentRangeEnd w:id="1"/><w:r><w:commentReference w:id="1"/></w:r>'
    if break_side is not None:
        br = '<w:r><w:br/></w:r>'
        body = start + alpha + (finish + br if break_side == "before" else br + finish) + beta
    elif target == "Beta":
        body = alpha + gap + start + beta + finish
    elif end_on_beta:
        body = start + alpha + gap + beta + finish
    else:
        body = start + alpha + finish + gap + beta
    parts["word/document.xml"] = (
        '<w:document xmlns:w="%s"><w:body><w:p>%s</w:p></w:body></w:document>'
        % (W, body)).encode()
    return parts


def requires_uris(raw):
    """Independent scope reader used to assert the fixture's original bindings."""
    scope, result = [], []
    for event, value in ET.iterparse(io.BytesIO(raw), events=("start-ns", "end-ns", "start")):
        if event == "start-ns":
            scope.append(value)
        elif event == "end-ns":
            scope.pop()
        elif value.tag == "{%s}Choice" % MC:
            result.append(dict(scope)[value.get("Requires")])
    return result


@case("30. scoped prefix rebinding fails before creating or overwriting output", docx_only=True)
def case_scoped_rebinding(tmp):
    parts = docx_anchor_span()
    alternatives = ''.join(
        '<mc:AlternateContent><mc:Choice xmlns:feat="%s" Requires="feat">'
        '<w:p><w:r><w:t>Choice</w:t></w:r></w:p></mc:Choice>'
        '<mc:Fallback><w:p><w:r><w:t>Fallback</w:t></w:r></w:p></mc:Fallback>'
        '</mc:AlternateContent>' % uri for uri in ('urn:feature-one', 'urn:feature-two'))
    raw = parts["word/document.xml"].decode().replace(
        '<w:document ', '<w:document xmlns:mc="%s" ' % MC).replace(
        '</w:body>', alternatives + '</w:body>')
    parts["word/document.xml"] = raw.encode()
    assert requires_uris(parts["word/document.xml"]) == ['urn:feature-one', 'urn:feature-two']
    base, work, out = [os.path.join(tmp, n + '.docx') for n in ('b', 'w', 'o')]
    write_zip(base, strip_comments(parts))
    write_zip(work, parts)
    original = open(work, 'rb').read()
    code, log = run(work, base, out=out)
    inplace_code, inplace_log = run(work, base, out=work)
    return (code == inplace_code == 2 and not os.path.exists(out)
            and open(work, 'rb').read() == original
            and 'word/document.xml' in log and 'feat' in log
            and 'Traceback' not in log + inplace_log), 'exit %s / %s' % (code, inplace_code)


def docx_process_content(declared=True, unprefixed=False):
    parts = docx_anchor_span()
    binding = ('xmlns="urn:feature"' if unprefixed else 'xmlns:feat="urn:feature"')
    value = 'wrapper' if unprefixed else 'feat:wrapper'
    attrs = 'xmlns:mc="%s" mc:ProcessContent="%s"' % (MC, value)
    if declared:
        attrs += ' ' + binding
    parts["word/document.xml"] = parts["word/document.xml"].decode().replace(
        '<w:p>', '<w:p %s>' % attrs, 1).encode()
    return parts


@case("31. qualified ProcessContent survives both scan and document serialization", docx_only=True)
def case_process_content(tmp):
    parts = docx_process_content()
    base, work, out = [os.path.join(tmp, n + '.docx') for n in ('b', 'w', 'o')]
    write_zip(work, parts)
    scan_code, _ = run(work, work, clean=False)
    write_zip(base, strip_comments(parts))
    code, log = run(work, base, out=out)
    doc = ET.fromstring(read_zip(out)['word/document.xml']) if os.path.exists(out) else None
    paras = list(doc.iter('{%s}p' % W)) if doc is not None else []
    kept = any(p.get('{%s}ProcessContent' % MC) == 'feat:wrapper' for p in paras)
    return code == scan_code == 0 and kept, 'scan %s, clean %s' % (scan_code, code)


@case("32. an undeclared ProcessContent QName fails", docx_only=True)
def case_unresolved_qname(tmp):
    work, out = [os.path.join(tmp, n + '.docx') for n in ('w', 'o')]
    write_zip(work, docx_process_content(declared=False))
    code, log = run(work, work, out=out)
    return code == 2 and not os.path.exists(out) and 'feat' in log, 'exit %s' % code


@case("33. a comment moved between phrases in one paragraph fails", docx_only=True)
def case_same_paragraph_move(tmp):
    base, work, out = [os.path.join(tmp, n + '.docx') for n in ('b', 'w', 'o')]
    write_zip(base, docx_anchor_span())
    moved = docx_anchor_span(target='Beta')
    write_zip(work, moved)
    code, log = run(work, base, out=out)
    scan_code, _ = run(work, base, clean=False)
    got = read_zip(out) if os.path.exists(out) else {}
    details = open(os.path.splitext(work)[0] + '_metahygiene.md', encoding='utf-8').read()
    return (code == scan_code == 2 and got.get('word/document.xml') == moved['word/document.xml']
            and 'word/comments.xml' in details and '1' in details), 'clean %s, scan %s' % (code, scan_code)


@case("34. splitting text runs and changing prefixes does not relocate a comment", docx_only=True)
def case_anchor_run_split(tmp):
    base, work, out = [os.path.join(tmp, n + '.docx') for n in ('b', 'w', 'o')]
    write_zip(base, docx_anchor_span())
    parts = docx_anchor_span(split=True)
    parts['word/document.xml'] = parts['word/document.xml'].replace(b'xmlns:w=', b'xmlns:word=').replace(
        b'<w:', b'<word:').replace(b'</w:', b'</word:').replace(b'w:id=', b'word:id=')
    write_zip(work, parts)
    code, log = run(work, base, out=out)
    return code == 0, 'exit %s' % code


@case("35. extending only the comment's end boundary fails", docx_only=True)
def case_anchor_end_move(tmp):
    base, work, out = [os.path.join(tmp, n + '.docx') for n in ('b', 'w', 'o')]
    write_zip(base, docx_anchor_span())
    changed = docx_anchor_span(end_on_beta=True)
    write_zip(work, changed)
    code, log = run(work, base, out=out)
    got = read_zip(out) if os.path.exists(out) else {}
    return code == 2 and got.get('word/document.xml') == changed['word/document.xml'], 'exit %s' % code


@case("36. moving a comment boundary across a break fails", docx_only=True)
def case_anchor_break(tmp):
    base, work, out = [os.path.join(tmp, n + '.docx') for n in ('b', 'w', 'o')]
    write_zip(base, docx_anchor_span(break_side='before'))
    changed = docx_anchor_span(break_side='after')
    write_zip(work, changed)
    code, log = run(work, base, out=out)
    got = read_zip(out) if os.path.exists(out) else {}
    return code == 2 and got.get('word/document.xml') == changed['word/document.xml'], 'exit %s' % code


@case("37. verification rejects a namespace reference changed to another declared URI", docx_only=True)
def case_namespace_uri_verification(tmp):
    spec = importlib.util.spec_from_file_location('hygiene_under_test', SCRIPT)
    hygiene = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hygiene)
    original = strip_comments(docx_with_compat())
    base, out = [os.path.join(tmp, n + '.docx') for n in ('b', 'o')]
    write_zip(base, original)
    inv = hygiene.baseline_inventory(base)
    good, _, _ = hygiene.verify_package(base, original, set(), [], [], inv=inv)
    changed = dict(original)
    changed['word/document.xml'] = changed['word/document.xml'].replace(b'http://x15', b'http://x15-other')
    write_zip(out, changed)
    ok, checks, _ = hygiene.verify_package(out, original, set(), [], [], inv=inv,
                                            comment_touched={'word/document.xml'})
    return good and not ok and any('changed URI' in c for c in checks), 'original %s, changed %s' % (good, ok)


@case("38. an unprefixed ProcessContent QName retains its default namespace", docx_only=True)
def case_default_qname(tmp):
    parts = docx_process_content(unprefixed=True)
    base, work, out = [os.path.join(tmp, n + '.docx') for n in ('b', 'w', 'o')]
    write_zip(base, strip_comments(parts))
    write_zip(work, parts)
    code, log = run(work, base, out=out)
    return code == 0, 'exit %s' % code


def main():
    ap = argparse.ArgumentParser(description="annotation regression suite")
    ap.add_argument("--docx", action="store_true", help="run the Word subset only")
    a = ap.parse_args()
    if not os.path.exists(SCRIPT):
        print("cannot find %s" % SCRIPT)
        return 1
    failures = 0
    for name, fn, docx_only in CASES:
        if a.docx and not docx_only:
            continue
        tmp = tempfile.mkdtemp(prefix="anntest_")
        try:
            ok, detail = fn(tmp)
        except Exception as e:                       # a crash is a failure
            ok, detail = False, "raised %s" % e
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print("%s  %s%s" % ("pass" if ok else "FAIL", name,
                            "" if ok else "  [%s]" % detail))
        failures += 0 if ok else 1
    print("\n%d case(s) run, %d failure(s)"
          % (len([c for c in CASES if not a.docx or c[2]]), failures))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
