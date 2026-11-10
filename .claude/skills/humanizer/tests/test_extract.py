#!/usr/bin/env python3
"""Extraction and comparison suite for extract_text.py, diff_text.py and
scan_repetition.py.

The defect this guards against is a comparison that reports no change because
the text was never read: literal namespace prefixes, a forced UTF-8 decode, or
a part that failed to parse without anyone being told.

Fixtures are generated here. No project document is used or shipped.

    python tests/test_extract.py

Exit status 0 when every case passes, 1 otherwise.
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)

from test_annotations import docx_with_comment, write_zip  # noqa: E402
import extract_text  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
SS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def run(script, *args):
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)] + list(args),
                       capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    return p.returncode, p.stdout + p.stderr


def body(paragraphs, prefix="w", heading_first=False, table_second=False):
    """document.xml with the Word namespace bound to the given prefix."""
    q = (prefix + ":") if prefix else ""
    decl = ('xmlns:%s="%s"' % (prefix, W)) if prefix else ('xmlns="%s"' % W)
    out = []
    for i, text in enumerate(paragraphs):
        ppr = ""
        if heading_first and i == 0:
            ppr = '<%spPr><%spStyle %sval="Heading1"/></%spPr>' % (q, q, q, q)
        para = '<%sp>%s<%sr><%st>%s</%st></%sr></%sp>' % (q, ppr, q, q, text, q, q, q)
        if table_second and i == 1:
            para = ('<%stbl><%str><%stc>%s</%stc></%str></%stbl>'
                    % (q, q, q, para, q, q, q))
        out.append(para)
    return ('<%sdocument %s><%sbody>%s</%sbody></%sdocument>'
            % (q, decl, q, "".join(out), q, q))


def make_docx(path, xml, encoding="utf-8"):
    parts = docx_with_comment()
    decl = '<?xml version="1.0" encoding="%s"?>' % ("UTF-16" if encoding == "utf-16"
                                                    else "UTF-8")
    parts["word/document.xml"] = (decl + xml).encode(encoding)
    write_zip(path, parts)


def body_rows(path):
    rows, problems, _ = extract_text.extract_report(path)
    return [(l, t) for l, t in rows if l.startswith("body:")], problems


@case("E1. equivalent text under w:, x: and a default namespace extracts identically")
def e1(tmp):
    paras = ["The slab was poured on 12-May-26.", "Testing may be required."]
    got = []
    for prefix in ("w", "x", ""):
        f = os.path.join(tmp, "p_%s.docx" % (prefix or "default"))
        make_docx(f, body(paras, prefix))
        rows, problems = body_rows(f)
        got.append((rows, problems))
    ok = got[0] == got[1] == got[2] and [t for _, t in got[0][0]] == paras \
        and not got[0][1]
    return ok, repr(got)


@case("E2. a changed date under an alternate prefix is detected by diff_text.py")
def e2(tmp):
    a, b = os.path.join(tmp, "a.docx"), os.path.join(tmp, "b.docx")
    make_docx(a, body(["The slab was poured on 12-May-26."], "x"))
    make_docx(b, body(["The slab was poured on 19-May-26."], "x"))
    code, out = run("diff_text.py", a, b)
    return (code == 0 and "changed: 1" in out and "12-May-26" in out
            and "19-May-26" in out), out[-400:]


@case("E3. a changed qualification under an alternate prefix is detected")
def e3(tmp):
    a, b = os.path.join(tmp, "a.docx"), os.path.join(tmp, "b.docx")
    make_docx(a, body(["The delay may affect the milestone."], "ns0"))
    make_docx(b, body(["The delay will affect the milestone."], "ns0"))
    code, out = run("diff_text.py", a, b)
    return code == 0 and "changed: 1" in out and "will affect" in out, out[-400:]


@case("E4. a UTF-16 document part extracts correctly and a change in it is detected")
def e4(tmp):
    u8, u16, u16b = (os.path.join(tmp, n) for n in ("u8.docx", "u16.docx", "u16b.docx"))
    make_docx(u8, body(["Programme rev 3 issued."], "w"))
    make_docx(u16, body(["Programme rev 3 issued."], "w"), "utf-16")
    make_docx(u16b, body(["Programme rev 4 issued."], "w"), "utf-16")
    same = body_rows(u8) == body_rows(u16)
    code, out = run("diff_text.py", u16, u16b)
    return (same and code == 0 and "changed: 1" in out), "same %s, %s" % (same, out[-300:])


@case("E5. malformed XML gives an explicit INCOMPLETE result, never a clean comparison")
def e5(tmp):
    good, bad = os.path.join(tmp, "good.docx"), os.path.join(tmp, "bad.docx")
    make_docx(good, body(["Text."], "w"))
    parts = docx_with_comment()
    parts["word/document.xml"] = b'<?xml version="1.0"?><w:document xmlns:w="%s"><w:body>' \
                                 b'<w:p><w:r><w:t>Text.</w:t></w:r></w:body>' % W.encode()
    write_zip(bad, parts)
    c1, o1 = run("extract_text.py", bad)
    c2, o2 = run("diff_text.py", good, bad)
    return (c1 == 2 and "INCOMPLETE" in o1 and c2 == 2 and "INCOMPLETE" in o2
            and "no change found" not in o2), "%s %s | %s" % (c1, c2, o2[:300])


@case("E6. unchanged valid documents compare as no change, exit 0")
def e6(tmp):
    a, b = os.path.join(tmp, "a.docx"), os.path.join(tmp, "b.docx")
    make_docx(a, body(["One.", "Two."], "x"))
    make_docx(b, body(["One.", "Two."], "w"))
    code, out = run("diff_text.py", a, b)
    return code == 0 and "no change found" in out and "changed: 0" in out, out[-300:]


@case("E7. a document with no text is reported as empty, not as a failure")
def e7(tmp):
    a, b = os.path.join(tmp, "a.docx"), os.path.join(tmp, "b.docx")
    parts = docx_with_comment()
    parts.pop("word/comments.xml", None)
    for f in (a, b):
        p = dict(parts)
        p["word/document.xml"] = ('<?xml version="1.0"?><w:document xmlns:w="%s">'
                                  '<w:body><w:p/></w:body></w:document>' % W).encode()
        write_zip(f, p)
    rows, problems, _ = extract_text.extract_report(a)
    code, out = run("diff_text.py", a, b)
    empty_msg = "nothing to compare" in out
    return (not problems and code == 0 and empty_msg and "INCOMPLETE" not in out), out[-300:]


@case("E8. scan_repetition exclusions line up under an alternate prefix")
def e8(tmp):
    f = os.path.join(tmp, "r.docx")
    make_docx(f, body(["Progress", "Cell text", "Works continued as planned.",
                       "Works continued as planned."], "x",
                      heading_first=True, table_second=True))
    code, out = run("scan_repetition.py", f)
    return (code == 0 and "body:document.xml:p1: Progress" in out
            and "body:document.xml:p2: Cell text" in out
            and "works continued as planned" in out.lower()), out[:600]


@case("E9. DrawingML slide text under an alternate prefix extracts")
def e9(tmp):
    f = os.path.join(tmp, "s.pptx")
    sys.path.insert(0, HERE)
    from test_delivery import pptx_parts
    parts = pptx_parts()
    parts["ppt/slides/slide1.xml"] = (
        '<?xml version="1.0"?><pp:sld xmlns:pp="%s" xmlns:dd="%s"><pp:cSld><pp:spTree>'
        '<pp:sp><pp:txBody><dd:p><dd:r><dd:t>Cut-off 31-Aug-26</dd:t></dd:r></dd:p>'
        '</pp:txBody></pp:sp></pp:spTree></pp:cSld></pp:sld>' % (P, A)).encode()
    write_zip(f, parts)
    rows = extract_text.extract(f)
    return ("slide:slide1.xml:a1", "Cut-off 31-Aug-26") in rows, repr(rows)


@case("E10. spreadsheet shared and inline strings under an alternate prefix extract")
def e10(tmp):
    from test_annotations import xlsx_with_comment
    f = os.path.join(tmp, "x.xlsx")
    parts = xlsx_with_comment()
    parts["xl/sharedStrings.xml"] = ('<?xml version="1.0"?><s:sst xmlns:s="%s">'
                                     '<s:si><s:t>Shared wording</s:t></s:si></s:sst>'
                                     % SS).encode()
    parts["xl/worksheets/sheet1.xml"] = (
        '<?xml version="1.0"?><s:worksheet xmlns:s="%s"><s:sheetData><s:row r="1">'
        '<s:c r="A1" t="s"><s:v>0</s:v></s:c>'
        '<s:c r="B1" t="inlineStr"><s:is><s:t>Inline wording</s:t></s:is></s:c>'
        '</s:row></s:sheetData></s:worksheet>' % SS).encode()
    write_zip(f, parts)
    texts = [t for _, t in extract_text.extract(f)]
    return texts.count("Shared wording") >= 1 and "Inline wording" in texts, repr(texts)


@case("E11. an embedded object present in the package is disclosed as not extracted")
def e11(tmp):
    f = os.path.join(tmp, "e.docx")
    parts = docx_with_comment()
    parts["word/embeddings/oleObject1.bin"] = b"\x00\x01binary"
    write_zip(f, parts)
    _, problems, notes = extract_text.extract_report(f)
    return (not problems and any("embedded object" in n or "OLE object" in n
                                 for n in notes)), repr(notes)


@case("E12. a text box paragraph is its own passage, not merged or duplicated")
def e12(tmp):
    f = os.path.join(tmp, "t.docx")
    xml = ('<w:document xmlns:w="%s"><w:body><w:p><w:r><w:t>Outer text.</w:t></w:r>'
           '<w:r><w:txbxContent><w:p><w:r><w:t>Box text.</w:t></w:r></w:p>'
           '</w:txbxContent></w:r></w:p></w:body></w:document>' % W)
    make_docx(f, xml)
    rows, _ = body_rows(f)
    texts = [t for _, t in rows]
    return texts == ["Outer text.", "Box text."], repr(texts)


def main():
    failures = 0
    for name, fn in CASES:
        tmp = tempfile.mkdtemp(prefix="extracttest_")
        try:
            ok, detail = fn(tmp)
        except Exception as e:
            ok, detail = False, "raised %s" % e
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print("%s  %s%s" % ("pass" if ok else "FAIL", name, "" if ok else "  [%s]" % detail))
        failures += 0 if ok else 1
    print("\n%d case(s) run, %d failure(s)" % (len(CASES), failures))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
