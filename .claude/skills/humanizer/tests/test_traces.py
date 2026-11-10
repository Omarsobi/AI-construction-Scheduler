#!/usr/bin/env python3
"""Rev37 regression suite, extended at Rev38, Rev39, Rev40 and Rev41: citation
tokens,
ChatGPT link tracking, hidden Unicode including variation selector runs, the Rev39
clean_artifacts corrections (log destination, Markdown code, signed packages),
revision consistency, package identity, generator-library metadata and the four certification outcomes.

Every fixture is generated here. No project document is used and none is
shipped. Cases T10 to T13 build their fixture with the library whose defaults
they test (python-docx, python-pptx, openpyxl, ReportLab); where that library
is not installed the case is reported as SKIPPED, never as passed. Cases T35,
T36 and T39 compare the Markdown code detection with two CommonMark parsers,
commonmark.py and markdown-it-py (test-only dependencies), and are SKIPPED
where either is not installed; a skipped comparison is not a release
verification, and release QA runs them with both installed. Case T16
compares this skill with Fix Language's copy of the shared script; where the
fix-language folder is not beside this one, it is reported as SKIPPED.

    python tests/test_traces.py

Exit status 0 when every case run passes, 1 otherwise.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
HYGIENE = os.path.join(SCRIPTS, "metadata_hygiene.py")
ARTIFACTS = os.path.join(SCRIPTS, "clean_artifacts.py")
DIFF = os.path.join(SCRIPTS, "diff_text.py")
FL_HYGIENE = os.path.normpath(os.path.join(os.path.dirname(HERE), "..", "fix-language",
                                           "scripts", "metadata_hygiene.py"))
sys.path.insert(0, SCRIPTS)
import metadata_hygiene as mh  # noqa: E402

CASES, SKIPPED = [], []


class Skip(Exception):
    pass


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def run(script, *args):
    p = subprocess.run([sys.executable, script] + [str(a) for a in args],
                       capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    return p.returncode, p.stdout + p.stderr


def read_zip(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def log_of(path):
    return open(path, encoding="utf-8").read()


def lines_of(log, kinds=("artifact", "review", "info")):
    return [l for l in log.splitlines()
            if any(l.startswith("- [%s]" % k) for k in kinds)]


def need(module):
    try:
        return __import__(module)
    except ImportError:
        raise Skip("%s is not installed" % module)


# ---------------------------------------------------------------- fixtures

def neutral_core(parts, creator="Jane Planner"):
    """Replace a library's defaults with ordinary values, so a fixture tests
    one thing at a time."""
    parts["docProps/core.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="%s" xmlns:dc="%s" xmlns:dcterms="http://purl.org/dc/'
        'terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<dc:creator>%s</dc:creator><cp:lastModifiedBy>%s</cp:lastModifiedBy>'
        '<cp:revision>3</cp:revision>'
        '<dcterms:created xsi:type="dcterms:W3CDTF">2026-09-01T08:00:00Z</dcterms:created>'
        '<dcterms:modified xsi:type="dcterms:W3CDTF">2026-09-02T08:00:00Z</dcterms:modified>'
        '</cp:coreProperties>' % (mh.CP_NS, mh.DC_NS, creator, creator)).encode()
    if "docProps/app.xml" in parts:
        parts["docProps/app.xml"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://'
            'schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
            '<Application>Microsoft Office Word</Application></Properties>').encode()
    return parts


def rewrite(path, fn):
    parts = read_zip(path)
    parts = fn(parts) or parts
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        if "[Content_Types].xml" in parts:
            z.writestr("[Content_Types].xml", parts["[Content_Types].xml"])
        for n, d in parts.items():
            if n != "[Content_Types].xml":
                z.writestr(n, d)


def make_docx(path, paragraphs, links=(), neutral=True, tracked=None):
    docx = need("docx")
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml.shared import OxmlElement, qn
    d = docx.Document()
    for text in paragraphs:
        d.add_paragraph(text)
    for label, url in links:
        p = d.add_paragraph("Link: ")
        rid = d.part.relate_to(url, RT.HYPERLINK, is_external=True)
        h = OxmlElement("w:hyperlink")
        h.set(qn("r:id"), rid)
        r = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        b = OxmlElement("w:b")
        rpr.append(b)
        r.append(rpr)
        t = OxmlElement("w:t")
        t.text = label
        r.append(t)
        h.append(r)
        p._p.append(h)
    if tracked:
        p = d.add_paragraph("Tracked: ")
        ins = OxmlElement("w:ins")
        ins.set(qn("w:id"), "1")
        ins.set(qn("w:author"), "Reviewer")
        ins.set(qn("w:date"), "2026-09-01T00:00:00Z")
        r = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.text = tracked
        r.append(t)
        ins.append(r)
        p._p.append(ins)
    d.save(path)
    if neutral:
        rewrite(path, neutral_core)
    return path


def make_xlsx(path, cells=(), links=(), formula=None, neutral=True):
    openpyxl = need("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    for ref, value in cells:
        ws[ref] = value
    for ref, url in links:
        ws[ref] = "link"
        ws[ref].hyperlink = url
    if formula:
        ws["Z1"] = formula
    ws["Y1"] = 2
    ws["Y2"] = "=Y1*3"
    wb.save(path)
    if neutral:
        rewrite(path, neutral_core)
    return path


def make_pptx(path, texts=(), links=(), neutral=True):
    pptx = need("pptx")
    from pptx.util import Inches
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(3))
    tf = box.text_frame
    for i, text in enumerate(texts):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.text = text
    for label, url in links:
        para = tf.add_paragraph()
        run_ = para.add_run()
        run_.text = label
        run_.hyperlink.address = url
    prs.save(path)
    if neutral:
        rewrite(path, neutral_core)
    return path


def doc_texts(path):
    docx = need("docx")
    return [p.text for p in docx.Document(path).paragraphs]


def external_targets(path):
    out = []
    parts = read_zip(path)
    for n in sorted(parts):
        if n.endswith(".rels"):
            root = mh.parse(parts[n])
            for r in mh.relationships(root):
                if mh.rel_is_external(r):
                    out.append((n, r.get("Id"), r.get("Target")))
    return out


TOKEN_DOC = [
    "Revenue rose 4 percent. :contentReference[oaicite:0]{index=0}",
    "See the source citeturn0search3turn0news1 for detail.",
    "Bare handles turn0click1 and turn0fetch2 and turn0view1 here [oaicite:7].",
    "Older marker 【4†source】 after the claim.",
    "Wrapped citeturn0search0turn0news3 ends here.",
    "Ordinary paragraph with no artifact.",
]


# ---------------------------------------------------------------- cases

@case("T1. ChatGPT citation tokens in DOCX text are detected, removed by the artifact clean, "
      "and everything else is kept")
def t1(tmp):
    src = make_docx(os.path.join(tmp, "t1.docx"), TOKEN_DOC)
    code, out = run(HYGIENE, src, "--log", os.path.join(tmp, "t1_scan.md"))
    scan = log_of(os.path.join(tmp, "t1_scan.md"))
    detected = (code == 2 and scan.count("- [artifact]") >= 5
                and "Scan result: FAIL" in scan)
    dest = os.path.join(tmp, "t1_fix.docx")
    c2, o2 = run(ARTIFACTS, src, "--clean", "-o", dest, "--log", os.path.join(tmp, "t1.md"))
    texts = doc_texts(dest)
    expected = ["Revenue rose 4 percent.", "See the source for detail.",
                "Bare handles and and here.", "Older marker after the claim.",
                "Wrapped ends here.", "Ordinary paragraph with no artifact."]
    left = mh.trace_findings(read_zip(dest))
    tokens_left = [f for f in left if f[0] in ("artifact", "review")]
    before, after = read_zip(src), read_zip(dest)
    untouched = all(after[n] == before[n] for n in before if n != "word/document.xml")
    runs_kept = before["word/document.xml"].count(b"<w:r>") == after["word/document.xml"].count(
        b"<w:r>")
    ok = detected and c2 == 0 and texts == expected and not tokens_left and untouched and runs_kept
    return ok, "detected=%s exit=%s texts=%r left=%s untouched=%s runs=%s" % (
        detected, c2, texts, tokens_left[:2], untouched, runs_kept)


@case("T2. legitimate citation-like strings are not treated as artifacts")
def t2(tmp):
    legit = ["As shown in [1] and [12], and in (Smith, 2020).",
             "Turnout rose; return 0 search results; turn12 searching; turn the page.",
             "Clause 4.2, ISO 9001:2015, doi:10.1000/xyz123, index=0 in the array.",
             "Unicode citation (cite) and the word oai and a citation index.",
             "URL https://example.com/a?utm_source=newsletter&ref=chatgpt"]
    src = make_docx(os.path.join(tmp, "t2.docx"), legit)
    found = [f for f in mh.trace_findings(read_zip(src)) if f[0] in ("artifact", "review")]
    code, out = run(ARTIFACTS, src)
    for line in legit:
        found += [h for h in mh.citation_hits(line)]
    return (not found and code == 0), "found=%r exit=%s" % (found[:3], code)


@case("T3. utm_source=chatgpt.com removed as the first, middle, last and only parameter")
def t3(tmp):
    cases = {
        "https://a.example/p?utm_source=chatgpt.com&x=1&y=2": "https://a.example/p?x=1&y=2",
        "https://a.example/p?x=1&utm_source=chatgpt.com&y=2": "https://a.example/p?x=1&y=2",
        "https://a.example/p?x=1&y=2&utm_source=chatgpt.com": "https://a.example/p?x=1&y=2",
        "https://a.example/p?utm_source=chatgpt.com": "https://a.example/p",
    }
    unit = {u: mh.strip_chatgpt_utm(u)[0] for u in cases}
    unit_ok = all(unit[u] == v for u, v in cases.items())
    links = [("L%d" % i, u) for i, u in enumerate(cases)]
    src = make_docx(os.path.join(tmp, "t3.docx"), ["Links below."], links)
    dest = os.path.join(tmp, "t3_fix.docx")
    code, out = run(ARTIFACTS, src, "--clean", "-o", dest, "--log", os.path.join(tmp, "t3.md"))
    before = {(n, i): t for n, i, t in external_targets(src)}
    after = {(n, i): t for n, i, t in external_targets(dest)}
    mapped = all(after[k] == cases[before[k]] for k in before)
    report = log_of(os.path.join(tmp, "t3.md"))
    recorded = all(("original %s ; final %s" % (u, v)) in report for u, v in cases.items())
    sp, dp = read_zip(src), read_zip(dest)
    only_rels = all(dp[k] == sp[k] for k in sp if k != "word/_rels/document.xml.rels")
    return (unit_ok and code == 0 and mapped and set(before) == set(after) and recorded
            and only_rels), \
        "unit=%s exit=%s mapped=%s ids_kept=%s recorded=%s body_and_formatting_unchanged=%s" % (
            unit_ok, code, mapped, set(before) == set(after), recorded, only_rels)


@case("T4. fragments, multiple parameters and repeated tracking pairs, in DOCX, XLSX, PPTX "
      "and Markdown")
def t4(tmp):
    pairs = {
        "https://b.example/r?a=1&utm_source=chatgpt.com&b=two%20x&utm_source=chatgpt.com#sec-2":
            "https://b.example/r?a=1&b=two%20x#sec-2",
        "https://b.example/r?utm_source=chatgpt.com#top": "https://b.example/r#top",
        "https://b.example/r?a=&utm_source=ChatGPT.com&c=3": "https://b.example/r?a=&c=3",
    }
    unit_ok = all(mh.strip_chatgpt_utm(u)[0] == v for u, v in pairs.items())
    results = []
    for kind, maker in (("docx", lambda p: make_docx(p, ["x"], [("k", u) for u in pairs])),
                        ("xlsx", lambda p: make_xlsx(p, links=[("A%d" % (i + 1), u)
                                                               for i, u in enumerate(pairs)])),
                        ("pptx", lambda p: make_pptx(p, ["x"], [("k", u) for u in pairs]))):
        src = maker(os.path.join(tmp, "t4.%s" % kind))
        dest = os.path.join(tmp, "t4_fix.%s" % kind)
        code, _ = run(ARTIFACTS, src, "--clean", "-o", dest)
        got = sorted(t for _, _, t in external_targets(dest) if "b.example" in t)
        results.append((kind, code == 0 and got == sorted(pairs.values()), got))
    md = os.path.join(tmp, "t4.md")
    with open(md, "w", encoding="utf-8", newline="") as f:
        f.write("Read [this](%s) and %s.\r\nKeep [ref](https://c.example/?utm_source=google).\r\n"
                % tuple(list(pairs)[:2]))
    dest = os.path.join(tmp, "t4_fix.md")
    code, _ = run(ARTIFACTS, md, "--clean", "-o", dest)
    got = open(dest, encoding="utf-8", newline="").read()
    want = ("Read [this](%s) and %s.\r\nKeep [ref](https://c.example/?utm_source=google).\r\n"
            % tuple(list(pairs.values())[:2]))
    results.append(("md", code == 0 and got == want, got))
    ok = unit_ok and all(r[1] for r in results)
    return ok, "unit=%s %s" % (unit_ok, [(k, o) for k, o, _ in results])


@case("T5. unrelated tracking parameters and look-alike values are left unchanged")
def t5(tmp):
    keep = ["https://d.example/?utm_source=google&utm_medium=chatgpt.com",
            "https://d.example/?utm_source=chatgpt.community",
            "https://d.example/?xutm_source=chatgpt.com",
            "https://d.example/?utm_source=chatgpt.com.au",
            # ai-language-fix Rev3: utm_source=openai is now an artifact (see
            # tests/test_rev3.py), so the look-alike kept here is openai.com.
            "https://d.example/?utm_campaign=chatgpt.com&utm_source=openai.com",
            "https://chatgpt.com/share/abc?x=1"]
    unit_ok = all(mh.strip_chatgpt_utm(u) == (u, 0) for u in keep)
    detect_ok = not any(mh.UTM_CHATGPT.search(u) for u in keep)
    src = make_docx(os.path.join(tmp, "t5.docx"), ["Keep these."],
                    [("k%d" % i, u) for i, u in enumerate(keep)])
    dest = os.path.join(tmp, "t5_fix.docx")
    code, _ = run(ARTIFACTS, src, "--clean", "-o", dest)
    same = read_zip(src) == read_zip(dest)
    return (unit_ok and detect_ok and code == 0 and same), \
        "unit=%s detect=%s exit=%s byte_identical=%s" % (unit_ok, detect_ok, code, same)


HIDDEN_PARA = ("Zero​width, word⁠joiner, inner﻿BOM, ‮override‬, "
               "⁦isolate⁩, tag\U000e0041 and invisible⁢times.")
INFO_PARA = "Soft­hyphen, 10 %, heart❤️, symbol ."


@case("T6. existing hidden characters are reported with class, count and location, need "
      "review, and are never removed")
def t6(tmp):
    src = make_docx(os.path.join(tmp, "t6.docx"), [HIDDEN_PARA, INFO_PARA])
    base = os.path.join(tmp, "t6_base.docx")
    shutil.copy(src, base)
    code, _ = run(HYGIENE, src, "--log", os.path.join(tmp, "t6_scan.md"), "--baseline", base)
    scan = log_of(os.path.join(tmp, "t6_scan.md"))
    controls = ["U+200B", "U+2060", "U+FEFF", "U+202E", "U+202C", "U+2066", "U+2069",
                "U+E0041", "U+2062"]
    reviewed = all(re.search(r"- \[review\] document: %s .*invisible control.*paragraph 1"
                             % re.escape(c), scan) for c in controls)
    infos = all(re.search(r"- \[info\] document: %s " % re.escape(c), scan)
                for c in ("U+00AD", "U+202F", "U+FE0F", "U+F0B7"))
    review_label = "Scan result: REVIEW REQUIRED" in scan
    c_out = os.path.join(tmp, "t6_clean.docx")
    c2, o2 = run(HYGIENE, src, "--clean", "--baseline", base, "-o", c_out,
                 "--log", os.path.join(tmp, "t6_clean.md"))
    kept = read_zip(c_out)["word/document.xml"] == read_zip(src)["word/document.xml"]
    a_out = os.path.join(tmp, "t6_art.docx")
    run(ARTIFACTS, src, "--clean", "-o", a_out)
    kept2 = read_zip(a_out) == read_zip(src)
    _, d = run(DIFF, base, src)
    diff_ok = ("U+200B ZERO WIDTH SPACE: 1 in the revised file, 1 in the original, pre-existing"
               in d)
    ok = (code == 2 and reviewed and infos and review_label and c2 == 2
          and "hygiene result: REVIEW REQUIRED" in o2 and kept and kept2 and diff_ok)
    return ok, ("exit=%s reviewed=%s infos=%s label=%s clean_exit=%s kept=%s kept2=%s diff=%s"
                % (code, reviewed, infos, review_label, c2, kept, kept2, diff_ok))


@case("T7. hidden characters introduced since the baseline fail, and diff_text marks them "
      "introduced")
def t7(tmp):
    base = make_docx(os.path.join(tmp, "t7_base.docx"), ["Plain text one.", "Plain two."])
    work = make_docx(os.path.join(tmp, "t7.docx"), ["Plain​ text one.",
                                                    "Plain ‮two."])
    code, out = run(HYGIENE, work, "--clean", "--baseline", base,
                    "-o", os.path.join(tmp, "t7_c.docx"), "--log", os.path.join(tmp, "t7.md"))
    log = log_of(os.path.join(tmp, "t7.md"))
    failed = (code == 2 and "hygiene result: FAIL" in out
              and re.search(r"\[artifact\] document: U\+200B .*1 introduced since the baseline",
                            log) is not None
              and "Final verification: FAIL" in log)
    _, d = run(DIFF, base, work)
    marked = ("U+200B ZERO WIDTH SPACE: 1 in the revised file, 0 in the original, 1 introduced "
              "-- scan item 16 fail" in d and "U+202E RIGHT-TO-LEFT OVERRIDE" in d)
    return failed and marked, "failed=%s marked=%s" % (failed, marked)


@case("T8. Arabic text with U+200C and U+200D is informational, preserved byte for byte, and "
      "passes")
def t8(tmp):
    arabic = ["می‌خواهم لا‍م",
              "المشروع ‏(أ)‎ note"]
    src = make_docx(os.path.join(tmp, "t8.docx"), arabic)
    base = os.path.join(tmp, "t8_base.docx")
    shutil.copy(src, base)
    out_doc = os.path.join(tmp, "t8_c.docx")
    code, out = run(HYGIENE, src, "--clean", "--baseline", base, "-o", out_doc,
                    "--log", os.path.join(tmp, "t8.md"))
    log = log_of(os.path.join(tmp, "t8.md"))
    infos = all(re.search(r"- \[info\] document: %s .*language-dependent" % re.escape(c), log)
                for c in ("U+200C", "U+200D", "U+200E", "U+200F"))
    no_fail = not re.search(r"\[(artifact|review)\] document: U\+200[C-F]", log)
    kept = read_zip(out_doc)["word/document.xml"] == read_zip(src)["word/document.xml"]
    a_out = os.path.join(tmp, "t8_a.docx")
    run(ARTIFACTS, src, "--clean", "-o", a_out)
    kept2 = read_zip(a_out) == read_zip(src)
    _, d = run(DIFF, base, out_doc)
    diff_ok = "[language-dependent] U+200C ZERO WIDTH NON-JOINER" in d and "preserve" in d
    ok = (code == 0 and "hygiene result: PASS WITH INFORMATIONAL FINDINGS" in out and infos
          and no_fail and kept and kept2 and diff_ok
          and "Final verification: PASS WITH INFORMATIONAL FINDINGS" in log)
    return ok, "exit=%s infos=%s no_fail=%s kept=%s kept2=%s diff=%s" % (
        code, infos, no_fail, kept, kept2, diff_ok)


@case("T9. source-controlled content is preserved: a formula, a tracked change, a quoted "
      "token and characters that belong to the text")
def t9(tmp):
    formula = '=HYPERLINK("https://e.example/?utm_source=chatgpt.com","src")'
    xsrc = make_xlsx(os.path.join(tmp, "t9.xlsx"),
                     cells=[("A1", "Text :contentReference[oaicite:3]{index=3} end"),
                            ("A2", "Name with NBSP and Soft­hyphen")],
                     formula=formula)
    xdest = os.path.join(tmp, "t9_fix.xlsx")
    code, _ = run(ARTIFACTS, xsrc, "--clean", "-o", xdest, "--log", os.path.join(tmp, "t9x.md"))
    xr = log_of(os.path.join(tmp, "t9x.md"))
    wb = need("openpyxl").load_workbook(xdest)
    ws = wb.active
    formula_kept = ws["Z1"].value == formula and ws["Y2"].value == "=Y1*3"
    text_fixed = ws["A1"].value == "Text end"
    chars_kept = ws["A2"].value == "Name with NBSP and Soft­hyphen"
    formula_flagged = "inside a formula, not edited" in xr
    dsrc = make_docx(os.path.join(tmp, "t9.docx"),
                     ['The string "oaicite:2" is discussed here as the subject.',
                      "Clause text with  non-breaking space kept."],
                     tracked="inserted turn0search9 text")
    ddest = os.path.join(tmp, "t9_fix.docx")
    c2, _ = run(ARTIFACTS, dsrc, "--clean", "-o", ddest, "--log", os.path.join(tmp, "t9d.md"))
    dr = log_of(os.path.join(tmp, "t9d.md"))
    same = read_zip(ddest) == read_zip(dsrc)
    flagged = ("inside a tracked change, not edited" in dr
               and "purpose ambiguous, left for review" in dr)
    ok = (code == 2 and formula_kept and text_fixed and chars_kept and formula_flagged
          and c2 == 2 and same and flagged)
    return ok, ("xlsx exit=%s formula_kept=%s text_fixed=%s chars=%s flagged=%s; docx exit=%s "
                "unchanged=%s flagged=%s" % (code, formula_kept, text_fixed, chars_kept,
                                             formula_flagged, c2, same, flagged))


@case("T10. DOCX from python-docx: generator name in creator fails, description needs review, "
      "template dates reported, and nothing is overwritten without authorization")
def t10(tmp):
    src = make_docx(os.path.join(tmp, "t10.docx"), ["Body."], neutral=False)
    base = os.path.join(tmp, "t10_base.docx")
    shutil.copy(src, base)
    code, _ = run(HYGIENE, src, "--baseline", base, "--log", os.path.join(tmp, "t10s.md"))
    s = log_of(os.path.join(tmp, "t10s.md"))
    scan_ok = (code == 2 and "[author-marker] docProps/core.xml: creator = python-docx" in s
               and "generator library: python-docx" in s
               and "[report-marker] docProps/core.xml: description = generated by python-docx"
               in s and re.search(r"\[info\] docProps/core.xml: created 2013-12-23T23:15:00Z.*"
                                  r"python-docx template dates, revision 1", s) is not None
               and "## Classification of the generator-library findings" in s
               and "Scan result: FAIL" in s)
    c1 = os.path.join(tmp, "t10_c1.docx")
    code1, out1 = run(HYGIENE, src, "--clean", "--baseline", base, "-o", c1,
                      "--log", os.path.join(tmp, "t10c1.md"))
    core1 = read_zip(c1)["docProps/core.xml"]
    not_overwritten = (b"<dc:creator>python-docx</dc:creator>" in core1
                       and b"generated by python-docx" in core1 and code1 == 2
                       and "hygiene result: FAIL" in out1)
    c2 = os.path.join(tmp, "t10_c2.docx")
    code2, out2 = run(HYGIENE, src, "--clean", "--baseline", base, "--blank-author", "-o", c2,
                      "--log", os.path.join(tmp, "t10c2.md"))
    review = code2 == 2 and "hygiene result: REVIEW REQUIRED" in out2
    desc_kept = b"generated by python-docx" in read_zip(c2)["docProps/core.xml"]
    c3 = os.path.join(tmp, "t10_c3.docx")
    code3, out3 = run(HYGIENE, src, "--clean", "--baseline", base, "--blank-author", "-o", c3,
                      "--accept", "docProps/core.xml|description|generated by python-docx|"
                                  "T. Reviewer|library default, decided", "--log",
                      os.path.join(tmp, "t10c3.md"))
    passed = code3 == 0 and "hygiene result: PASS WITH INFORMATIONAL FINDINGS" in out3
    ok = scan_ok and not_overwritten and review and desc_kept and passed
    return ok, "scan=%s kept=%s review=%s desc_kept=%s passed=%s" % (
        scan_ok, not_overwritten, review, desc_kept, passed)


@case("T11. PPTX from python-pptx: description needs review, Steve Canny and the template "
      "dates are reported only, lastModifiedBy is not replaced")
def t11(tmp):
    src = make_pptx(os.path.join(tmp, "t11.pptx"), ["Body"], neutral=False)
    base = os.path.join(tmp, "t11_base.pptx")
    shutil.copy(src, base)
    dest = os.path.join(tmp, "t11_c.pptx")
    code, out = run(HYGIENE, src, "--clean", "--baseline", base, "-o", dest,
                    "--log", os.path.join(tmp, "t11.md"))
    log = log_of(os.path.join(tmp, "t11.md"))
    core = read_zip(dest)["docProps/core.xml"]
    ok = (code == 2 and "hygiene result: REVIEW REQUIRED" in out
          and "[report-marker] docProps/core.xml: description = generated using python-pptx" in log
          and re.search(r"\[info\] docProps/core.xml: lastModifiedBy = Steve Canny.*Reported "
                        r"only", log) is not None
          and "python-pptx template dates, revision 1" in log
          and b"<cp:lastModifiedBy>Steve Canny</cp:lastModifiedBy>" in core
          and not re.search(r"\[(author-marker|artifact|review)\][^\n]*Steve Canny", log))
    return ok, "exit=%s" % code


@case("T12. XLSX from openpyxl: creator and Application fail until decided; --author changes "
      "only the author fields")
def t12(tmp):
    src = make_xlsx(os.path.join(tmp, "t12.xlsx"), cells=[("A1", "x")], neutral=False)
    base = os.path.join(tmp, "t12_base.xlsx")
    shutil.copy(src, base)
    c1 = os.path.join(tmp, "t12_c1.xlsx")
    code1, out1 = run(HYGIENE, src, "--clean", "--baseline", base, "-o", c1,
                      "--log", os.path.join(tmp, "t12a.md"))
    l1 = log_of(os.path.join(tmp, "t12a.md"))
    first = (code1 == 2 and "hygiene result: FAIL" in out1
             and "creator = openpyxl" in l1 and "Application = Microsoft Excel Compatible / "
                                                 "Openpyxl" in l1)
    c2 = os.path.join(tmp, "t12_c2.xlsx")
    code2, out2 = run(HYGIENE, src, "--clean", "--baseline", base, "-o", c2,
                      "--author", "A. Preparer", "--log", os.path.join(tmp, "t12b.md"))
    p2 = read_zip(c2)
    author_set = b"<dc:creator>A. Preparer</dc:creator>" in p2["docProps/core.xml"].replace(
        b' xmlns:dc="http://purl.org/dc/elements/1.1/"', b"")
    app_kept = b"Openpyxl" in p2["docProps/app.xml"]
    second = code2 == 2 and "hygiene result: FAIL" in out2 and author_set and app_kept
    app = re.search(rb"<Application>([^<]+)</Application>",
                    read_zip(src)["docProps/app.xml"]).group(1).decode()
    c3 = os.path.join(tmp, "t12_c3.xlsx")
    code3, out3 = run(HYGIENE, src, "--clean", "--baseline", base, "-o", c3,
                      "--author", "A. Preparer", "--accept",
                      "docProps/app.xml|Application|%s|T. Reviewer|generator, decided" % app,
                      "--log", os.path.join(tmp, "t12c.md"))
    third = code3 == 0 and re.search(r"hygiene result: PASS", out3) is not None
    return first and second and third, "first=%s second=%s third=%s" % (first, second, third)


@case("T13. PDF from ReportLab: the Producer is examined by the PDF provenance check and fails; "
      "the file is not edited")
def t13(tmp):
    need("reportlab")
    from reportlab.pdfgen import canvas
    path = os.path.join(tmp, "t13.pdf")
    c = canvas.Canvas(path)
    c.drawString(72, 720, "Body text with turn0search4 handle.")
    c.save()
    before = open(path, "rb").read()
    code, out = run(HYGIENE, path, "--log", os.path.join(tmp, "t13.md"))
    log = log_of(os.path.join(tmp, "t13.md"))
    if "read with" not in log:
        raise Skip("no PDF parser installed, the parser path cannot be tested")
    ok = (code == 2 and "Inspection result: FAIL" in log
          and "/Producer carries generator library: reportlab" in log
          and "turn0search4" in log and open(path, "rb").read() == before
          and "## Classification of the generator-library findings" in log)
    return ok, "exit=%s" % code


@case("T14. existing author metadata: an ordinary author is kept and passes, a library author "
      "changes only with --author or --blank-author")
def t14(tmp):
    src = make_docx(os.path.join(tmp, "t14.docx"), ["Body."])
    base = os.path.join(tmp, "t14_base.docx")
    shutil.copy(src, base)
    c1 = os.path.join(tmp, "t14_c1.docx")
    code1, out1 = run(HYGIENE, src, "--clean", "--baseline", base, "-o", c1,
                      "--log", os.path.join(tmp, "t14a.md"))
    kept = b"Jane Planner" in read_zip(c1)["docProps/core.xml"]
    first = code1 == 0 and out1.count("hygiene result: PASS") == 1 and kept
    lib = os.path.join(tmp, "t14_lib.docx")
    shutil.copy(src, lib)
    rewrite(lib, lambda p: neutral_core(p, creator="PptxGenJS"))
    lbase = os.path.join(tmp, "t14_lbase.docx")
    shutil.copy(lib, lbase)
    c2 = os.path.join(tmp, "t14_c2.docx")
    code2, out2 = run(HYGIENE, lib, "--clean", "--baseline", lbase, "-o", c2,
                      "--log", os.path.join(tmp, "t14b.md"))
    unauthorized = code2 == 2 and b"PptxGenJS" in read_zip(c2)["docProps/core.xml"]
    c3 = os.path.join(tmp, "t14_c3.docx")
    code3, out3 = run(HYGIENE, lib, "--clean", "--baseline", lbase, "-o", c3,
                      "--blank-author", "--log", os.path.join(tmp, "t14c.md"))
    authorized = code3 == 0 and b"PptxGenJS" not in read_zip(c3)["docProps/core.xml"]
    un = os.path.join(tmp, "t14_un.docx")
    shutil.copy(src, un)
    rewrite(un, lambda p: neutral_core(p, creator="Un-named"))
    ubase = os.path.join(tmp, "t14_ubase.docx")
    shutil.copy(un, ubase)
    c4 = os.path.join(tmp, "t14_c4.docx")
    code4, out4 = run(HYGIENE, un, "--clean", "--baseline", ubase, "-o", c4,
                      "--log", os.path.join(tmp, "t14d.md"))
    unnamed = (code4 == 0 and "PASS WITH INFORMATIONAL FINDINGS" in out4
               and b"Un-named" in read_zip(c4)["docProps/core.xml"])
    ok = first and unauthorized and authorized and unnamed
    return ok, "ordinary=%s unauthorized_kept=%s authorized=%s unnamed=%s" % (
        first, unauthorized, authorized, unnamed)


@case("T15. template dates and revision values: both dates, one date, and an ordinary date")
def t15(tmp):
    def core(created, modified, rev="1"):
        return {"docProps/core.xml": (
            '<?xml version="1.0"?><cp:coreProperties xmlns:cp="%s" xmlns:dc="%s" '
            'xmlns:dcterms="http://purl.org/dc/terms/"><cp:revision>%s</cp:revision>'
            '<dcterms:created>%s</dcterms:created><dcterms:modified>%s</dcterms:modified>'
            '</cp:coreProperties>' % (mh.CP_NS, mh.DC_NS, rev, created, modified)).encode()}
    both = [f for f in mh.trace_findings(core("2013-01-27T09:14:16Z", "2013-01-27T09:15:58Z"))
            if "template date" in f[2]]
    one = [f for f in mh.trace_findings(core("2013-12-23T23:15:00Z", "2026-09-30T10:00:00Z",
                                             "7")) if "template date" in f[2]]
    none_ = [f for f in mh.trace_findings(core("2026-09-01T08:00:00Z", "2026-09-02T08:00:00Z"))
             if "template date" in f[2]]
    ok = (len(both) == 1 and both[0][0] == "info" and "python-pptx template dates, revision 1"
          in both[0][2] and len(one) == 1 and one[0][0] == "info"
          and "created 2013-12-23T23:15:00Z matches the python-docx template date, revision 7"
          in one[0][2] and not none_
          and mh.outcome(both + one) == mh.OUTCOME_INFO)
    return ok, "both=%s one=%s none=%s" % (both, one, none_)


# T16 retired at ai-language-fix Rev1: the merged skill carries one
# metadata_hygiene.py, so there is no second copy to compare. The function is
# kept, unregistered, for the record.
def t16(tmp):
    if not os.path.exists(FL_HYGIENE):
        raise Skip("fix-language is not installed beside ai-fix at %s" % FL_HYGIENE)
    fixtures = [make_docx(os.path.join(tmp, "p1.docx"), TOKEN_DOC),
                make_docx(os.path.join(tmp, "p2.docx"), [HIDDEN_PARA, INFO_PARA]),
                make_docx(os.path.join(tmp, "p3.docx"), ["م‌ر ل‍"]),
                make_docx(os.path.join(tmp, "p4.docx"), ["Body."], neutral=False),
                make_docx(os.path.join(tmp, "p5.docx"), ["Body."],
                          [("k", "https://f.example/?utm_source=chatgpt.com&q=1")])]
    diffs = []
    for fx in fixtures:
        base = fx + ".base.docx"
        shutil.copy(fx, base)
        res = []
        for script, tag in ((HYGIENE, "af"), (FL_HYGIENE, "fl")):
            for mode in ("scan", "clean"):
                lg = "%s.%s.%s.md" % (fx, tag, mode)
                args = [fx, "--baseline", base, "--log", lg]
                if mode == "clean":
                    args += ["--clean", "-o", "%s.%s.out.docx" % (fx, tag)]
                code, _ = run(script, *args)
                text = log_of(lg)
                found = sorted(l for l in text.splitlines() if re.match(r"- \[[a-z-]+\] ", l))
                result = re.findall(r"^(?:Scan result|Hygiene result|- Final verification): "
                                    r"(.*)$", text, re.M)
                res.append((mode, code, found, result))
        if res[:2] != res[2:]:
            diffs.append(os.path.basename(fx))

    def shared(path):
        src = open(path, encoding="utf-8").read()
        m = re.search(r"# -+ trace detection\n.*?\n(?=# -+ XML helpers)", src, re.S)
        return m.group(0) if m else None

    a_block, f_block = shared(HYGIENE), shared(FL_HYGIENE)
    same_block = a_block is not None and a_block == f_block
    import importlib.util
    spec = importlib.util.spec_from_file_location("fl_mh", FL_HYGIENE)
    fl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fl)
    names = ("TOOL_PATTERNS", "GENERATOR_PATTERNS", "LIBRARY_DEFAULT_VALUES", "TEMPLATE_DATES",
             "FAILING", "REVIEW_KINDS", "INFO_KINDS", "PROVENANCE_FIELDS", "DESCRIPTIVE_FIELDS",
             "AUTHOR_TAGS", "INTEGRATION_KEYS")
    same_defs = all(getattr(mh, n) == getattr(fl, n) for n in names)
    import ast
    import inspect
    import textwrap
    funcs = ("keyword_hits", "describe", "classify", "custom_property_verdict", "outcome",
             "trace_findings", "verify_package", "certification_block", "read_certificate",
             "hidden_findings", "text_trace_findings", "citation_hits",
             "strip_chatgpt_utm", "text_units", "hidden_class", "hidden_hits", "hidden_id",
             "hidden_counts", "unicode_label")

    # recertify is left out on purpose: Fix Language's copy refuses a workbook,
    # presentation or PDF before recertifying, which is its narrower scope.
    def code(mod, f):     # the code itself, so a comment-only difference does not count
        return ast.dump(ast.parse(textwrap.dedent(inspect.getsource(getattr(mod, f)))))
    differing = [f for f in funcs if code(mh, f) != code(fl, f)]
    same_funcs = not differing
    ok = not diffs and same_block and same_defs and same_funcs
    return ok, "fixtures_differing=%s shared_block=%s definitions=%s functions_differing=%s" % (
        diffs, same_block, same_defs, differing)


@case("T17. files with no trace are unchanged: PASS, nothing found, nothing edited")
def t17(tmp):
    results = []
    for kind, maker in (("docx", lambda p: make_docx(p, ["Plain body text.", "Second."],
                                                      [("k", "https://g.example/?a=1#x")])),
                        ("xlsx", lambda p: make_xlsx(p, cells=[("A1", "Plain")],
                                                     links=[("B1", "https://g.example/?a=1")])),
                        ("pptx", lambda p: make_pptx(p, ["Plain"],
                                                     [("k", "https://g.example/")]))):
        src = maker(os.path.join(tmp, "t17.%s" % kind))
        base = os.path.join(tmp, "t17_base.%s" % kind)
        shutil.copy(src, base)
        acode, aout = run(ARTIFACTS, src)
        a_dest = os.path.join(tmp, "t17_a.%s" % kind)
        ccode, _ = run(ARTIFACTS, src, "--clean", "-o", a_dest)
        same = read_zip(a_dest) == read_zip(src)
        dest = os.path.join(tmp, "t17_c.%s" % kind)
        hcode, hout = run(HYGIENE, src, "--clean", "--baseline", base, "-o", dest,
                          "--log", os.path.join(tmp, "t17_%s.md" % kind))
        log = log_of(os.path.join(tmp, "t17_%s.md" % kind))
        plain_pass = ("hygiene result: PASS\n" in hout + "\n"
                      and "- Final verification: PASS\n" in log)
        results.append((kind, acode == 0 and "found: 0" in aout and ccode == 0 and same
                        and hcode == 0 and plain_pass))
    md = os.path.join(tmp, "t17.md")
    open(md, "w", encoding="utf-8").write("﻿Plain text with a [link](https://g.example/).\n")
    tcode, tout = run(HYGIENE, md, "--log", os.path.join(tmp, "t17_md.md"))
    results.append(("md", tcode == 0 and "trace inspection result: PASS\n" in tout + "\n"))
    return all(r[1] for r in results), "%s" % results


@case("T18. the four outcomes, in scan, clean, the certification record and recertification")
def t18(tmp):
    out = {}
    specs = {"PASS": ["Plain."],
             "PASS WITH INFORMATIONAL FINDINGS": ["م‌ر"],
             "REVIEW REQUIRED": ["zero​width"],
             "FAIL": ["Claim. :contentReference[oaicite:0]{index=0}"]}
    for label, paras in specs.items():
        src = make_docx(os.path.join(tmp, "o_%d.docx" % len(out)), paras)
        base = src + ".base.docx"
        shutil.copy(src, base)
        slog = src + ".scan.md"
        scode, _ = run(HYGIENE, src, "--baseline", base, "--log", slog)
        dest = src + ".clean.docx"
        clog = src + ".clean.md"
        ccode, cout = run(HYGIENE, src, "--clean", "--baseline", base, "-o", dest, "--log", clog)
        s, c = log_of(slog), log_of(clog)
        want_code = 0 if label.startswith("PASS") else 2
        good = (scode == want_code and ccode == want_code
                and re.search(r"^Scan result: %s(,|$)" % re.escape(label), s, re.M) is not None
                and re.search(r"^hygiene result: %s$" % re.escape(label), cout, re.M) is not None
                and re.search(r"^- Final verification: %s$" % re.escape(label), c, re.M)
                is not None)
        recert = None
        if label.startswith("PASS"):
            rlog = src + ".recert.md"
            rcode, rout = run(HYGIENE, dest, "--recertify", "--certificate", clog,
                              "--baseline", base, "--log", rlog)
            recert = rcode == 0 and ("recertification: %s" % label) in rout
            good = good and recert
        else:
            rcode, rout = run(HYGIENE, dest, "--recertify", "--certificate", clog,
                              "--baseline", base, "--log", src + ".recert.md")
            recert = rcode == 2 and "does not record a pass" in log_of(src + ".recert.md")
            good = good and recert
        out[label] = (good, scode, ccode, recert)
    return all(v[0] for v in out.values()), "%s" % out


@case("T19. a refused artifact clean writes nothing over the source")
def t19(tmp):
    src = make_docx(os.path.join(tmp, "t19.docx"), TOKEN_DOC)
    before = read_zip(src)
    code, out = run(ARTIFACTS, src, "--clean", "-o", src)
    alias = os.path.join(tmp, "alias.docx")
    os.link(src, alias)
    code2, out2 = run(ARTIFACTS, src, "--clean", "-o", alias)
    code3, out3 = run(ARTIFACTS, src, "--clean", "-o", os.path.join(tmp, "t19.xlsx"))
    ok = (code == 2 and "refused" in out and code2 == 2 and "refused" in out2 and code3 == 2
          and "refused" in out3 and read_zip(src) == before
          and not os.path.exists(os.path.join(tmp, "t19.xlsx")))
    return ok, "exits %s %s %s" % (code, code2, code3)


# ---------------------------------------------------------------- Rev38: variation selector runs

def vs_full(data):
    """Each byte as one selector: U+FE00+b below 16, otherwise U+E0100+(b-16)."""
    return "".join(chr(0xFE00 + b) if b < 16 else chr(0xE0100 + b - 16) for b in data)


def vs_nibble(data):
    """Each byte as two selectors from U+FE00-U+FE0F only."""
    return "".join(chr(0xFE00 + (b >> 4)) + chr(0xFE00 + (b & 15)) for b in data)


VS_PLAIN = "The slab pour for Zone B was completed."


@case("T20. a variation selector run introduced since the baseline fails as VS-RUN in Word, "
      "plain text and diff_text, in both ranges")
def t20(tmp):
    base = make_docx(os.path.join(tmp, "t20_base.docx"), [VS_PLAIN])
    results = {}
    for label, payload in (("full", vs_full(b"TEST-TRACE-0042")),
                           ("nibble", vs_nibble(b"TEST-TRACE-0042"))):
        text = "The" + payload + VS_PLAIN[3:]
        work = make_docx(os.path.join(tmp, "t20_%s.docx" % label), [text])
        log_path = os.path.join(tmp, "t20_%s.md" % label)
        code, out = run(HYGIENE, work, "--clean", "--baseline", base,
                        "-o", os.path.join(tmp, "t20_%s_c.docx" % label), "--log", log_path)
        log = log_of(log_path)
        n = len(payload)
        docx_fail = (code == 2 and "hygiene result: FAIL" in out
                     and re.search(r"\[artifact\] document: VS-RUN .*invisible control, %d "
                                   r"occurrence.*%d introduced since the baseline" % (n, n),
                                   log) is not None
                     and "U+FE0" not in "".join(l for l in lines_of(log) if "[info]" in l))
        tb, tw = os.path.join(tmp, "t20_base.txt"), os.path.join(tmp, "t20_%s.txt" % label)
        open(tb, "w", encoding="utf-8").write(VS_PLAIN + "\n")
        open(tw, "w", encoding="utf-8").write(text + "\n")
        tcode, tout = run(HYGIENE, tw, "--baseline", tb,
                          "--log", os.path.join(tmp, "t20_%s_t.md" % label))
        text_fail = tcode == 2 and "trace inspection result: FAIL" in tout
        _, d = run(DIFF, tb, tw)
        diff_fail = ("VS-RUN variation selectors in a run of two or more" in d
                     and "%d introduced -- scan item 16 fail" % n in d)
        results[label] = (docx_fail, text_fail, diff_fail)
    return all(all(v) for v in results.values()), "%s" % results


@case("T21. a single variation selector after a base character stays informational and passes")
def t21(tmp):
    paras = ["Status: ✔️ complete.", "Variant 葛\U000e0100 form."]
    src = make_docx(os.path.join(tmp, "t21.docx"), paras)
    base = make_docx(os.path.join(tmp, "t21_base.docx"), ["Status: complete.", "Variant form."])
    code, out = run(HYGIENE, src, "--clean", "--baseline", base,
                    "-o", os.path.join(tmp, "t21_c.docx"), "--log", os.path.join(tmp, "t21.md"))
    log = log_of(os.path.join(tmp, "t21.md"))
    ok = (code == 0 and "hygiene result: PASS WITH INFORMATIONAL FINDINGS" in out
          and re.search(r"\[info\] document: U\+FE0F ", log) is not None
          and re.search(r"\[info\] document: U\+E0100 ", log) is not None
          and "VS-RUN" not in log)
    return ok, "exit=%s" % code


@case("T22. a pre-existing run needs review, is never removed, clears only by an exact "
      "--accept, and is left to the hygiene report by clean_artifacts")
def t22(tmp):
    text = "The" + vs_full(b"ID-7") + VS_PLAIN[3:]
    src = make_docx(os.path.join(tmp, "t22.docx"), [text])
    base = os.path.join(tmp, "t22_base.docx")
    shutil.copy(src, base)
    dest = os.path.join(tmp, "t22_c.docx")
    code, out = run(HYGIENE, src, "--clean", "--baseline", base, "-o", dest,
                    "--log", os.path.join(tmp, "t22.md"))
    log = log_of(os.path.join(tmp, "t22.md"))
    review = (code == 2 and "hygiene result: REVIEW REQUIRED" in out
              and "--accept 'unicode|VS-RUN|present|REVIEWER|REASON'" in log
              and read_zip(dest)["word/document.xml"] == read_zip(src)["word/document.xml"])
    code2, out2 = run(HYGIENE, src, "--clean", "--baseline", base,
                      "-o", os.path.join(tmp, "t22_c2.docx"), "--log", os.path.join(tmp, "t22b.md"),
                      "--accept", "unicode|VS-RUN|present|A. Reviewer|source-controlled")
    accepted = code2 == 0 and "hygiene result: PASS WITH INFORMATIONAL FINDINGS" in out2
    acode, aout = run(ARTIFACTS, src)
    artifacts_silent = acode == 0 and "found: 0" in aout
    return review and accepted and artifacts_silent, (
        "review=%s accepted=%s artifacts_silent=%s" % (review, accepted, artifacts_silent))


# ---------------------------------------------------------------- Rev39 corrections

@case("T23. clean_artifacts refuses a --log that is the source or the actual output, in every "
      "mode and through aliases, with nothing written")
def t23(tmp):
    src = os.path.join(tmp, "t23.md")
    body = "Claim. :contentReference[oaicite:0]{index=0}\n"
    open(src, "w", encoding="utf-8").write(body)
    res = {}
    code, out = run(ARTIFACTS, src, "--log", src)
    res["report_log_is_source"] = code == 2 and "refused" in out and log_of(src) == body
    default_out = os.path.join(tmp, "t23_artifacts.md")
    code, out = run(ARTIFACTS, src, "--clean", "--log", default_out)
    res["clean_log_is_default_output"] = (code == 2 and "refused" in out
                                          and not os.path.exists(default_out)
                                          and log_of(src) == body)
    named = os.path.join(tmp, "named.md")
    code, out = run(ARTIFACTS, src, "--clean", "-o", named, "--log", named)
    res["clean_log_is_named_output"] = code == 2 and not os.path.exists(named)
    alias = os.path.join(tmp, "hard.md")
    os.link(src, alias)
    code, out = run(ARTIFACTS, src, "--log", alias)
    res["hard_link_to_source"] = code == 2 and log_of(src) == body
    sym = os.path.join(tmp, "sym.md")
    os.symlink(os.path.join(tmp, "t23_artifacts.md"), sym)
    code, out = run(ARTIFACTS, src, "--clean", "--log", sym)
    res["symlink_to_default_output"] = code == 2 and not os.path.exists(default_out)
    rel = os.path.join(tmp, "sub")
    os.mkdir(rel)
    code, out = run(ARTIFACTS, src, "--log", os.path.join(rel, "..", "t23.md"))
    res["dotdot_path_to_source"] = code == 2 and log_of(src) == body
    good_log = os.path.join(tmp, "report.md")
    code, out = run(ARTIFACTS, src, "--clean", "-o", os.path.join(tmp, "ok.md"),
                    "--log", good_log)
    res["separate_log_still_written"] = (code == 0 and os.path.exists(good_log)
                                         and log_of(src) == body)
    return all(res.values()), "%s" % res


@case("T24. Markdown fenced and inline code is reproduced exactly and flagged; prose and plain "
      "text are still cleaned")
def t24(tmp):
    md = ("Intro. :contentReference[oaicite:1]{index=1}\n"
          "\n"
          "```\n"
          "Example: :contentReference[oaicite:0]{index=0} and ?utm_source=chatgpt.com\n"
          "```\n"
          "~~~~text\n"
          "turn0search3 sample\n"
          "~~~~\n"
          "Inline `oaicite:3` and ``x :contentReference[oaicite:2]{index=2}`` here.\n"
          "Outside again. :contentReference[oaicite:4]{index=4}\n")
    src = os.path.join(tmp, "t24.md")
    open(src, "w", encoding="utf-8").write(md)
    dest = os.path.join(tmp, "t24_c.md")
    log = os.path.join(tmp, "t24_log.md")
    run(ARTIFACTS, src, "--clean", "-o", dest, "--log", log)
    out = log_of(dest).split("\n")
    want = md.split("\n")
    kept_code = out[2:8] == want[2:8] and "`oaicite:3`" in out[8] and \
        "``x :contentReference[oaicite:2]{index=2}``" in out[8]
    prose_cleaned = out[0] == "Intro." and out[9] == "Outside again."
    lg = log_of(log)
    flagged = ("inside a fenced code block, not edited" in lg
               and "inside a code span, not edited" in lg)
    unclosed = os.path.join(tmp, "t24u.md")
    open(unclosed, "w", encoding="utf-8").write("```\nx :contentReference[oaicite:0]{index=0}\n")
    run(ARTIFACTS, unclosed, "--clean", "-o", os.path.join(tmp, "t24u_c.md"))
    unclosed_kept = log_of(os.path.join(tmp, "t24u_c.md")) == log_of(unclosed)
    txt = os.path.join(tmp, "t24.txt")
    open(txt, "w", encoding="utf-8").write("```\nx :contentReference[oaicite:0]{index=0}\n```\n")
    run(ARTIFACTS, txt, "--clean", "-o", os.path.join(tmp, "t24_c.txt"))
    txt_cleaned = log_of(os.path.join(tmp, "t24_c.txt")) == "```\nx\n```\n"
    ok = kept_code and prose_cleaned and flagged and unclosed_kept and txt_cleaned
    return ok, ("kept_code=%s prose_cleaned=%s flagged=%s unclosed_kept=%s txt_cleaned=%s"
                % (kept_code, prose_cleaned, flagged, unclosed_kept, txt_cleaned))


def sign(path):
    """Add an OOXML digital-signature origin and signature part to a package.
    Synthetic: the structure the detection reads, not a cryptographic signature."""
    parts = read_zip(path)
    parts["_xmlsignatures/sig1.xml"] = (b'<?xml version="1.0"?><Signature '
                                        b'xmlns="http://www.w3.org/2000/09/xmldsig#"/>')
    parts["_xmlsignatures/_rels/origin.sigs.rels"] = (
        b'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
        b'package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.'
        b'openxmlformats.org/package/2006/relationships/digital-signature/signature" '
        b'Target="sig1.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in parts.items():
            z.writestr(n, b)
    return path


@case("T25. a digitally signed package is reported, and --clean refuses it before writing")
def t25(tmp):
    res = {}
    for kind, maker in (("docx", lambda p: make_docx(p, TOKEN_DOC)),
                        ("xlsx", lambda p: make_xlsx(p, cells=[("A1", TOKEN_DOC[0])])),
                        ("pptx", lambda p: make_pptx(p, [TOKEN_DOC[0]]))):
        src = sign(maker(os.path.join(tmp, "t25.%s" % kind)))
        before = read_zip(src)
        dest = os.path.join(tmp, "t25_c.%s" % kind)
        code, out = run(ARTIFACTS, src, "--clean", "-o", dest)
        rcode, rout = run(ARTIFACTS, src)
        res[kind] = (code == 2 and "digitally signed" in out and not os.path.exists(dest)
                     and read_zip(src) == before and "Digitally signed package" in rout)
    unsigned = make_docx(os.path.join(tmp, "t25u.docx"), TOKEN_DOC)
    code, _ = run(ARTIFACTS, unsigned, "--clean", "-o", os.path.join(tmp, "t25u_c.docx"))
    res["unsigned_still_cleaned"] = os.path.exists(os.path.join(tmp, "t25u_c.docx"))
    return all(res.values()), "%s" % res


@case("T26. SKILL.md carries a semantic version in its front matter and names every bundled script")
def t26(tmp):
    root = os.path.dirname(HERE)
    skill = log_of(os.path.join(root, "SKILL.md"))
    version = re.search(r'^  version: "(\d+\.\d+\.\d+)"', skill, re.M)
    scripts = sorted(f for f in os.listdir(os.path.join(root, "scripts"))
                     if f.endswith(".py"))
    missing = [f for f in scripts if "scripts/" + f not in skill]
    ok = bool(version) and not missing
    return ok, "version=%s missing=%s" % (version and version.group(1), missing)

IDENTITY_HASHES = {
    # SHA-256 of lower-case identifiers that must never appear in a shipped
    # package (a personal user name or an organization or project reference).
    # Stored hashed so the package does not carry the identifiers themselves.
    "ade7442362549c261f7dd957ec025f966d7381a091d0d4ffc208b25eb86e1513",
    "f26f4c0560bf7269f9369537c90953067e490ab5d7b5e6e5792461522b8f403f",
    "b6b48ca4c9bc57ccf9bda3449d30ca7a39970d0abe3dd06c4dd91189c173d99c",
    "1b18bf1f3caaf0eca35688ae7fc3473fee323e848ada0f3bf530ccdecee348ab",
    "a860d4ad683b8b9a514e08491e56ac9568084c3342f996dc57559e2d9a78cad5",
}


def identity_hits(package_dir):
    """(file, line, token) for every word, or hyphenated compound, in the
    package's text files whose lower-case SHA-256 is in IDENTITY_HASHES."""
    import hashlib
    hits = []
    for root, dirs, files in os.walk(package_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith((".py", ".md", ".txt", ".json")):
                continue
            path = os.path.join(root, f)
            for i, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
                tokens = set(re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", line))
                tokens |= {p for t in list(tokens) for p in t.split("-")}
                for t in tokens:
                    if hashlib.sha256(t.lower().encode()).hexdigest() in IDENTITY_HASHES:
                        hits.append((os.path.relpath(path, package_dir), i, t))
    return hits


@case("T27. no personal user name or organization or project identifier in the package")
def t27(tmp):
    hits = identity_hits(os.path.dirname(HERE))
    return not hits, "hits=%s" % [(f, i) for f, i, _ in hits]


# ---------------------------------------------------------------- Rev40 corrections

TOK = ":contentReference[oaicite:0]{index=0}"


def md_clean(tmp, name, text, ext=".md"):
    """Run the artifact clean on a Markdown or text fixture. Returns
    (exit, output text, report text, stdout)."""
    src = os.path.join(tmp, name + ext)
    with open(src, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    dest = os.path.join(tmp, name + "_c" + ext)
    log = os.path.join(tmp, name + "_log.md")
    code, out = run(ARTIFACTS, src, "--clean", "-o", dest, "--log", log)
    with open(dest, encoding="utf-8", newline="") as fh:
        cleaned = fh.read()
    return code, cleaned, log_of(log), out


@case("T28. an inline code span that crosses line breaks is kept exactly and flagged, with single "
      "and double backticks")
def t28(tmp):
    res = {}
    for label, fence in (("single", "`"), ("double", "``")):
        text = "Example %sstart\n%s\nend%s and done.\n" % (fence, TOK, fence)
        code, cleaned, log, out = md_clean(tmp, "t28_" + label, text)
        res[label] = (cleaned == text and code == 2 and "nothing left" not in out
                      and "inside a code span, not edited" in log)
    return all(res.values()), "%s" % res


@case("T29. a fenced block inside a blockquote or opened on a list-item line is kept exactly "
      "and flagged; quoted and listed prose is still cleaned, and a fence ends with its blockquote")
def t29(tmp):
    text = ("> Note %s\n>\n> ```\n> x %s\n> ```\n> after %s\n" % (TOK, TOK, TOK))
    code, cleaned, log, out = md_clean(tmp, "t29", text)
    kept = cleaned == "> Note\n>\n> ```\n> x %s\n> ```\n> after\n" % TOK
    flagged = "inside a fenced code block, not edited" in log and "nothing left" not in out
    open_text = "> ```\n> x %s\nOutside %s\n" % (TOK, TOK)
    _, cleaned2, _, _ = md_clean(tmp, "t29b", open_text)
    ends = cleaned2 == "> ```\n> x %s\nOutside\n" % TOK
    nested = "> > ```\n> > y %s\n> > ```\n" % TOK
    _, cleaned3, _, _ = md_clean(tmp, "t29c", nested)
    deep = cleaned3 == nested
    listed = "- ```\n  z %s\n  ```\n1. ```\n   w %s\n   ```\n- item %s\n" % (TOK, TOK, TOK)
    _, cleaned4, _, _ = md_clean(tmp, "t29d", listed)
    in_list = cleaned4 == "- ```\n  z %s\n  ```\n1. ```\n   w %s\n   ```\n- item\n" % (TOK, TOK)
    return kept and flagged and ends and deep and in_list, (
        "kept=%s flagged=%s ends=%s nested=%s list=%s" % (kept, flagged, ends, deep, in_list))


@case("T30. an indented code block (four spaces or a tab, after a blank line) is kept exactly and "
      "flagged; an indented line continuing a paragraph is still cleaned")
def t30(tmp):
    text = ("Para.\n\n    code %s\n\n    more %s\n\n\ttab %s\n\nAfter %s\n" % (TOK, TOK, TOK, TOK))
    code, cleaned, log, out = md_clean(tmp, "t30", text)
    kept = cleaned == ("Para.\n\n    code %s\n\n    more %s\n\n\ttab %s\n\nAfter\n"
                       % (TOK, TOK, TOK))
    flagged = (log.count("inside an indented code block, not edited") == 3
               and "nothing left" not in out)
    _, cleaned2, _, _ = md_clean(tmp, "t30b", "Paragraph line\n    continued %s\n" % TOK)
    lazy = cleaned2 == "Paragraph line\n    continued\n"
    return kept and flagged and lazy, "kept=%s flagged=%s lazy=%s" % (kept, flagged, lazy)


@case("T31. utm_source=chatgpt.com inside a multiline code span is kept and flagged; the same link "
      "in prose is still corrected")
def t31(tmp):
    url = "https://a.example/?q=1&utm_source=chatgpt.com"
    text = "See `start\n%s\nend` here.\n\nProse link %s done.\n" % (url, url)
    code, cleaned, log, out = md_clean(tmp, "t31", text)
    ok = (cleaned == "See `start\n%s\nend` here.\n\nProse link https://a.example/?q=1 done.\n"
          % url and "utm_source=chatgpt.com inside a code span, not edited" in log
          and "nothing left" not in out)
    return ok, "exit=%s" % code


@case("T32. outside code nothing changes: Markdown prose, CRLF line endings and plain text are "
      "cleaned as before")
def t32(tmp):
    res = {}
    code, cleaned, _, _ = md_clean(tmp, "t32a", "A %s `x %s` B %s\n" % (TOK, TOK, TOK))
    res["prose_beside_span"] = cleaned == "A `x %s` B\n" % TOK
    crlf = "A `s\r\n%s\r\ne` z %s\r\n" % (TOK, TOK)
    _, cleaned, _, _ = md_clean(tmp, "t32b", crlf)
    res["crlf"] = cleaned == "A `s\r\n%s\r\ne` z\r\n" % TOK
    _, cleaned, _, _ = md_clean(tmp, "t32c", "Odd ` tick %s\n" % TOK)
    res["unmatched_backtick"] = cleaned == "Odd ` tick\n"
    txt = "Example `start\n%s\nend`\n\n    code %s\n" % (TOK, TOK)
    code, cleaned, _, out = md_clean(tmp, "t32d", txt, ".txt")
    res["txt_unchanged_rule"] = cleaned == "Example `start\n\nend`\n\n    code\n" and code == 0
    return all(res.values()), "%s" % res


# ---------------------------------------------------------------- Rev41 corrections

@case("T33. indented code directly after a closed block is kept exactly and flagged: ATX and "
      "Setext headings, thematic breaks, closing fences, quoted variants and tabs")
def t33(tmp):
    tok = "turn0search3"
    res = {}
    for label, text in (
            ("atx", "# Example\n    %s\n" % tok),
            ("atx_tab", "## Example\n\t%s\n" % tok),
            ("thematic_dash", "---\n    %s\n" % tok),
            ("thematic_star", "***\n    %s\n" % tok),
            ("thematic_underscore", "___\n\t%s\n" % tok),
            ("setext_equals", "Title\n=====\n    %s\n" % tok),
            ("setext_dash", "Title\n-----\n    %s\n" % tok),
            ("after_backtick_fence", "```txt\nhello\n```\n    %s\n" % tok),
            ("after_tilde_fence", "~~~\nhello\n~~~\n\t%s\n" % tok),
            ("quoted_heading", "> # H\n>     %s\n" % tok),
            ("quoted_heading_then_top", "> # H\n    %s\n" % tok)):
        code, cleaned, log, out = md_clean(tmp, "t33_" + label, text)
        res[label] = (cleaned == text and "inside an indented code block, not edited" in log
                      and "nothing left" not in out)
    failed = [k for k, v in res.items() if not v]
    return not failed, "failed=%s" % failed


@case("T34. an indented line continuing paragraph or list text is still cleaned (controls)")
def t34(tmp):
    tok = "turn0search3"
    res = {}
    for label, text, want in (
            ("paragraph", "Ordinary paragraph\n    %s\n" % tok, "Ordinary paragraph\n\n"),
            ("paragraph_tab", "Ordinary paragraph\n\t%s\n" % tok, "Ordinary paragraph\n\n"),
            ("list_item", "- item\n    %s\n" % tok, "- item\n\n"),
            ("equals_without_paragraph", "===\n    %s\n" % tok, "===\n\n"),
            ("quoted_paragraph", "> para\n>     %s\n" % tok, "> para\n>\n")):
        code, cleaned, log, out = md_clean(tmp, "t34_" + label, text)
        res[label] = cleaned == want
    return all(res.values()), "%s" % res


# The CommonMark comparison (T35, T36). Inputs are generated deterministically
# from CM_BLOCKS: every ordered combination of two and three blocks (T35) and
# 20,000 documents of four blocks drawn with random.Random(41) (T36). Both
# references are test-only dependencies: commonmark.py and markdown-it-py.
# Where either is missing the cases are reported as SKIPPED. A skipped
# comparison is not a release verification; release QA runs it with both
# installed. Each non-blank line is compared:
#   - where the two references agree, the cleaner must agree with them;
#   - where they disagree, the disagreement must follow from a reading one
#     reference gives that CommonMark specification 0.31.2 rules out, and the
#     cleaner must side with the other reference. Two such readings exist:
#       A. markdown-it-py opens an indented code block on an unprefixed
#          indented line directly after a paragraph. Indented code cannot
#          interrupt a paragraph (sections 4.4 and 5.1): the line is lazy
#          paragraph text. From that line on, commonmark.py is the reference.
#       B. commonmark.py opens a type 7 HTML block directly after a paragraph.
#          A type 7 HTML block cannot interrupt a paragraph, lazy or not
#          (sections 4.6 and 5.1). From that line on, markdown-it-py is the
#          reference.
#     A line after both readings in one document has no reliable reference;
#     it is counted and reported, and the cleaner must match one of them.
#   - any other disagreement fails the case.
CM_BLOCKS = ["Para text", "Para two", "# Heading", "> # Quoted heading", "---", "***", "___",
             "Title\n===", "Title\n---", "```\nfenced\n```", "~~~\nfenced\n~~~",
             "    indented", "\tindented", "- item", "1. item", "1) item", "2. item", "> quote",
             "> > nested", ">     quoted indent", "<div>", "", "  indented two", "    ```", "- - -",
             "## H2 ##", "- item\n  - nested", "- item\n    - nested deep",
             "1. one\n   ```\n   code\n   ```", "- a\n\n      code in item", "-\n  late",
             "- item\n\n  para in item", ">     ```\n> x\n> ```", "<pre>\nx\n</pre>",
             "<!-- c\n-->", "<span>"]


def _cm_references():
    try:
        import commonmark
    except ImportError:
        raise Skip("commonmark (commonmark.py) is not installed; release QA must run this case")
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        raise Skip("markdown-it-py is not installed; release QA must run this case")
    return commonmark.Parser(), MarkdownIt("commonmark")


_UNPREFIXED_INDENT = re.compile(r"^(?: {4}| {0,3}\t)")


def _mi_reading(mi, text):
    """markdown-it-py code lines, and the first line of a class A reading."""
    lines = text.split("\n")
    code, para_end, quirk = set(), set(), None
    for t in mi.parse(text):
        if not t.map:
            continue
        if t.type == "paragraph_open":
            para_end.add(t.map[1])
        elif t.type in ("code_block", "fence"):
            code.update(range(*t.map))
            if (t.type == "code_block" and t.map[0] in para_end
                    and _UNPREFIXED_INDENT.match(lines[t.map[0]])
                    and (quirk is None or t.map[0] < quirk)):
                quirk = t.map[0]
    return code, quirk


def _cp_reading(cp, text):
    """commonmark.py code lines, and the first line of a class B reading."""
    import clean_artifacts as ca
    lines = text.split("\n")
    code, para_end, quirk = set(), set(), None
    for node, entering in cp.parse(text).walker():
        if not entering or not node.sourcepos:
            continue
        start, stop = node.sourcepos[0][0] - 1, node.sourcepos[1][0]
        if node.t == "code_block":
            code.update(range(start, stop))
        elif node.t == "paragraph":
            para_end.add(stop)
        elif node.t == "html_block" and start in para_end:
            first = lines[start].lstrip(" >")
            if not any(pat.match(first) for kind, pat, _ in ca.MD_HTML_START if kind != 7):
                quirk = start if quirk is None else min(quirk, start)
    return code, quirk


def cleaner_code_lines(text):
    import clean_artifacts as ca
    lines = text.split("\n")
    starts, pos = [], 0
    for line in lines:
        starts.append(pos)
        pos += len(line) + 1
    out = set()
    for a, b, label in ca.markdown_code_ranges(text):
        if label == "code span":
            continue
        out.update(i for i, st in enumerate(starts) if a <= st < b or (st == a == b))
    return out


def cm_compare(docs):
    cp, mi = _cm_references()
    wrong, unresolved = [], []
    counts = {"agree": 0, "A": 0, "B": 0, "both": 0}
    total = 0
    for text in docs:
        total += 1
        lines = text.split("\n")
        mi_code, qa = _mi_reading(mi, text)
        cp_code, qb = _cp_reading(cp, text)
        mine = cleaner_code_lines(text)
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            in_mi, in_cp, in_mine = i in mi_code, i in cp_code, i in mine
            if in_mi == in_cp:
                counts["agree"] += 1
                if in_mine != in_mi:
                    wrong.append((text, i + 1, "both references read %s"
                                  % ("code" if in_mi else "not code")))
                continue
            after_a = qa is not None and i >= qa
            after_b = qb is not None and i >= qb
            if after_a and after_b:
                counts["both"] += 1
            elif after_a:
                counts["A"] += 1
                if in_mine != in_cp:
                    wrong.append((text, i + 1, "class A: commonmark.py is the reference"))
            elif after_b:
                counts["B"] += 1
                if in_mine != in_mi:
                    wrong.append((text, i + 1, "class B: markdown-it-py is the reference"))
            else:
                unresolved.append((text, i + 1))
    detail = ("%d documents; lines where the references agree %d; disagreements resolved: "
              "class A %d, class B %d, after both %d; cleaner wrong %d, unresolved %d"
              % (total, counts["agree"], counts["A"], counts["B"], counts["both"],
                 len(wrong), len(unresolved)))
    for text, line, why in wrong[:5]:
        detail += "\n       wrong line %d of %r (%s)" % (line, text, why)
    for text, line in unresolved[:5]:
        detail += "\n       unresolved line %d of %r" % (line, text)
    print("     " + detail.split("\n")[0])
    return not wrong and not unresolved, detail


@case("T35. block code detection matches CommonMark on every ordered combination of two and "
      "three blocks (needs commonmark.py and markdown-it-py; SKIPPED without them)")
def t35(tmp):
    import itertools
    docs = ["\n".join(c) + "\n" for n in (2, 3) for c in itertools.product(CM_BLOCKS, repeat=n)]
    return cm_compare(docs)


@case("T36. block code detection matches CommonMark on 20,000 four-block documents drawn with "
      "a fixed seed (needs commonmark.py and markdown-it-py; SKIPPED without them)")
def t36(tmp):
    import random
    rnd = random.Random(41)
    docs = ["\n".join(rnd.choice(CM_BLOCKS) for _ in range(4)) + "\n" for _ in range(20000)]
    return cm_compare(docs)


@case("T37. code inside list items, nested lists included, is kept exactly and flagged; "
      "paragraph text inside an item is still cleaned")
def t37(tmp):
    tok = "turn0search3"
    kept, cleaned = {}, {}
    for label, text in (
            ("bullet_fence_4sp", "- item\n    ```\n    %s\n    ```\n" % tok),
            ("ordered_paren_fence", "1) item\n    ```\n    %s\n    ```\n" % tok),
            ("ordered_dot_fence", "1. one\n   ```\n   %s\n   ```\n" % tok),
            ("nested_list_fence", "- a\n  - b\n\n        ```\n        %s\n        ```\n" % tok),
            ("indented_in_item", "- a\n\n      %s\n" % tok),
            ("item_starts_with_code", "-     %s\n" % tok),
            ("nested_item_indented", "- a\n  - b\n\n          %s\n" % tok),
            ("item_in_quote_fence", "> - item\n>   ```\n>   %s\n>   ```\n" % tok)):
        code, out, log, std = md_clean(tmp, "t37k_" + label, text)
        kept[label] = out == text and "not edited" in log
    for label, text, want in (
            ("item_continuation", "- item\n    %s\n" % tok, "- item\n\n"),
            ("loose_item_paragraph", "- item\n\n  para %s\n" % tok, "- item\n\n  para\n"),
            ("nested_item_paragraph", "- a\n  - b %s\n" % tok, "- a\n  - b\n")):
        code, out, log, std = md_clean(tmp, "t37c_" + label, text)
        cleaned[label] = out == want
    ok = all(kept.values()) and all(cleaned.values())
    return ok, "kept=%s cleaned=%s" % ({k: v for k, v in kept.items() if not v},
                                       {k: v for k, v in cleaned.items() if not v})


@case("T38. container boundaries: a list item ends a quoted paragraph; HTML blocks are "
      "tracked; a type 7 tag on a lazy line does not hide the fence after it")
def t38(tmp):
    tok = "turn0search3"
    res = {}
    for label, text, want_kept in (
            ("item_ends_quote_para", "> quote\n2. item\n>     %s\n" % tok, True),
            ("empty_item_ends_quote_para", "> quote\n-\n  late\n>     %s\n" % tok, True),
            ("code_after_html_block", "<div>\n- a\n\n    %s\n" % tok, True),
            ("type7_lazy_then_fence", "- item\n<span>\n```\n%s\n```\n" % tok, True),
            ("nested_quote_lazy_indent", "> > nested\n    ```%s\n" % tok, False)):
        code, out, log, std = md_clean(tmp, "t38_" + label, text)
        res[label] = (out == text) == want_kept
    return all(res.values()), "%s" % {k: v for k, v in res.items() if not v}


@case("T39. inline code spans match CommonMark: the token is protected exactly where both "
      "reference parsers read it as code (needs commonmark.py and markdown-it-py)")
def t39(tmp):
    import itertools
    import clean_artifacts as ca
    cp, mi = _cm_references()
    tok = "turn0search3"
    pieces = ["`", "``", "\\`", "\\", "x", " ", "\nq ", tok]
    docs = set()
    for n in range(1, 7):
        for combo in itertools.product(pieces, repeat=n):
            if combo.count(tok) != 1:
                continue
            docs.add("p " + "".join(combo) + "\n")
    wrong, disagree = [], []

    def ref_mi(text):
        return any(tok in c.content for t in mi.parse(text) for c in (t.children or [])
                   if c.type == "code_inline")

    def ref_cp(text):
        return any(node.t == "code" and tok in (node.literal or "")
                   for node, entering in cp.parse(text).walker() if entering)

    for text in sorted(docs):
        a, b = ref_mi(text), ref_cp(text)
        if a != b:
            disagree.append(text)
            continue
        start = text.index(tok)
        mine = any(sa <= start and start + len(tok) <= sb
                   for sa, sb, lab in ca.markdown_code_ranges(text) if lab == "code span")
        if mine != a:
            wrong.append((text, a))
    detail = "%d documents; cleaner wrong %d, references disagree %d" % (
        len(docs), len(wrong), len(disagree))
    for text, a in wrong[:5]:
        detail += "\n       wrong %r (references: %s)" % (text, "code" if a else "not code")
    for text in disagree[:5]:
        detail += "\n       disagree %r" % text
    print("     " + detail.split("\n")[0])
    return not wrong and not disagree, detail


def main():
    failures = 0
    for name, fn in CASES:
        tmp = tempfile.mkdtemp(prefix="aifix_traces_")
        try:
            ok, detail = fn(tmp)
        except Skip as s:
            SKIPPED.append(name)
            print("SKIPPED %s (%s)" % (name, s))
            continue
        except Exception as e:  # a crash is a failure, never a pass
            ok, detail = False, "exception: %r" % e
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print("%s %s" % ("pass" if ok else "FAIL", name))
        if not ok:
            failures += 1
            print("     " + detail)
    run_count = len(CASES) - len(SKIPPED)
    print("\n%d case(s) run, %d failure(s), %d skipped" % (run_count, failures, len(SKIPPED)))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
