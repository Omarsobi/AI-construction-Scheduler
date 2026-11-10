#!/usr/bin/env python3
"""Extract text from a document, with a location for each passage.

Covers text a body-paragraph-only read would miss: table cells, chart titles
and cached chart labels, headers, footers, footnotes, endnotes, comments,
text boxes, slide notes, spreadsheet cell text and picture alt text.

    python extract_text.py FILE [--json] [--min-chars N] [--kinds body,chart,...]

Prints one line per passage: LOCATION<TAB>TEXT

Supports .docx, .pptx, .xlsx and any plain text format (.md, .txt, .html).

Slide layouts, masters, themes and style parts are skipped: their placeholder
text is scaffolding rather than text the reader sees.

How XML is read. Every part is parsed with an XML parser from its original
bytes, so the part's own encoding declaration is honoured (UTF-8, UTF-16 and
the other encodings the parser supports). Elements are matched on namespace
URI and local name, never on a literal prefix: a document that binds the
WordprocessingML namespace to x: instead of w: extracts exactly as it would
with w:. Transitional and Strict OOXML namespaces are both recognized.

Incomplete extraction is reported, never hidden. A package that cannot be
opened, or a text-bearing part that will not parse, is listed as a problem,
and the exit status is 2. A document whose supported locations genuinely hold
no text is reported as such, which is a different result from a failure.

Coverage caveat. This is supplementary extraction of the common OOXML text
locations, not a guarantee. Embedded objects, SmartArt data, some third-party
extensions, deleted revision text and content in linked or OLE parts may not
appear; embedded and OLE parts that are present are counted and named in the
report. Never treat a clean run of this script as proof that all
reader-visible text was reviewed. The pre-issue scan is run against the
document itself; this script only helps make sure less of it is missed.
"""

import argparse
import json
import os
import re
import sys


def _utf8_streams():
    """ai-language-fix Rev1: a Windows code page cannot encode every character
    this script reports (a hidden character, Arabic, a symbol in an excerpt),
    and the run stopped with UnicodeEncodeError. Write UTF-8 instead."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass


_utf8_streams()
import xml.etree.ElementTree as ET
import zipfile

NUMERIC = re.compile(r"^[-+]?[\d.,eE%]+$")

OOXML = (".docx", ".pptx", ".xlsx", ".docm", ".pptm", ".xlsm", ".dotx", ".potx")

# Namespace URIs, Transitional and Strict. Matching is on these and the local
# name, never on the prefix a file happens to use.
W_NS = {"http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "http://purl.oclc.org/ooxml/wordprocessingml/main"}
A_NS = {"http://schemas.openxmlformats.org/drawingml/2006/main",
        "http://purl.oclc.org/ooxml/drawingml/main"}
C_NS = {"http://schemas.openxmlformats.org/drawingml/2006/chart",
        "http://purl.oclc.org/ooxml/drawingml/chart"}
SS_NS = {"http://schemas.openxmlformats.org/spreadsheetml/2006/main",
         "http://purl.oclc.org/ooxml/spreadsheetml/main"}
P_NS = {"http://schemas.openxmlformats.org/presentationml/2006/main",
        "http://purl.oclc.org/ooxml/presentationml/main"}
WP_NS = {"http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
         "http://purl.oclc.org/ooxml/drawingml/wordprocessingDrawing"}
XDR_NS = {"http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
          "http://purl.oclc.org/ooxml/drawingml/spreadsheetDrawing"}
PIC_NS = {"http://schemas.openxmlformats.org/drawingml/2006/picture",
          "http://purl.oclc.org/ooxml/drawingml/picture"}
# The alt-text carriers this script has always read: wp:docPr, a:cNvPr,
# xdr:cNvPr and pic:cNvPr.
ALT_CARRIERS = (("docPr", WP_NS), ("cNvPr", A_NS), ("cNvPr", XDR_NS), ("cNvPr", PIC_NS))

HEADING_STYLE = re.compile(r"^(?:Heading|Title|TOC|Caption)", re.I)
TITLE_PLACEHOLDERS = ("title", "ctrTitle", "subTitle")

# Template scaffolding, not text a reader of the issued document sees.
SKIP = ("ppt/slideLayouts/", "ppt/slideMasters/", "ppt/notesMasters/",
        "ppt/handoutMasters/", "word/styles.xml", "word/numbering.xml",
        "word/settings.xml", "word/fontTable.xml", "word/theme/", "ppt/theme/",
        "xl/theme/", "xl/styles.xml", "customXml/")

# Parts that are present in some packages but whose text this script does not
# read. They are counted and named so the report never implies full coverage.
UNSUPPORTED = (("/embeddings/", "embedded object"), ("oleObject", "OLE object"),
               ("/activeX/", "ActiveX control"))


def split(tag):
    """(namespace URI, local name) of an element tag."""
    if isinstance(tag, str) and tag.startswith("{"):
        uri, local = tag[1:].split("}", 1)
        return uri, local
    return "", tag if isinstance(tag, str) else ""


def is_el(el, local, uris):
    uri, name = split(el.tag)
    return name == local and uri in uris


def parse(data):
    """Parse XML from bytes, honouring the part's own encoding declaration."""
    return ET.fromstring(data)


def attr(el, local, uris):
    for key, value in el.attrib.items():
        uri, name = split(key)
        if name == local and uri in uris:
            return value
    return None


def own_text(p, text_local, text_uris, para_local, para_uris):
    """Text of paragraph p, not descending into a paragraph nested inside it
    (a text box), which is reported as a passage of its own."""
    out = []

    def walk(el):
        for child in el:
            if is_el(child, para_local, para_uris):
                continue
            if is_el(child, text_local, text_uris) and child.text:
                out.append(child.text)
            walk(child)
    walk(p)
    return "".join(out).strip()


def word_paragraphs(root):
    """Every w:p in document order, as (element, text, in_table, is_heading).

    Numbering by position in this sequence is the pN in a location label, so
    any caller that needs to line up with extract() uses this function."""
    out = []

    def walk(el, in_table):
        for child in el:
            table = in_table or is_el(child, "tbl", W_NS)
            if is_el(child, "p", W_NS):
                style = ""
                for ppr in child:
                    if is_el(ppr, "pPr", W_NS):
                        for s in ppr:
                            if is_el(s, "pStyle", W_NS):
                                style = attr(s, "val", W_NS) or ""
                out.append((child, own_text(child, "t", W_NS, "p", W_NS), table,
                            bool(HEADING_STYLE.match(style))))
            walk(child, table)
    walk(root, False)
    return out


def drawing_paragraphs(root):
    """Every a:p in document order, as (element, text, in_table, in_title)."""
    out = []

    def title_shape(sp):
        for el in sp.iter():
            if is_el(el, "ph", P_NS) and el.get("type") in TITLE_PLACEHOLDERS:
                return True
        return False

    def walk(el, in_table, in_title):
        for child in el:
            table = in_table or is_el(child, "tbl", A_NS)
            title = in_title or (is_el(child, "sp", P_NS) and title_shape(child))
            if is_el(child, "p", A_NS):
                out.append((child, own_text(child, "t", A_NS, "p", A_NS), table, title))
            walk(child, table, title)
    walk(root, False, False)
    return out


def kind_for(part):
    table = [("word/document.xml", "body"), ("word/header", "header"),
             ("word/footer", "footer"), ("word/footnotes", "footnote"),
             ("word/endnotes", "endnote"), ("word/comments", "comment"),
             ("word/charts/", "chart"), ("ppt/slides/", "slide"),
             ("ppt/notesSlides/", "slide-notes"), ("ppt/charts/", "chart"),
             ("ppt/diagrams/", "diagram"), ("xl/sharedStrings", "cell-text"),
             ("xl/charts/", "chart"), ("xl/worksheets/", "sheet"),
             ("xl/drawings/", "drawing"), ("word/drawings/", "drawing")]
    for prefix, name in table:
        if part.startswith(prefix):
            return name
    return os.path.basename(part).replace(".xml", "")


def si_text(si):
    return "".join(t.text or "" for t in si.iter() if is_el(t, "t", SS_NS)).strip()


def shared_strings(root):
    if root is None:
        return []
    return [si_text(si) for si in root if is_el(si, "si", SS_NS)]


def sheet_names(root):
    if root is None:
        return {}
    out = {}
    for el in root.iter():
        if is_el(el, "sheet", SS_NS) and el.get("name") and el.get("sheetId"):
            out[el.get("sheetId")] = el.get("name")
    return out


def from_worksheet(root, strings, label):
    """Resolve each text cell to its wording and its A1 reference."""
    out = []
    for c in root.iter():
        if not is_el(c, "c", SS_NS):
            continue
        ref = c.get("r") or "?"
        typ = c.get("t") or "n"
        v = next((x for x in c if is_el(x, "v", SS_NS)), None)
        if typ == "s":
            text = ""
            if v is not None and v.text:
                try:
                    text = strings[int(v.text.strip())]
                except (ValueError, IndexError):
                    text = ""
        elif typ in ("inlineStr", "str"):
            inline = "".join(t.text or "" for t in c.iter() if is_el(t, "t", SS_NS))
            text = (inline or (v.text if v is not None and v.text else "")).strip()
        else:
            continue
        if text and not NUMERIC.match(text):
            out.append((f"{label}!{ref}", text))
    return out


def alt_texts(root):
    out = []
    for el in root.iter():
        uri, name = split(el.tag)
        if not any(name == local and uri in uris for local, uris in ALT_CARRIERS):
            continue
        for key, value in el.attrib.items():
            if split(key)[1] in ("descr", "title") and value.strip():
                out.append(value.strip())
                break
    return out


def from_ooxml(path):
    """Returns (rows, problems, notes)."""
    rows, problems, notes = [], [], []
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        return [], ["cannot open %s as an OOXML package: %s" % (os.path.basename(path), e)], []
    with z:
        names = z.namelist()
        roots = {}

        def load(part):
            if part in roots:
                return roots[part]
            try:
                roots[part] = parse(z.read(part))
            except KeyError:
                roots[part] = None
            except (ET.ParseError, ValueError, LookupError) as e:
                roots[part] = None
                problems.append("%s will not parse as XML (%s); its text was not extracted"
                                % (part, e))
            return roots[part]

        strings = shared_strings(load("xl/sharedStrings.xml")
                                 if "xl/sharedStrings.xml" in names else None)
        sheets = sheet_names(load("xl/workbook.xml") if "xl/workbook.xml" in names else None)

        for part in sorted(n for n in names if n.endswith(".xml")):
            if part.startswith("docProps") or "/_rels/" in part:
                continue
            if part.startswith(SKIP):
                continue
            root = load(part)
            if root is None:
                continue
            kind = kind_for(part)
            base = os.path.basename(part)
            seen = []

            if part.startswith("xl/worksheets/"):
                sid = re.search(r"sheet(\d+)\.xml", base)
                label = sheets.get(sid.group(1), base) if sid else base
                seen += from_worksheet(root, strings, label)

            elif part == "xl/sharedStrings.xml":
                for i, t in enumerate(strings, 1):
                    if t:
                        seen.append((f"{kind}:{i}", t))

            else:
                # Word paragraphs and DrawingML paragraphs are both collected.
                # A chart part carries its titles and labels as DrawingML and
                # its cached category and series text as c:v, so neither is
                # skipped in favour of the other.
                for i, (_, t, _, _) in enumerate(word_paragraphs(root), 1):
                    if t:
                        seen.append((f"{kind}:{base}:p{i}", t))
                for i, (_, t, _, _) in enumerate(drawing_paragraphs(root), 1):
                    if t:
                        seen.append((f"{kind}:{base}:a{i}", t))
                if kind == "chart":
                    values = [el.text for el in root.iter() if is_el(el, "v", C_NS)]
                    for i, v in enumerate(values, 1):
                        t = (v or "").strip()
                        if t and not NUMERIC.match(t):
                            seen.append((f"chart-data:{base}:{i}", t))

            for i, t in enumerate(alt_texts(root), 1):
                seen.append((f"alt-text:{base}:{i}", t))

            rows.extend(seen)

        for marker, label in UNSUPPORTED:
            hits = [n for n in names if marker in n and not n.endswith("/")]
            if hits:
                notes.append("not extracted: %d %s part(s), for example %s"
                             % (len(hits), label, hits[0]))
    return rows, problems, notes


def from_text(path):
    try:
        with open(path, encoding="utf8", errors="replace") as fh:
            rows = [(f"line:{i}", line.rstrip()) for i, line in enumerate(fh, 1)
                    if line.strip()]
        return rows, [], []
    except OSError as e:
        return [], ["cannot read %s: %s" % (path, e)], []


def extract_report(path):
    """(rows, problems, notes). problems lists anything that makes the
    extraction materially incomplete; notes lists known unsupported content
    present in the file. Callers that compare or count must check problems."""
    ext = os.path.splitext(path)[1].lower()
    if ext in OOXML:
        return from_ooxml(path)
    return from_text(path)


def extract(path):
    """Rows only, for callers that only list text. It does not reveal an
    incomplete extraction; use extract_report wherever that matters."""
    return extract_report(path)[0]


def bucket(location):
    return location.split(":")[0].split("!")[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-chars", type=int, default=1)
    ap.add_argument("--kinds", help="comma-separated location kinds to keep, "
                                    "for example chart,header,footer,alt-text")
    args = ap.parse_args()

    all_rows, problems, notes = extract_report(args.file)
    rows = [(l, t) for l, t in all_rows if len(t) >= args.min_chars]
    if args.kinds:
        keep = {k.strip() for k in args.kinds.split(",")}
        rows = [(l, t) for l, t in rows if bucket(l) in keep]

    if args.json:
        json.dump({"passages": [{"location": l, "text": t} for l, t in rows],
                   "problems": problems, "notes": notes}, sys.stdout, indent=1)
        print()
    else:
        for l, t in rows:
            print(f"{l}\t{t}")

    kinds = {}
    for l, _ in rows:
        kinds[bucket(l)] = kinds.get(bucket(l), 0) + 1
    print(f"\n# {len(rows)} passages, {sum(len(t.split()) for _, t in rows)} words",
          file=sys.stderr)
    print("# by location: " + (", ".join(f"{k} {v}" for k, v in sorted(kinds.items()))
                                or "none"), file=sys.stderr)
    for n in notes:
        print("# " + n, file=sys.stderr)
    if problems:
        print("# INCOMPLETE extraction:", file=sys.stderr)
        for p in problems:
            print("#   " + p, file=sys.stderr)
        return 2
    if not all_rows:
        print("# the supported text locations of this file hold no text; this is an "
              "empty result, not a failure", file=sys.stderr)
    print("# supplementary extraction, not a coverage guarantee: embedded objects, "
          "SmartArt and linked parts may not appear", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
