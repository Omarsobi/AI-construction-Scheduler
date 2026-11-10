#!/usr/bin/env python3
"""Package and metadata hygiene for AI Fix deliverables.

Inspects, and on request cleans, unnecessary tool, add-in, personal and
local-path metadata in an Office Open XML package, and inspects PDF metadata.

Separate from character cleanup. This script never touches wording, formulas,
cell values, slide content or visible document text.

Scope in this copy: .docx, .pptx, .xlsx (inspect and clean),
.pdf (inspect only), .txt and .md (visible-content notes only).

Design rules, after repeated defects traced to string handling of XML:
  - Every metadata part is parsed with an XML parser and every element is
    matched on its local name. A namespace prefix is an alias chosen by
    whoever wrote the file and is never matched literally.
  - Writing a value goes through the parser, so an ampersand or an angle
    bracket in a name is escaped rather than corrupting the part.
  - One classification routine serves both the inspection run and the
    post-clean verification, so the two can never disagree about coverage.
  - Automatic deletion is limited to identified integration metadata and
    confirmed local working paths. Anything else carrying a tool name is
    reported for a decision, because a tool name can be legitimate content.
  - An ordinary http or https link is functional content, not evidence of
    authorship, even where the host carries a tool name.

Usage
    python metadata_hygiene.py file.xlsx                  # scan, writes only its report
    python metadata_hygiene.py file.xlsx --clean          # write file_clean.xlsx
    python metadata_hygiene.py file.docx --clean --blank-author
    python metadata_hygiene.py file.docx --clean --author "A. Preparer"
    python metadata_hygiene.py file.pdf                   # inspection only
    python metadata_hygiene.py file.docx --clean --baseline before.docx --log run.md

Every run writes a report, by default the input's name with _metahygiene.md,
or the path given with --log. Before anything is written, every destination is
checked against the source, the baseline, a supplied --certificate, the file
being recertified and the run's other output, by path, resolved path, symbolic
link and hard link. A collision is refused with exit status 2, the reason goes
to stdout and stderr, nothing is written and no PASS is reported. Recertifying
never writes over the certificate it checks: where the default report path is
the certificate, pass --log with a separate path.

Removed automatically:
  - Office web-extension parts whose own content carries an integration marker
    or a local path, or whose Office Store reference id is a known
    writing-assistant add-in (Grammarly for Microsoft Word WA200001011, QuillBot
    WA200000368), with their relationship entries, task-pane entries and
    content-type declarations. An extension without a marker is preserved.
  - custom document properties whose name is a known integration key, currently
    claude.fileId and GrammarlyDocumentId, matched on the whole name and
    case-insensitively, or whose name or value is a local working path
  - (Rev31 also removed any custom property whose name or value named
    Grammarly or QuillBot. Rev33 supersedes that: such a property is reported.)
  - the Excel absolute-path record absPath
  - HyperlinkBase where its value is a local working path

Grammarly and QuillBot metadata is classified as writing-assistant integration
metadata. In .docx, .pptx and .xlsx, confirmed integration residue is removed:
GrammarlyDocumentId by name, and a web extension carrying either tool's name or
Office Store id. Everything else naming either tool is detected and reported
for a decision, because a tool name alone does not show that the item is
disposable: a custom property naming either tool in its name or value (Rev33;
Rev31 removed these), a core or app property (title, subject, author, company
and the like), a custom XML part, a relationship target, visible document
content, PDF metadata, and browser-extension HTML residue in a text
file (data-gr-ext-installed, data-new-gr-c-s-check-loaded, grammarly-extension,
quillbot-extension). No such finding is evidence of
generative AI use or AI authorship, and none is reported as such. Document
content is never edited by this script to remove one.

Annotations, that is cell comments, notes, threaded comments and document
comments, follow the annotation rule. An annotation already in the file is
protected source content and is never deleted, rewritten or re-authored. An
annotation absent from the pre-edit inventory supplied with --baseline was
created during processing and is removed, with only the infrastructure it
brought with it. One altered during processing is restored exactly. Without an
inventory nothing is guessed at: every annotation is preserved and the run
reports that it cannot certify the result. This script never creates an
annotation of its own for any purpose.

Reported, never removed automatically: external links, defined names, custom
XML, connections, embedded and OLE objects, custom properties carrying a tool
name without being integration metadata, and author or company fields, which
change only under --author or --blank-author.

A digitally signed package is not cleaned. Repackaging invalidates the
signature, so the script reports it and stops.

Trace detection (AI Fix Rev37, Fix Language Rev 3.20, shared logic). The same
run also detects, and never edits: generation-only citation tokens (ChatGPT
contentReference and oaicite tokens, turn0search-style handles and their
wrappers) and the utm_source=chatgpt.com tracking parameter in document text
and hyperlink targets; hidden Unicode characters, classified as invisible
controls, language-dependent characters (Arabic joiners and directional
marks, always preserved and informational) or informational characters, with
a run of two or more variation selectors reported as an invisible control
under VS-RUN (AI Fix Rev38, Fix Language Rev 3.22); and
generator-library metadata (python-docx, python-pptx, openpyxl, PptxGenJS,
ReportLab, pdf-lib, pypdf, wkhtmltopdf), with their default author values and
template dates reported only. A generator finding indicates programmatic file
generation, not that AI wrote the content.

Outcomes: PASS; PASS WITH INFORMATIONAL FINDINGS, where disclosed
informational traces remain; REVIEW REQUIRED, where an ambiguous finding needs
a human decision before certification; FAIL, where a confirmed defect remains
or a required check fails. Only the first two are passes.

Exit status 0 on a pass, 2 on a failure, a refusal, or an inspection that
cannot be completed.
Standard library only.
"""

import argparse
import copy
import hashlib
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
import time
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SUPPORTED_OOXML = (".docx", ".pptx", ".xlsx")
SUPPORTED_TEXT = (".txt", ".md")
SUPPORTED_PDF = (".pdf",)

TOOL_PATTERNS = [
    "claude", "anthropic", "chatgpt", "openai", "copilot", "gpt",
    "grammarly", "quillbot",
    "ai-generated", "ai generated",
]

# Writing-assistant tools whose metadata is integration metadata. A custom
# property merely naming one of them is reported and kept until a decision is
# recorded with --accept (Rev33; Rev31 removed it). Only the known integration
# key and the add-in are removed. Found anywhere else, the name is reported.
WRITING_ASSISTANTS = {"grammarly": "Grammarly", "quillbot": "QuillBot"}

# Office Store asset ids of writing-assistant add-ins, matched on the whole
# reference id of a web extension and case-insensitively. Verified against the
# Office Store listing for each asset id on 29-Sep-26.
WEBEXT_STORE_IDS = {
    "wa200001011": "Grammarly for Microsoft Word (Office Store WA200001011)",
    "wa200000368": "QuillBot (Office Store WA200000368)",
}

# Markup that the Grammarly and QuillBot browser extensions inject into a page
# and that survives when that HTML is pasted or saved. Reported in text files.
EXTENSION_RESIDUE = re.compile(
    r"data-gr-ext-installed|data-new-gr-c-s-check-loaded|grammarly-extension"
    r"|quillbot-extension[\w-]*", re.I)

# What a writing-assistant marker means, so a log entry is never read as a
# finding of generative AI use. Its metadata records that the add-in or
# extension touched the file, nothing more.
WRITING_ASSISTANT_NOTE = (
    "Grammarly and QuillBot findings above are writing-assistant integration "
    "metadata. They record that the Grammarly or QuillBot add-in, extension or "
    "application touched the file. They do not establish generative AI use or AI "
    "authorship and are not reported as evidence of either.")

# Custom-property names that are integration metadata by definition, matched on
# the whole name and case-insensitively, never as a substring. Only a name on
# this list is deleted on the strength of its name alone.
INTEGRATION_KEYS = {
    "claude.fileid": "known integration key",
    "grammarlydocumentid": ("Grammarly document identifier, a known writing-assistant "
                            "integration key"),
}

PATH_PATTERNS = [
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:\\[^\"'<>|*?\r\n]*"),
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:/(?!/)[^\"'<>|*?\r\n]*"),
    re.compile(r"\\\\[A-Za-z0-9._-]+\\[^\"'<>|*?\r\n]*"),
    re.compile(r"(?<![A-Za-z0-9._~%+-])/Users/[^\"'<>|*?\r\n]*"),
    re.compile(r"file:///[^\"'<>\s]+", re.I),
]

URL = re.compile(r"https?://[^\s\"'<>]+", re.I)

WEBEXT_DIR = re.compile(r"^(word|xl|ppt)/webextensions/", re.I)
WEBEXT_PART = re.compile(r"^(word|xl|ppt)/webextensions/webextension\d*\.xml$", re.I)
TASKPANES_PART = re.compile(r"^(word|xl|ppt)/webextensions/taskpanes\.xml$", re.I)
SIGNATURE_PART = re.compile(r"^_xmlsignatures/", re.I)

REPORT_ONLY_PARTS = [
    (re.compile(r"^xl/persons/", re.I), "threaded-comment person list"),
    (re.compile(r"^xl/threadedComments/", re.I), "threaded comments"),
    (re.compile(r"^xl/comments", re.I), "cell comments"),
    (re.compile(r"^word/comments", re.I), "document comments"),
    (re.compile(r"^ppt/comments", re.I), "slide comments"),
    (re.compile(r"^xl/externalLinks/", re.I), "external links"),
    (re.compile(r"^customXml/", re.I), "custom XML"),
    (re.compile(r"^xl/connections\.xml$", re.I), "data connections"),
    (re.compile(r"embeddings/", re.I), "embedded object"),
    (re.compile(r"oleObject", re.I), "OLE object"),
    (re.compile(r"\.bin$", re.I), "embedded binary part"),
]

DOCPROPS = ("docProps/core.xml", "docProps/app.xml", "docProps/custom.xml")
DC_NS = "http://purl.org/dc/elements/1.1/"
CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
AUTHOR_NS = {"creator": DC_NS, "lastModifiedBy": CP_NS}
AUTHOR_TAGS = ("creator", "lastModifiedBy")
COMPANY_TAGS = ("Company", "Manager")

# Field context decides what a tool name in a metadata value means.
# Provenance says who or what produced the file, so a tool name there is a
# provenance question. Descriptive says what the file is about, so a tool name
# there may simply be the subject and is reported for a decision.
PROVENANCE_FIELDS = ("creator", "lastModifiedBy", "Company", "Manager",
                     "Application", "AppVersion", "Template", "CreatorTool")
DESCRIPTIVE_FIELDS = ("title", "subject", "description", "keywords", "category",
                      "contentStatus")
PDF_PROVENANCE = ("/Author", "/Creator", "/Producer", "CreatorTool", "creator", "Producer",
                  "Author")
PDF_DESCRIPTIVE = ("/Title", "/Subject", "/Keywords", "/Description", "/Category",
                   "title", "description")

# kinds that make a package fail
# artifact and review are the Rev37 / Rev 3.20 trace kinds, see trace_findings.
FAILING = ("remove", "metadata", "package", "author-marker", "report-marker",
           "artifact", "review")
NO_MUTATION = ("keep", "keep-unverified", "report-manual", "relocated")


# ---------------------------------------------------------------- basics

def read_parts(path):
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad is not None:
            raise IOError("corrupt package member: %s" % bad)
        return {n: z.read(n) for n in z.namelist()}


def as_text(b):
    try:
        return b.decode("utf-8", "replace")
    except Exception:
        return ""


def local_name(tag):
    return tag.split("}")[-1]


def without_urls(text):
    """An ordinary http or https link is functional content, not a trace."""
    return URL.sub(" ", text)


def keyword_hits(text, strip_urls=True):
    """strip_urls=False where a URL is itself the metadata under inspection,
    as in an Office web-extension definition, whose service URL is exactly the
    integration this procedure looks for."""
    low = (without_urls(text) if strip_urls else text).lower()
    return sorted({p for p in TOOL_PATTERNS + GENERATOR_PATTERNS if p in low})


def path_hits(text):
    out = []
    for rx in PATH_PATTERNS:
        for m in rx.findall(text):
            m = m.strip()
            if len(m) > 3 and m not in out:
                out.append(m)
    return out[:20]


def markers(text, strip_urls=True):
    return keyword_hits(text, strip_urls), path_hits_in_field(text)


def has_marker(text, strip_urls=True):
    kw, lp = markers(text, strip_urls)
    return bool(kw or lp)


def path_hits_in_field(value):
    """Local paths in a field that may legitimately hold an http link.

    An http or https URL is removed before the test, so a path-like segment
    inside a URL, such as https://example.com/C:/docs, is not read as a local
    path. A file:/// URL is still a local path and survives the removal.
    """
    return path_hits(without_urls(value))


def mentions_writing_assistant(lines):
    """True where any reported line names Grammarly or QuillBot, so the log can
    carry the classification note. It reads the report text only and decides
    nothing."""
    return any(k in (line or "").lower() for line in lines for k in WRITING_ASSISTANTS)


def webext_store_hits(data):
    """Known writing-assistant add-ins named by a web extension's Office Store
    reference id. The id is matched whole, never as a substring."""
    root = parse(data)
    if root is None:
        return []
    out = []
    for node in find_local(root, "reference"):
        rid = (node.get("id") or "").strip().lower()
        if rid in WEBEXT_STORE_IDS and WEBEXT_STORE_IDS[rid] not in out:
            out.append(WEBEXT_STORE_IDS[rid])
    return out


def describe(kw, lp):
    parts = []
    tools = [k for k in kw if k not in GENERATOR_PATTERNS]
    gens = [k for k in kw if k in GENERATOR_PATTERNS]
    if tools:
        parts.append("tool name: " + ", ".join(tools))
    if gens:
        parts.append("generator library: " + ", ".join(gens))
    if lp:
        parts.append("local path: " + "; ".join(lp))
    return "; ".join(parts)


def resolve_target(rels_name, target):
    base = os.path.dirname(os.path.dirname(rels_name))
    joined = os.path.join(base, target) if base else target
    return os.path.normpath(joined).replace("\\", "/").lstrip("/")


def is_content_part(name):
    """Parts a reader sees. A tool name here is subject matter, not provenance.

    Charts, drawings and diagrams carry titles, labels and text a reader sees,
    so a chart titled "OpenAI Adoption" is business content and not a trace.
    """
    return bool(re.match(
        r"^(word/document|word/header|word/footer|word/footnotes|word/endnotes"
        r"|xl/sharedStrings|xl/worksheets/|ppt/slides/|ppt/notesSlides/"
        r"|(xl|word|ppt)/charts/|(xl|word|ppt)/drawings/|(xl|word|ppt)/diagrams/"
        r"|(xl|word|ppt)/chartsheets/)", name, re.I))


# ---------------------------------------------------------------- trace detection
#
# AI Fix Rev37 / Fix Language Rev 3.20. Shared logic: this block is identical
# in both copies of this script, and an amendment to it goes into both in the
# same pass. It detects and classifies; nothing in it edits a file.
#
# Three families are covered: generator-library metadata (programmatic file
# generation, not evidence that AI wrote the content), generation-only
# citation tokens and the utm_source=chatgpt.com tracking parameter, and
# hidden Unicode characters. Classification decides the outcome:
#   artifact  a confirmed defect that remains, fails the result
#   review    an ambiguous finding that needs a human decision first
#   info      disclosed, does not stop a pass

# Libraries that write their own name into document metadata by default.
# Matched case-insensitively, like TOOL_PATTERNS, and reported under their own
# label so a finding is never read as a finding of AI use.
GENERATOR_PATTERNS = ["python-docx", "python-pptx", "openpyxl", "pptxgenjs", "reportlab",
                      "pdf-lib", "pypdf", "wkhtmltopdf"]

GENERATOR_NOTE = (
    "Generator-library findings above (python-docx, python-pptx, openpyxl, PptxGenJS, "
    "ReportLab, pdf-lib, pypdf, wkhtmltopdf, their default field values and their template "
    "dates) indicate that the file was produced or saved programmatically. They do not "
    "establish that AI wrote the content and are not reported as evidence of it.")

# Default values a library writes into an author field. Reported only: never a
# replacement target, never a failure on its own.
LIBRARY_DEFAULT_VALUES = {
    "steve canny": "the python-pptx template default for lastModifiedBy",
    "un-named": "the docx (npm) library default for creator and lastModifiedBy",
}

# Creation and modification dates carried over from a library's bundled
# template. Reported only.
TEMPLATE_DATES = (
    ("python-docx", "2013-12-23T23:15:00Z", "2013-12-23T23:15:00Z"),
    ("python-pptx", "2013-01-27T09:14:16Z", "2013-01-27T09:15:58Z"),
)

# ChatGPT citation handles: turn, a number, a source type, a number. Bounded
# on both sides so an ordinary word is never matched.
_CITE_TYPES = ("search|click|fetch|view|news|image|file|product|finance|forecast|sports"
               "|calc|time")
_TURN = r"turn\d+(?:%s)\d+" % _CITE_TYPES

# Confirmed generation-only tokens, in priority order. A span matched by an
# earlier pattern is not matched again by a later one.
CITATION_CONFIRMED = (
    ("ChatGPT wrapped citation",
     re.compile(r"(?:cite|filecite|navlist)[^\r\n]{1,300}")),
    ("ChatGPT citation handle",
     re.compile(r"(?<![A-Za-z0-9])(?:cite|filecite|navlist)(?:?" + _TURN
                + r")+(?:?L\d+(?:-L\d+)?)??")),
    ("contentReference citation token",
     re.compile(r":?contentReference\[oaicite:\d+\]\{index=\d+\}")),
    ("oaicite citation token", re.compile(r"\[?oaicite:\d+\]?")),
    # ai-language-fix Rev3: further generation-only forms.
    ("oai_citation token",
     re.compile(r"\[?oai_citation(?:_attribution)?:\d+[^\]\s]{0,60}\]?")),
    ("attribution JSON fragment",
     re.compile(r'\{"attribution":\s*\{"attributableIndex":\s*"[^"\r\n]{0,40}"\}\}')),
    ("ChatGPT citation handle",
     re.compile(r"(?<![A-Za-z0-9])" + _TURN + r"(?![A-Za-z0-9])")),
    ("ChatGPT source marker",
     re.compile("【\\d+(?::\\d+)?†[^】\\r\\n]{1,120}】")),
)

# Residues whose purpose cannot be confirmed from the text alone. Flagged for
# review, never removed automatically.
CITATION_SUSPECT = (
    ("incomplete contentReference residue", re.compile(r"contentReference")),
    # ai-language-fix Rev3: forms reported in chatbot output whose purpose
    # cannot be confirmed from the text alone. Review, never removed.
    ("attached_file reference residue",
     re.compile(r"(?<![A-Za-z0-9_])attached_file(?::\d+)?(?![A-Za-z0-9_])")),
    ("grok_card residue", re.compile(r"(?<![A-Za-z0-9_])grok_card(?![A-Za-z0-9_])")),
    ("[web:N] source tag", re.compile(r"\[web:\d+\]")),
    ("attributableIndex residue", re.compile(r"attributableIndex")),
    ("incomplete citation handle",
     re.compile(r"(?<![A-Za-z0-9])turn\d+(?:%s)(?![A-Za-z0-9])" % _CITE_TYPES)),
    ("stray citation wrapper character", re.compile("[-]")),
)

# A confirmed token standing between quotation marks or backticks may be the
# subject of the text, as in a document that discusses these tokens, so its
# purpose is ambiguous and it is flagged rather than removed.
QUOTE_CHARS = "\"'`“”‘’"

# The exact tracking parameter, as a whole name=value pair.
# ai-language-fix Rev3: utm_source=openai is the later value of the same parameter.
UTM_VALUES = ("chatgpt.com", "openai")
UTM_CHATGPT = re.compile(r"(?<![A-Za-z0-9_])utm_source=(?:chatgpt\.com|openai)(?![A-Za-z0-9.-])",
                         re.I)


def utm_found(s):
    """The tracking pair as it appears in s, lower-cased, for a message."""
    m = UTM_CHATGPT.search(s or "")
    return m.group(0).lower() if m else "utm_source=chatgpt.com"
# A URL inside running text. Stops at whitespace, quotes, angle brackets and a
# closing bracket, so a Markdown link target ends where the link does.
URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>)\]]+", re.I)

# Hidden Unicode. Three classes, kept apart:
#   invisible control   no legitimate reason to sit in ordinary prose
#   language-dependent  joiners and directional marks that Arabic and other
#                       scripts need; informational, never a failure
#   informational       visible-effect or font-specific characters that may be
#                       legitimate (soft hyphen, narrow no-break space, a single
#                       variation selector, private-use symbols)
# A variation selector in a run of two or more consecutive selectors (either
# range, U+FE00-U+FE0F or U+E0100-U+E01EF) is classed invisible control under
# the key VS-RUN: no legitimate text places two selectors in a row, and runs
# of them are the usual way a hidden payload is carried (Rev38).
HIDDEN_CONTROL = "invisible control"
HIDDEN_LANGUAGE = "language-dependent"
HIDDEN_INFO = "informational"
HIDDEN_RX = re.compile("[­​-‏‪- ⁠-⁤⁦-⁩"
                       "︀-️﻿-\U000e0000-\U000e007f\U000e0100-\U000e01ef]")
VS_RUN_RX = re.compile("[\ufe00-\ufe0f\U000e0100-\U000e01ef]{2,}")
VS_RUN = 0x110000                 # key for selectors in a run; beyond Unicode, sorts last


def hidden_class(cp):
    if cp == VS_RUN:
        return HIDDEN_CONTROL
    if cp in (0x200C, 0x200D, 0x200E, 0x200F):
        return HIDDEN_LANGUAGE
    if (cp in (0x200B, 0xFEFF) or 0x2060 <= cp <= 0x2064 or 0x202A <= cp <= 0x202E
            or 0x2066 <= cp <= 0x2069 or 0xE0000 <= cp <= 0xE007F):
        return HIDDEN_CONTROL
    return HIDDEN_INFO


def hidden_id(cp):
    """The identifier used in a finding and in an --accept key."""
    return "VS-RUN" if cp == VS_RUN else "U+%04X" % cp


def hidden_hits(text):
    """(start, end, key) for each hidden character in text, in order. A
    variation selector inside a run of two or more is keyed VS_RUN and carries
    the span of the whole run; every other character is keyed by its code
    point. Counts stay one per character, so baseline comparison is by
    character, not by run."""
    runs = [(m.start(), m.end()) for m in VS_RUN_RX.finditer(text)]
    out, ri = [], 0
    for m in HIDDEN_RX.finditer(text):
        s = m.start()
        while ri < len(runs) and runs[ri][1] <= s:
            ri += 1
        if ri < len(runs) and runs[ri][0] <= s < runs[ri][1]:
            out.append((runs[ri][0], runs[ri][1], VS_RUN))
        else:
            out.append((s, m.end(), ord(m.group(0))))
    return out


def unicode_label(cp):
    if cp == VS_RUN:
        return ("VS-RUN variation selectors in a run of two or more (U+FE00-U+FE0F, "
                "U+E0100-U+E01EF), a hidden-payload pattern")
    try:
        name = unicodedata.name(chr(cp))
    except ValueError:
        name = "PRIVATE USE CHARACTER" if 0xE000 <= cp <= 0xF8FF else "UNNAMED CHARACTER"
    return "U+%04X %s" % (cp, name)


def hidden_counts(text, initial_bom_ok=False):
    """{code point: count}. A byte-order mark at the very start of a plain-text
    file is a valid encoding signature and is not counted."""
    out = {}
    for start, _, cp in hidden_hits(text):
        if initial_bom_ok and start == 0 and cp == 0xFEFF:
            continue
        out[cp] = out.get(cp, 0) + 1
    return out


def visible_snippet(text, start, end, width=30):
    """Context for a location report, with hidden characters made visible."""
    lo, hi = max(0, start - width), min(len(text), end + width)
    s = text[lo:hi].replace("\r", " ").replace("\n", " ")
    return HIDDEN_RX.sub(lambda m: "<U+%04X>" % ord(m.group(0)), s)


def citation_hits(text):
    """Every citation token in text, as (start, end, token, label, confirmed).

    confirmed is False for a residue whose purpose is ambiguous: a suspect
    pattern, or a confirmed token standing between quotation marks."""
    taken, hits = [], []

    def free(s, e):
        return all(e <= a or s >= b for a, b in taken)

    for label, rx in CITATION_CONFIRMED:
        for m in rx.finditer(text):
            s, e = m.span()
            if s == e or not free(s, e):
                continue
            quoted = (s > 0 and e < len(text) and text[s - 1] in QUOTE_CHARS
                      and text[e] in QUOTE_CHARS)
            taken.append((s, e))
            hits.append((s, e, m.group(0), label + (", quoted, so possibly the subject of "
                                                    "the text" if quoted else ""), not quoted))
    for label, rx in CITATION_SUSPECT:
        for m in rx.finditer(text):
            s, e = m.span()
            if not free(s, e):
                continue
            taken.append((s, e))
            hits.append((s, e, m.group(0), label, False))
    return sorted(hits)


def strip_chatgpt_utm(url):
    """Remove every utm_source=chatgpt.com pair from a URL's query.

    The destination, every other parameter in its original order and spelling,
    and the fragment are kept. A query left empty loses its question mark, so
    the result is still a valid URL. Returns (new url, pairs removed)."""
    base, hashmark, fragment = url.partition("#")
    path, qmark, query = base.partition("?")
    if not qmark:
        return url, 0
    keep, removed = [], 0
    for pair in query.split("&"):
        name, eq, value = pair.partition("=")
        if eq and name.lower() == "utm_source" and value.lower() in UTM_VALUES:
            removed += 1
            continue
        keep.append(pair)
    if not removed:
        return url, 0
    new = path + ("?" + "&".join(keep) if keep else "") + hashmark + fragment
    return new, removed


# Block-level text units, so a token split across runs is still seen.
TRACE_BLOCKS = {"p": "paragraph", "si": "shared string", "is": "inline string"}
# Markup whose text is not edited automatically: a formula, and a tracked
# change, which may be project evidence and is decided by the document owner.
REVISION_TAGS = ("ins", "del", "moveFrom", "moveTo")


def text_units(raw):
    """[(location, text, protected)] for one XML part, or None where it will
    not parse. protected is "formula", "tracked change" or None."""
    root = parse(raw)
    if root is None:
        return None
    units, counters = [], {}

    def gather(node, out, label):
        """Block text with tracked-change subtrees split off as their own units."""
        if not isinstance(node.tag, str):
            return
        if local_name(node.tag) in REVISION_TAGS:
            units.append((label + ", tracked change", "".join(node.itertext()),
                          "tracked change"))
            return
        if node.text:
            out.append(node.text)
        for child in node:
            gather(child, out, label)
            if child.tail:
                out.append(child.tail)

    def walk(node, protected):
        if not isinstance(node.tag, str):
            return
        name = local_name(node.tag)
        for attr, value in node.attrib.items():
            if value and value.strip():
                units.append(("%s@%s" % (name, local_name(attr)), value, protected))
        if name in TRACE_BLOCKS:
            counters[name] = counters.get(name, 0) + 1
            label = "%s %d" % (TRACE_BLOCKS[name], counters[name])
            out = []
            gather(node, out, label)
            units.append((label, "".join(out), protected))
            for sub in node.iter():
                if sub is not node and isinstance(sub.tag, str):
                    for attr, value in sub.attrib.items():
                        if value and value.strip():
                            units.append(("%s %s@%s" % (label, local_name(sub.tag),
                                                       local_name(attr)), value, protected))
            return
        if name in REVISION_TAGS:
            protected = "tracked change"
        elif name == "f":
            protected = "formula"
        if node.text and node.text.strip():
            units.append((name, node.text, protected))
        for child in node:
            walk(child, protected)
            if child.tail and child.tail.strip():
                units.append((name, child.tail, protected))

    walk(root, None)
    return units


# Formatting scaffolding, not text a reader sees. A Symbol-font bullet in a
# numbering definition is a private-use character by design, so these parts
# are not read for traces.
TRACE_SKIP = re.compile(r"^(word/(styles|stylesWithEffects|numbering|settings|webSettings"
                        r"|fontTable)\.xml|xl/styles\.xml|(word|xl|ppt)/theme/"
                        r"|ppt/(slideLayouts|slideMasters|notesMasters|handoutMasters)/)", re.I)


def trace_text_parts(parts):
    """The XML parts whose text the trace detection reads."""
    return [n for n in sorted(parts)
            if n.lower().endswith(".xml") and n != "[Content_Types].xml"
            and not WEBEXT_DIR.match(n) and not TRACE_SKIP.match(n)]


def package_hidden(parts):
    """{code point: [(part, location, snippet), ...]} over the trace parts."""
    out = {}
    for name in trace_text_parts(parts):
        units = text_units(parts[name]) or []
        for label, text, _ in units:
            for start, end, cp in hidden_hits(text):
                out.setdefault(cp, []).append(
                    (name, label, visible_snippet(text, start, end)))
    return out


def hidden_findings(now, base, accepted, matched, where_label=""):
    """Classify hidden characters. now and base map a code point to a count;
    base is None where no baseline is available. now_where maps a code point to
    a short location list. Returns findings in the classify() tuple form."""
    findings = []
    for cp in sorted(now):
        count, where = now[cp]
        cls = hidden_class(cp)
        before = None if base is None else base.get(cp, 0)
        introduced = 0 if before is None else max(0, count - before)
        what = "%s, %s, %d occurrence(s)%s%s" % (
            unicode_label(cp), cls, count,
            "" if before is None else ", %d in the baseline" % before,
            (", at " + where) if where else "")
        key = ("unicode", hidden_id(cp), "present")
        if cls == HIDDEN_CONTROL:
            if introduced:
                findings.append(("artifact", where_label or "document",
                                 "%s; %d introduced since the baseline, a processing defect. "
                                 "Remove the introduced character(s) in the edit and re-run; "
                                 "nothing is removed automatically" % (what, introduced)))
            elif key in accepted:
                matched.add(key)
                findings.append(("info", where_label or "document",
                                 "%s; %s" % (what, accept_note(accepted, key))))
            else:
                findings.append(("review", where_label or "document",
                                 "%s; %s. Not removed automatically. Remove it in the edit "
                                 "where it is not source-controlled, or record a decision with "
                                 "--accept 'unicode|%s|present|REVIEWER|REASON'"
                                 % (what, "pre-existing in the baseline" if before is not None
                                    else "no baseline was supplied, so whether it is "
                                         "pre-existing cannot be established", hidden_id(cp))))
        else:
            findings.append(("info", where_label or "document",
                             "%s; %s%s, preserved and not a failure" % (
                                 what, "needed for joining or direction in Arabic and other "
                                       "scripts" if cls == HIDDEN_LANGUAGE
                                 else "may be legitimate",
                                 ", %d introduced since the baseline" % introduced
                                 if introduced else "")))
    return findings


def trace_findings(parts, accepted=None, matched=None, base_parts=None):
    """Citation tokens, the ChatGPT tracking parameter, hidden Unicode and
    generator-library template data in an Office package.

    Returns findings in the classify() tuple form. base_parts is the pre-edit
    baseline package where one is available; it decides whether a hidden
    character is pre-existing or was introduced during processing."""
    accepted = accepted or {}
    if matched is None:
        matched = set()
    findings = []

    for name in trace_text_parts(parts):
        units = text_units(parts[name])
        if units is None:
            continue                      # an unparseable part fails elsewhere
        seen = set()
        for label, text, protected in units:
            for s, e, token, what, confirmed in citation_hits(text):
                if (label, token) in seen:
                    continue
                seen.add((label, token))
                key = (name, "citation", token)
                shown = visible_snippet(token, 0, len(token), 0)
                if confirmed and not protected:
                    findings.append(("artifact", name,
                                     "%s %s in %s, a generation-only token. Remove it in the "
                                     "edit (AI Fix rule 10, scripts/clean_artifacts.py in AI "
                                     "Fix)" % (what, shown, label)))
                elif key in accepted:
                    matched.add(key)
                    findings.append(("info", name, "%s %s in %s, %s"
                                     % (what, shown, label, accept_note(accepted, key))))
                else:
                    findings.append(("review", name,
                                     "%s %s in %s%s; purpose ambiguous, not removed. Decide, "
                                     "then remove it in the edit or record --accept "
                                     "'%s|citation|TOKEN|REVIEWER|REASON'"
                                     % (what, shown, label,
                                        ", inside a %s" % protected if protected else "",
                                        name)))
            for m in UTM_CHATGPT.finditer(text):
                if (label, "utm") in seen:
                    continue
                seen.add((label, "utm"))
                if protected:
                    findings.append(("review", name,
                                     "%s in %s, inside a %s, which is not "
                                     "edited automatically" % (m.group(0).lower(), label,
                                                               protected)))
                else:
                    findings.append(("artifact", name,
                                     "%s in %s, a ChatGPT tracking "
                                     "parameter. Remove it in the edit (scripts/"
                                     "clean_artifacts.py in AI Fix)" % (m.group(0).lower(),
                                                                        label)))

    for name in sorted(parts):
        if not name.lower().endswith(".rels"):
            continue
        root = parse(parts[name])
        if root is None:
            continue
        for r in relationships(root):
            target = r.get("Target") or ""
            if rel_is_external(r) and UTM_CHATGPT.search(target):
                findings.append(("artifact", name,
                                 "hyperlink target %s carries %s, a ChatGPT "
                                 "tracking parameter. Remove it in the edit (scripts/"
                                 "clean_artifacts.py in AI Fix)" % (target, utm_found(target))))

    now = package_hidden(parts)
    base = None
    if base_parts is not None:
        base = {cp: len(v) for cp, v in package_hidden(base_parts).items()}
    summary = {}
    for cp, hits in now.items():
        where = "; ".join("%s %s [%s]" % (p, l, s) for p, l, s in hits[:3])
        if len(hits) > 3:
            where += "; and %d more" % (len(hits) - 3)
        summary[cp] = (len(hits), where)
    findings += hidden_findings(summary, base, accepted, matched)

    core = parse(parts.get("docProps/core.xml", b"")) if "docProps/core.xml" in parts else None
    if core is not None:
        values = {}
        for node in core.iter():
            if isinstance(node.tag, str) and not list(node):
                values.setdefault(local_name(node.tag), (node.text or "").strip())
        for tag in AUTHOR_TAGS:
            v = values.get(tag, "")
            if v.lower() in LIBRARY_DEFAULT_VALUES:
                findings.append(("info", "docProps/core.xml",
                                 "%s = %s, %s. Reported only: not a replacement target and not "
                                 "evidence of AI authorship" % (tag, v,
                                                                LIBRARY_DEFAULT_VALUES[v.lower()])))
        for lib, created, modified in TEMPLATE_DATES:
            hit = [f for f, d in (("created", created), ("modified", modified))
                   if values.get(f) == d]
            if hit:
                rev = values.get("revision")
                findings.append(("info", "docProps/core.xml",
                                 "%s matches the %s template date%s%s. An indicator of "
                                 "programmatic generation, reported only, not evidence that AI "
                                 "wrote the content" % (
                                     " and ".join("%s %s" % (f, values.get(f)) for f in hit),
                                     lib, "s" if len(hit) > 1 else "",
                                     ", revision %s" % rev if rev else "")))
    return findings


def text_trace_findings(text, accepted=None, matched=None, base_text=None):
    """The same detection for a plain-text file, which has no package."""
    accepted = accepted or {}
    if matched is None:
        matched = set()
    findings = []
    lines = text.split("\n")
    for i, line in enumerate(lines, 1):
        for s, e, token, what, confirmed in citation_hits(line):
            key = ("text", "citation", token)
            if confirmed:
                findings.append(("artifact", "line %d" % i,
                                 "%s %s, a generation-only token. Remove it in the edit"
                                 % (what, visible_snippet(token, 0, len(token), 0))))
            elif key in accepted:
                matched.add(key)
                findings.append(("info", "line %d" % i, "%s %s, %s"
                                 % (what, token, accept_note(accepted, key))))
            else:
                findings.append(("review", "line %d" % i,
                                 "%s %s; purpose ambiguous, not removed. Decide, then remove "
                                 "it in the edit or record --accept "
                                 "'text|citation|TOKEN|REVIEWER|REASON'"
                                 % (what, visible_snippet(token, 0, len(token), 0))))
        if UTM_CHATGPT.search(line):
            findings.append(("artifact", "line %d" % i,
                             "%s, a ChatGPT tracking parameter. Remove it "
                             "in the edit" % utm_found(line)))
    now = {}
    for i, line in enumerate(lines, 1):
        for start, end, cp in hidden_hits(line):
            if i == 1 and start == 0 and cp == 0xFEFF:
                continue                  # a valid initial byte-order mark
            now.setdefault(cp, []).append(
                "line %d [%s]" % (i, visible_snippet(line, start, end)))
    base = None
    if base_text is not None:
        base = hidden_counts(base_text, initial_bom_ok=True)
    summary = {cp: (len(v), "; ".join(v[:3]) + ("; and %d more" % (len(v) - 3)
                                                 if len(v) > 3 else ""))
               for cp, v in now.items()}
    findings += hidden_findings(summary, base, accepted, matched, "text")
    return findings


# Outcomes, applied the same way in scan, clean, recertification and the
# certification record.
OUTCOME_PASS = "PASS"
OUTCOME_INFO = "PASS WITH INFORMATIONAL FINDINGS"
OUTCOME_REVIEW = "REVIEW REQUIRED"
OUTCOME_FAIL = "FAIL"
REVIEW_KINDS = ("review", "report-marker")
INFO_KINDS = ("info", "content")


def outcome(findings, failed=False, review=False):
    """FAIL where a confirmed defect remains or a required check failed;
    REVIEW REQUIRED where only ambiguous findings stand in the way; PASS WITH
    INFORMATIONAL FINDINGS where disclosed informational traces remain; PASS
    otherwise."""
    kinds = {f[0] for f in findings}
    if failed or kinds & (set(FAILING) - set(REVIEW_KINDS)):
        return OUTCOME_FAIL
    if review or kinds & set(REVIEW_KINDS):
        return OUTCOME_REVIEW
    if kinds & set(INFO_KINDS):
        return OUTCOME_INFO
    return OUTCOME_PASS


def is_pass(label):
    return label in (OUTCOME_PASS, OUTCOME_INFO)


def mentions_generator(lines):
    """True where any reported line names a generator library or its default
    data, so the log can carry the classification note."""
    keys = list(GENERATOR_PATTERNS) + list(LIBRARY_DEFAULT_VALUES) + ["template date"]
    return any(k in (line or "").lower() for line in lines for k in keys)


# ---------------------------------------------------------------- XML helpers

RESERVED_PREFIX = re.compile(r"^(ns\d+|xml|xmlns)$", re.I)


def register_prefixes(raw):
    """Best effort only. Keeping the file's own prefixes is cosmetic.

    Correctness rests on namespace URIs and local names, never on the textual
    prefix, so this must not be able to stop a file being processed. A prefix
    Python reserves for its own use, such as ns0, is skipped rather than
    registered, and any failure here is swallowed.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    try:
        for m in re.finditer(r"""xmlns:([A-Za-z0-9_.-]+)\s*=\s*["']([^"']+)["']""", raw):
            if RESERVED_PREFIX.match(m.group(1)):
                continue
            try:
                ET.register_namespace(m.group(1), m.group(2))
            except ValueError:
                pass
        for m in re.finditer(r"""xmlns\s*=\s*["']([^"']+)["']""", raw):
            try:
                ET.register_namespace("", m.group(1))
            except ValueError:
                pass
    except Exception:
        pass


NSDECL = {}          # root element -> {prefix: uri} required by the markup
NSCONFLICT = {}      # root element -> prefixes bound to more than one uri

# A prefix can be referenced by value rather than by use, in which case the
# serializer has no reason to keep its declaration.
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
NS_REFERENCING_ATTRS = ("Ignorable", "MustUnderstand")


class NamespacePreservationError(ValueError):
    """A part cannot be serialized without changing a namespace reference."""


def decode_xml(raw):
    """Decode XML bytes by their own declaration, not by assuming UTF-8."""
    if not isinstance(raw, bytes):
        return raw
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    head = raw[:200].decode("latin-1", "replace")
    m = re.search(r"""encoding\s*=\s*["']([^"']+)["']""", head)
    if m:
        try:
            return raw.decode(m.group(1), "replace")
        except LookupError:
            pass
    return raw.decode("utf-8", "replace")


def declared_prefixes(raw):
    """Prefix declarations found anywhere in the part.

    Presence here is not proof that a prefix is in scope where it is used; the
    scope-aware scan below is what decides that.
    """
    out = {}
    for m in re.finditer(r"""xmlns:([A-Za-z0-9_.-]+)\s*=\s*["']([^"']+)["']""",
                         decode_xml(raw)):
        out[m.group(1)] = m.group(2)
    return out


def ns_scan(raw):
    """Walk the part with namespace scope, and resolve every prefix it names.

    Returns (required, conflicts, unresolved). required maps a prefix named by
    mc:Ignorable, mc:Choice/@Requires or a similar attribute to the URI that
    was in scope at the element naming it. conflicts holds prefixes bound to
    more than one URI across the part. unresolved holds prefixes named where
    no binding was in scope, which is a markup error.
    """
    required, conflicts, unresolved = {}, set(), set()
    try:
        parser = ET.XMLPullParser(events=("start-ns", "end-ns", "start"))
        parser.feed(raw)
        parser.close()
    except Exception:
        return required, conflicts, unresolved
    scope = []
    try:
        events = list(parser.read_events())
    except Exception:
        return required, conflicts, unresolved
    for event, payload in events:
        if event == "start-ns":
            scope.append(payload)
        elif event == "end-ns":
            if scope:
                scope.pop()
        else:
            named = set()
            for attr, value in payload.attrib.items():
                if attr in {"{%s}%s" % (MC_NS, a) for a in NS_REFERENCING_ATTRS}:
                    named |= {x for x in (value or "").split() if x}
                elif attr == "Requires" and payload.tag == "{%s}Choice" % MC_NS:
                    named |= {x for x in (value or "").split() if x}
                elif attr == "{%s}ProcessContent" % MC_NS:
                    # ProcessContent holds QNames. An unprefixed QName uses
                    # the default namespace, or no namespace if none is bound.
                    for qname in (value or "").split():
                        if qname.count(":") > 1 or qname.startswith(":") or qname.endswith(":"):
                            unresolved.add(qname)
                        else:
                            named.add(qname.split(":", 1)[0] if ":" in qname else "")
            if not named:
                continue
            in_scope = {"": "", "xml": "http://www.w3.org/XML/1998/namespace"}
            for pfx, uri in scope:
                in_scope[pfx] = uri
            for pfx in named:
                if pfx not in in_scope:
                    unresolved.add(pfx)
                    continue
                if pfx in required and required[pfx] != in_scope[pfx]:
                    conflicts.add(pfx)
                required[pfx] = in_scope[pfx]
    return required, conflicts, unresolved


def namespace_defects(parts, original_parts=None):
    """Check references before any package write, including their original URIs.

    ElementTree cannot retain scoped rebinding of a prefix named by value.
    Reject that supported-format limitation explicitly rather than flatten it.
    """
    problems = []
    for name, raw in sorted(parts.items()):
        if not name.lower().endswith((".xml", ".rels")):
            continue
        required, conflicts, unresolved = ns_scan(raw)
        if conflicts:
            problems.append("%s: cannot preserve scoped namespace binding(s): %s"
                            % (name, ", ".join(p or "(default)" for p in sorted(conflicts))))
        if unresolved:
            problems.append("%s: unresolved namespace reference(s): %s"
                            % (name, ", ".join(sorted(unresolved))))
        if original_parts is not None and name in original_parts:
            original, old_conflicts, _ = ns_scan(original_parts[name])
            if old_conflicts:
                problems.append("%s: original scoped namespace bindings cannot be flattened"
                                % name)
            for prefix, uri in required.items():
                if prefix in original and original[prefix] != uri:
                    problems.append("%s: namespace reference %s changed URI from %r to %r"
                                    % (name, prefix or "(default)", original[prefix], uri))
    return problems


def parse(raw):
    """Parse from the original bytes where possible.

    An OOXML part may legitimately be UTF-16 or another XML-supported
    encoding, and only the raw bytes carry the encoding declaration. Decoding
    to UTF-8 first would reject a valid part.
    """
    register_prefixes(raw)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        root = None
    if root is None and isinstance(raw, bytes):
        try:
            root = ET.fromstring(raw.decode("utf-8", "replace"))
        except ET.ParseError:
            root = None
    if root is not None:
        required, conflicts, _ = ns_scan(raw)
        NSDECL[root] = required
        NSCONFLICT[root] = conflicts
    return root


def xml_text(raw):
    """Normalized UTF-8 text of an XML part, for marker scanning.

    Falls back to a lenient decode where the part will not parse, so a
    malformed part is still scanned rather than skipped.
    """
    root = parse(raw)
    if root is None:
        return as_text(raw)
    return as_text(serialize(root))


def serialize(root):
    """Serialize, keeping the namespace bindings the markup still refers to.

    A prefix named in mc:Ignorable or in mc:Choice/@Requires is referenced by
    value, not by use, so the serializer has no reason to keep its declaration
    and would leave an undeclared prefix behind. Those bindings are put back at
    the root, where they are in scope for the whole part. Nothing is solved by
    deleting the compatibility attribute or the alternate content.
    """
    conflicts = NSCONFLICT.get(root, set())
    if conflicts:
        raise NamespacePreservationError("cannot preserve scoped namespace binding(s): %s"
                                         % ", ".join(p or "(default)" for p in sorted(conflicts)))
    out = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    required = NSDECL.get(root, {})
    if not required:
        return out
    text = out.decode("utf-8", "replace")
    # Read the serializer's root bindings with a parser, including the default
    # binding and escaped URI characters. Do not treat a wrong URI as present.
    parser = ET.XMLPullParser(events=("start-ns", "start"))
    parser.feed(out)
    parser.close()
    have = {"xml": "http://www.w3.org/XML/1998/namespace"}
    for event, payload in parser.read_events():
        if event == "start":
            break
        have[payload[0]] = payload[1]
    missing = {p: u for p, u in required.items() if p not in have and u}
    if missing:
        from xml.sax.saxutils import quoteattr
        m = re.search(r"<[A-Za-z_][^>]*?(/?)>", text)
        if not m:
            raise NamespacePreservationError("cannot locate the serialized root element")
        decls = "".join(" xmlns%s=%s" % ((":" + p) if p else "", quoteattr(u))
                        for p, u in sorted(missing.items()))
        tag = m.group(0)
        new_tag = tag[:-2] + decls + tag[-2:] if tag.endswith("/>") else tag[:-1] + decls + ">"
        out = (text[:m.start()] + new_tag + text[m.end():]).encode("utf-8")
    actual, conflicts, unresolved = ns_scan(out)
    changed = {p for p, uri in actual.items() if p in required and required[p] != uri}
    if conflicts or unresolved or changed or not trees_equal(root, ET.fromstring(out)):
        raise NamespacePreservationError("serialization would change namespace bindings: %s"
                                         % ", ".join(p or "(default)" for p in
                                                     sorted(conflicts | unresolved | changed)))
    return out


def find_local(root, name):
    return [e for e in root.iter() if local_name(e.tag) == name]


def remove_child(root, node):
    for parent in root.iter():
        if node in list(parent):
            parent.remove(node)
            return True
    return False


def relationships(root):
    return find_local(root, "Relationship") if root is not None else []


def rel_is_external(node):
    return (node.get("TargetMode") or "") == "External"


def internal_targets(rels_name, raw):
    root = parse(raw)
    out = []
    for r in relationships(root):
        if rel_is_external(r):
            continue
        t = r.get("Target")
        if t:
            out.append(resolve_target(rels_name, t))
    return out


# ---------------------------------------------------------------- classification

def classify_web_extensions(parts):
    unnecessary, preserved = [], []
    for n in sorted(parts):
        if not WEBEXT_PART.match(n):
            continue
        # A tool URL inside an extension definition is the integration itself,
        # and so is the Office Store id of a known writing-assistant add-in.
        if (has_marker(xml_text(parts[n]), strip_urls=False)
                or webext_store_hits(parts[n])):
            unnecessary.append(n)
        else:
            preserved.append(n)
    return unnecessary, preserved


def custom_property_verdict(node):
    """remove, report, or keep. Deletion needs integration metadata or a path."""
    name = (node.get("name") or "").strip()
    value = " ".join(t for t in node.itertext())
    if name.lower() in INTEGRATION_KEYS:
        return "remove", INTEGRATION_KEYS[name.lower()]
    if path_hits_in_field(name) or path_hits_in_field(value):
        return "remove", "local working path"
    # A Grammarly or QuillBot name alone is not proof of integration residue:
    # ClientName = QuillBot may name a business party. Such a property falls
    # through to the report below (Rev33, superseding the Rev31 removal rule).
    kw, _ = markers(name + " " + value)
    if kw:
        return "report", ("carries the tool name %s, which may be legitimate metadata, "
                          "so it is not removed automatically" % ", ".join(kw))
    return "keep", ""


def acceptable(kw, lp):
    """An acceptance resolves ambiguity only. A local path is never ambiguous."""
    return bool(kw) and not lp


def accept_note(accepted, key):
    entry = accepted.get(key) if isinstance(accepted, dict) else None
    if not entry:
        return "reviewed and accepted"
    return ("reviewed and accepted by %s, %s, recorded %s"
            % (entry.get("reviewer", "?"), entry.get("reason", "no reason given"),
               entry.get("recorded", "")))


def classify(parts, accepted=None, matched=None, base_parts=None):
    """The single classification routine. Used for inspection and for
    post-clean verification, so their coverage cannot drift apart.

    Returns a list of (kind, part, detail). Kinds:
      remove        removed automatically by --clean
      keep          examined and deliberately preserved
      report        present, reported, never removed automatically
      report-marker a report-only part carrying a tool name or a path
      metadata      a marker in a document-property part
      author        an author or company value, recorded, not a failure
      author-marker an author or company value carrying a tool name or a path,
                    changed only under --author or --blank-author
      package       a marker anywhere else outside document content
      content       a marker inside visible document content

    accepted maps (part, field, exact value) to the reviewer and reason
    recorded for it. An acceptance resolves an ambiguous finding only: a tool
    name in a descriptive or author field, or in a custom property. It can
    never clear a local working path, a known integration key, an add-in, a
    structural defect, a signature or an indeterminate reading. Nothing is
    ever deleted on the strength of an acceptance.
    """
    accepted = accepted or {}
    findings = []
    unnecessary, preserved = classify_web_extensions(parts)

    for n in unnecessary:
        kw, lp = markers(xml_text(parts[n]), strip_urls=False)
        store = webext_store_hits(parts[n])
        what = [describe(kw, lp)] if (kw or lp) else []
        what += ["writing-assistant add-in " + x for x in store]
        findings.append(("remove", n, "Office web extension carrying " + "; ".join(what)))
    for n in preserved:
        findings.append(("keep", n, "Office web extension, no marker, preserved"))

    for name in sorted(parts):
        if WEBEXT_DIR.match(name):
            continue
        is_xml = name.lower().endswith((".xml", ".rels"))
        text = xml_text(parts[name]) if is_xml else ""

        report_only = False
        for rx, label in REPORT_ONLY_PARTS:
            if rx.search(name):
                is_comment = "comment" in label or "person list" in label
                kw, lp = markers(text) if text else ([], [])
                if kw or lp:
                    if is_comment:
                        # Comments are decided one by one in the comment pass,
                        # so the part itself is listed rather than failed here.
                        findings.append(("report", name,
                                         "%s carrying %s, see the comment decisions"
                                         % (label, describe(kw, lp))))
                    else:
                        findings.append(("report-marker", name,
                                         "%s carrying %s, removal is not automatic"
                                         % (label, describe(kw, lp))))
                else:
                    findings.append(("report", name, label + ", removal not automatic"))
                report_only = True
                break
        if report_only:
            continue

        if name == "docProps/custom.xml":
            root = parse(text)
            if root is None:
                findings.append(("metadata", name, "will not parse as XML"))
                continue
            for node in find_local(root, "property"):
                verdict, why = custom_property_verdict(node)
                label = node.get("name") or "(unnamed)"
                if verdict == "remove":
                    findings.append(("remove", name, "custom property %s, %s" % (label, why)))
                elif verdict == "report":
                    value = " ".join(t for t in node.itertext()).strip()
                    kw, lp = markers(label + " " + value)
                    key = (name, label, value)
                    if acceptable(kw, lp) and key in accepted:
                        if matched is not None:
                            matched.add(key)
                        findings.append(("keep", name, "custom property %s = %s, %s"
                                         % (label, value, accept_note(accepted, key))))
                    else:
                        findings.append(("report-marker", name,
                                         "custom property %s %s" % (label, why)))
            continue

        if name in ("docProps/core.xml", "docProps/app.xml"):
            root = parse(parts[name])
            if root is None:
                findings.append(("metadata", name, "will not parse as XML"))
                continue
            for node in root.iter():
                if list(node) or node is root:
                    continue          # leaf values only
                tag = local_name(node.tag)
                value = (node.text or "").strip()
                if not value:
                    continue

                if tag == "HyperlinkBase":
                    lp = path_hits_in_field(value)
                    if lp:
                        findings.append(("remove", name,
                                         "HyperlinkBase local working path " + "; ".join(lp)))
                    continue

                kw, lp = markers(value)
                if not kw and not lp:
                    if tag in AUTHOR_TAGS + COMPANY_TAGS:
                        findings.append(("author", name, "%s = %s" % (tag, value)))
                    continue

                key = (name, tag, value)
                if acceptable(kw, lp) and key in accepted:
                    if matched is not None:
                        matched.add(key)
                    findings.append(("keep", name, "%s = %s, %s"
                                     % (tag, value, accept_note(accepted, key))))
                    continue

                if lp:
                    # A local working path in any metadata field is definite.
                    findings.append(("metadata", name,
                                     "%s = %s, carries %s" % (tag, value, describe(kw, lp))))
                elif tag in PROVENANCE_FIELDS:
                    findings.append(("author-marker", name,
                                     "%s = %s, a provenance field carrying %s, changed only "
                                     "under --author or --blank-author"
                                     % (tag, value, describe(kw, lp))))
                else:
                    where = "a descriptive field" if tag in DESCRIPTIVE_FIELDS else "a field"
                    findings.append(("report-marker", name,
                                     "%s = %s, %s carrying %s, which may be the subject rather "
                                     "than provenance, so it is reported and not removed"
                                     % (tag, value, where, describe(kw, lp))))
            continue

        if is_xml:
            root = parse(parts[name])
            for node in (find_local(root, "absPath") if root is not None else []):
                findings.append(("remove", name, "absolute working path record absPath = %s"
                                 % (node.get("url") or "")))

        if not text:
            continue

        if name.lower().endswith(".rels"):
            root = parse(text)
            if root is None:
                findings.append(("package", name, "will not parse as XML"))
                continue
            for r in relationships(root):
                t = r.get("Target") or ""
                if rel_is_external(r) and URL.match(t.strip()):
                    continue          # an ordinary link is functional content
                kw, lp = markers(t)
                if kw or lp:
                    findings.append(("package", name,
                                     "relationship target carrying " + describe(kw, lp)))
            continue

        kw, lp = markers(text)
        if kw or lp:
            body = text
            if "absPath" in text:
                root = parse(text)
                if root is not None:
                    remove_abspath_tree(root)
                    body = as_text(serialize(root))
            kw2, lp2 = markers(body)
            if kw2 or lp2:
                findings.append(("content" if is_content_part(name) else "package",
                                 name, describe(kw2, lp2)))

    # Rev37 / Rev 3.20: citation tokens, the ChatGPT tracking parameter,
    # hidden Unicode and generator-library template data.
    findings += trace_findings(parts, accepted, matched, base_parts)
    return findings


def failing_items(findings):
    return [(k, n, d) for k, n, d in findings if k in FAILING]


# ---------------------------------------------------------------- cleaning

# ---------------------------------------------------------------- annotations

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
XLSX_COMMENT_PART = re.compile(r"^(xl/comments\d*\.xml|xl/comments/[^/]+\.xml)$", re.I)
XLSX_THREAD_PART = re.compile(r"^xl/threadedcomments/[^/]+\.xml$", re.I)
DOCX_COMMENT_PART = re.compile(r"^word/comments\.xml$", re.I)
DOCX_SUPPORT_PART = re.compile(r"^word/comments(Extended|Ids|Extensible)\.xml$", re.I)
PPTX_COMMENT_PART = re.compile(r"^ppt/.*comments?/.*\.xml$", re.I)


def col_row(ref):
    """A1 style reference to zero-based (column, row)."""
    m = re.match(r"([A-Za-z]+)(\d+)$", (ref or "").strip())
    if not m:
        return None
    col = 0
    for ch in m.group(1).upper():
        col = col * 26 + (ord(ch) - 64)
    return col - 1, int(m.group(2)) - 1


def node_text(node):
    return " ".join(t.strip() for t in node.itertext() if t.strip())


def para_ids(node):
    out = set()
    for e in node.iter():
        for a, v in e.attrib.items():
            if local_name(a) == "paraId" and v:
                out.add(v.lower())
    return out


def persons_in(parts):
    """personId to display name, across every person part."""
    people = {}
    for name in parts:
        if name.lower().startswith("xl/persons/"):
            root = parse(parts[name])
            for p in (find_local(root, "person") if root is not None else []):
                people[(p.get("id") or "").lower()] = p.get("displayName") or ""
    return people


def collect_comments(parts):
    """Every annotation in the package, with the part it lives in.

    The part is part of the identity. Two cells named A1 on different
    worksheets live in different comment parts, so a new annotation can never
    be mistaken for an existing one on another sheet.
    """
    found = []
    people = persons_in(parts)

    for name in sorted(parts):
        if XLSX_COMMENT_PART.match(name):
            root = parse(parts[name])
            if root is None:
                continue
            authors = [(a.text or "").strip() for a in find_local(root, "author")]
            for node in find_local(root, "comment"):
                try:
                    author = authors[int(node.get("authorId") or 0)]
                except (ValueError, IndexError):
                    author = ""
                found.append({"kind": "xlsx", "part": name, "node": node, "root": root,
                              "ref": node.get("ref") or "", "author": author,
                              "text": node_text(node), "id": "", "parent": "", "person": ""})

        elif XLSX_THREAD_PART.match(name):
            root = parse(parts[name])
            if root is None:
                continue
            for node in find_local(root, "threadedComment"):
                pid = (node.get("personId") or "").lower()
                found.append({"kind": "xlsx-threaded", "part": name, "node": node, "root": root,
                              "ref": node.get("ref") or "",
                              "id": (node.get("id") or "").lower(),
                              "parent": (node.get("parentId") or "").lower(),
                              "person": pid, "author": people.get(pid, ""),
                              "text": node_text(node)})

        elif DOCX_COMMENT_PART.match(name):
            root = parse(parts[name])
            if root is None:
                continue
            for node in find_local(root, "comment"):
                found.append({"kind": "docx", "part": name, "node": node, "root": root,
                              "ref": "", "parent": "", "person": "",
                              "id": str(node.get("{%s}id" % W_NS) or node.get("id") or ""),
                              "author": node.get("{%s}author" % W_NS) or node.get("author") or "",
                              "text": node_text(node)})

        elif PPTX_COMMENT_PART.match(name):
            root = parse(parts[name])
            if root is None:
                continue
            for node in find_local(root, "cm") + find_local(root, "cmt"):
                found.append({"kind": "pptx", "part": name, "node": node, "root": root,
                              "ref": node.get("idx") or "", "id": node.get("idx") or "",
                              "parent": "", "person": "",
                              "author": node.get("authorId") or "", "text": node_text(node)})

    return [attach_support(parts, c) for c in found]


def canon_node(node):
    """Canonical form of an XML node.

    Serialization details are normalized: a namespace prefix is an alias, so
    the namespace URI is kept and the prefix is not, and attributes are sorted
    by their qualified name. Content is never normalized: text and tail are
    compared exactly, so a double space that becomes a single space is a
    change, not a match.
    """
    attrs = sorted(node.attrib.items())
    kids = "".join(canon_node(k) for k in list(node))
    return "<%s %s>%r%s</%s>%r" % (node.tag,
                                   " ".join("%s=%r" % a for a in attrs),
                                   node.text or "", kids, node.tag, node.tail or "")


def sheet_vml_for(parts, comment_part):
    """The VML drawing belonging to the same worksheet as this comment part."""
    for rels in [n for n in parts if re.match(r"^xl/worksheets/_rels/", n, re.I)]:
        targets = internal_targets(rels, parts[rels])
        if comment_part in targets:
            return [t for t in targets if t.lower().endswith(".vml")]
    return []


VML_CLOSE = re.compile(r"</[A-Za-z0-9_.-]*:?xml>\s*$")


def split_vml(raw):
    """Shape blocks and the container's closing tag, kept apart.

    The last shape block otherwise carries the closing tag with it, so a block
    stored from one drawing cannot be put back without duplicating or losing
    that tag.
    """
    m = VML_CLOSE.search(raw)
    close = m.group(0) if m else ""
    body = raw[:m.start()] if m else raw
    return re.split(r"(?=<[A-Za-z0-9_.-]*:?shape\b)", body), close


def vml_shapes(raw):
    """Shape blocks only. The container's closing tag is not part of a block."""
    return split_vml(raw)[0]


def shape_cell(block):
    m_r = re.search(r"<[A-Za-z0-9_.-]*:?Row>(\d+)</", block)
    m_c = re.search(r"<[A-Za-z0-9_.-]*:?Column>(\d+)</", block)
    if m_r and m_c:
        return int(m_c.group(1)), int(m_r.group(1))
    return None


def vml_shape_for(parts, comment_part, ref):
    """The note shape that belongs to one cell comment."""
    cell = col_row(ref)
    if cell is None:
        return None
    for vml in sheet_vml_for(parts, comment_part):
        if vml not in parts:
            continue
        for block in vml_shapes(as_text(parts[vml])):
            if shape_cell(block) == cell:
                return (vml, block)
    return None


def sheet_for(parts, comment_part):
    """The worksheet that owns this comment part."""
    for rels in [n for n in parts if re.match(r"^xl/worksheets/_rels/", n, re.I)]:
        if comment_part in internal_targets(rels, parts[rels]):
            sheet = "xl/worksheets/" + os.path.basename(rels)[:-len(".rels")]
            return sheet if sheet in parts else None
    return None


def legacy_drawing_for(parts, comment_part):
    """The worksheet's legacyDrawing element, and the element that follows it.

    Worksheet children are ordered by the schema, and extLst legitimately comes
    after legacyDrawing, so the element that follows is recorded and the
    reference is put back in front of it rather than at the end.
    """
    sheet = sheet_for(parts, comment_part)
    if sheet is None:
        return None
    root = parse(parts[sheet])
    if root is None:
        return None
    kids = list(root)
    for i, node in enumerate(kids):
        if local_name(node.tag) == "legacyDrawing":
            follower = local_name(kids[i + 1].tag) if i + 1 < len(kids) else ""
            return (sheet, node, follower)
    return None


def person_node_for(parts, person_id):
    for name in parts:
        if name.lower().startswith("xl/persons/"):
            root = parse(parts[name])
            for p in (find_local(root, "person") if root is not None else []):
                if (p.get("id") or "").lower() == (person_id or "").lower():
                    return (name, p)
    return None


def attr_local(node, name):
    for a, v in node.attrib.items():
        if local_name(a) == name:
            return v
    return None


def docx_support_records(parts, paraids):
    """The commentsExtended, commentsIds and commentsExtensible records of one comment."""
    out = []
    durable = set()
    for name in parts:
        if re.match(r"^word/commentsIds\.xml$", name, re.I):
            root = parse(parts[name])
            for node in (list(root) if root is not None else []):
                pid = (attr_local(node, "paraId") or "").lower()
                if pid in paraids:
                    out.append((name, node))
                    did = attr_local(node, "durableId")
                    if did:
                        durable.add(did.lower())
    for name in parts:
        if re.match(r"^word/commentsExtended\.xml$", name, re.I):
            root = parse(parts[name])
            for node in (list(root) if root is not None else []):
                if (attr_local(node, "paraId") or "").lower() in paraids:
                    out.append((name, node))
        if re.match(r"^word/commentsExtensible\.xml$", name, re.I):
            root = parse(parts[name])
            for node in (list(root) if root is not None else []):
                if (attr_local(node, "durableId") or "").lower() in durable:
                    out.append((name, node))
    return out


def docx_anchors(parts, comment_id):
    """The commentRangeStart, commentRangeEnd and commentReference of one comment.

    A comment with no reference in the body is not attached to anything and can
    be ignored when the document is loaded, so the anchors are part of what the
    baseline protects.
    """
    out = []
    for name in sorted(parts):
        if not re.match(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$",
                        name, re.I):
            continue
        root = parse(parts[name])
        for node in (root.iter() if root is not None else []):
            if local_name(node.tag) not in ("commentRangeStart", "commentRangeEnd",
                                            "commentReference"):
                continue
            nid = node.get("{%s}id" % W_NS) or node.get("id")
            if str(nid) == str(comment_id):
                out.append((name, node))
    return out


def anchor_context(parts, comment_id):
    """Protect the paragraph and the exact content offset of every anchor.

    Adjacent text runs contribute consecutive characters, without synthetic
    spaces. Functional run content contributes a token, so moving an anchor
    across a tab, break or drawing is also detected. Prefix changes and text
    run splits leave this context unchanged.
    """
    out = []
    for name in sorted(parts):
        if not re.match(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$",
                        name, re.I):
            continue
        root = parse(parts[name])
        if root is None:
            continue
        paras = [e for e in root.iter() if local_name(e.tag) == "p"]
        for i, para in enumerate(paras):
            stream, anchors = [], []

            def walk(node):
                kind = local_name(node.tag)
                if node is not para and kind == "p":
                    return  # A nested paragraph is inventoried separately.
                if kind in ("pPr", "rPr"):
                    return
                if kind in ("commentRangeStart", "commentRangeEnd", "commentReference"):
                    nid = node.get("{%s}id" % W_NS) or node.get("id")
                    if str(nid) == str(comment_id):
                        anchors.append((kind, len(stream)))
                    return
                if kind in ("t", "delText", "instrText", "delInstrText"):
                    stream.extend((kind, ch) for ch in (node.text or ""))
                    return
                if kind in ("tab", "br", "cr", "drawing", "pict", "object", "sym",
                            "fldChar", "footnoteReference", "endnoteReference",
                            "noBreakHyphen", "softHyphen"):
                    stream.append((kind, canon_node(node)))
                    return
                for child in node:
                    walk(child)

            walk(para)
            for kind, offset in anchors:
                out.append((name, kind, i, tuple(stream), offset))
    return tuple(sorted(out))


def comments_relationship(parts, comment_part):
    """The relationship that attaches the comments part to the document."""
    for rels in [n for n in parts if n.endswith(".rels")]:
        root = parse(parts[rels])
        for r in (relationships(root) if root is not None else []):
            t = r.get("Target")
            if t and resolve_target(rels, t) == comment_part:
                return (rels, r)
    return None


def attach_support(parts, c):
    """Record the infrastructure this annotation owns, for comparison and restoration.

    An annotation is not only its own node. A cell comment owns its note shape,
    a threaded comment owns the person record it names, and a Word comment owns
    its commentsExtended, commentsIds and commentsExtensible records. A change
    in any of them is a change to the annotation.
    """
    support = []
    if c["kind"] == "xlsx":
        hit = vml_shape_for(parts, c["part"], c["ref"])
        if hit:
            support.append(("vml", hit[0], hit[1]))
        hit = legacy_drawing_for(parts, c["part"])
        if hit:
            support.append(("legacydrawing", hit[0], hit[1]))
            c["legacy_follower"] = hit[2]
    elif c["kind"] == "xlsx-threaded":
        hit = person_node_for(parts, c["person"])
        if hit:
            support.append(("person", hit[0], hit[1]))
    elif c["kind"] == "docx":
        for name, node in docx_support_records(parts, para_ids(c["node"])):
            support.append(("record", name, node))
        for name, node in docx_anchors(parts, str(c.get("id"))):
            support.append(("anchor", name, node))
        hit = comments_relationship(parts, c["part"])
        if hit:
            support.append(("rel", hit[0], hit[1]))
        c["anchor_context"] = anchor_context(parts, str(c.get("id")))
    c["support"] = support
    c["support_canon"] = tuple(sorted(
        (kind, name, item if kind == "vml" else canon_node(item))
        for kind, name, item in support))
    return c


def locator(c):
    """Where the annotation sits. Identity only, never content."""
    if c["kind"] == "xlsx":
        return (c["kind"], c["part"], c["ref"])
    return (c["kind"], c["part"], c["id"])


def canon_comment(c):
    """Canonical form of the annotation node itself.

    For a legacy cell comment the authorId is an index into the part's author
    list, not content: the author is compared by name instead, so reordering
    the author table is deliberately not an alteration and raises no false
    failure. Everything else is compared exactly.
    """
    node = c["node"]
    if c["kind"] == "xlsx" and "authorId" in node.attrib:
        node = copy.deepcopy(node)
        del node.attrib["authorId"]
    return canon_node(node)


def comment_key(c):
    """The whole protected state: position, author, own XML, and its support."""
    return locator(c) + (c["author"], canon_comment(c), c.get("support_canon", ()),
                         c.get("legacy_follower", ""), c.get("anchor_context", ()))


def match_key(c):
    """Locator only, used to find the annotation that must be restored."""
    return locator(c)


def package_defects(parts):
    """Structural requirements every OOXML package must meet."""
    problems = []
    if "[Content_Types].xml" not in parts:
        problems.append("[Content_Types].xml is missing")
    elif parse(parts["[Content_Types].xml"]) is None:
        problems.append("[Content_Types].xml will not parse")
    if "_rels/.rels" not in parts:
        problems.append("_rels/.rels is missing")
    else:
        root = parse(parts["_rels/.rels"])
        target = None
        for r in (relationships(root) if root is not None else []):
            if (r.get("Type") or "").endswith("/officeDocument"):
                target = resolve_target("_rels/.rels", r.get("Target") or "")
        if target is None:
            problems.append("the root officeDocument relationship is missing")
        elif target not in parts:
            problems.append("the root officeDocument relationship points at %s, which is not "
                            "in the package" % target)
        else:
            ct = parse(parts.get("[Content_Types].xml", b""))
            declared = {(n.get("PartName") or "").lstrip("/"): n.get("ContentType") or ""
                        for n in (find_local(ct, "Override") if ct is not None else [])}
            if target not in declared:
                problems.append("the main part %s has no content-type declaration" % target)
            elif "main+xml" not in declared[target]:
                problems.append("the main part %s is declared as %s, which is not a main "
                                "document type" % (target, declared[target]))
    return problems


def annotation_chain_defects(parts):
    """A relationship or a declaration that promises a part which is not there.

    A baseline whose comments part is gone but whose relationship and
    content-type declaration remain still looks like it has no comments. It
    must not be trusted to authorize deleting one.
    """
    problems = []
    for rels in [n for n in parts if n.endswith(".rels")]:
        root = parse(parts[rels])
        for r in (relationships(root) if root is not None else []):
            if (r.get("TargetMode") or "") == "External":
                continue
            t = r.get("Target")
            if not t:
                continue
            resolved = resolve_target(rels, t)
            if resolved not in parts:
                problems.append("%s points at %s, which is not in the package"
                                % (rels, resolved))
    ct = parse(parts.get("[Content_Types].xml", b""))
    for node in (find_local(ct, "Override") if ct is not None else []):
        part = (node.get("PartName") or "").lstrip("/")
        if part and part not in parts:
            problems.append("a content-type declaration names %s, which is not in the package"
                            % part)
    return problems


def baseline_inventory(path):
    """The pre-edit inventory: annotations and the infrastructure behind them.

    A baseline that is not a sound package, or whose annotation XML will not
    parse, is no inventory at all. None is returned, and with no inventory
    nothing is removed, pruned or restored.
    """
    try:
        bparts = read_parts(path)
    except Exception:
        return None
    defects = package_defects(bparts) + namespace_defects(bparts)
    if defects:
        print("the baseline is not a usable package (%s), so no inventory was built"
              % "; ".join(defects))
        return None
    for n, v in bparts.items():
        if (XLSX_COMMENT_PART.match(n) or XLSX_THREAD_PART.match(n)
                or DOCX_COMMENT_PART.match(n) or DOCX_SUPPORT_PART.match(n)
                or n.lower().startswith("xl/persons/")):
            if parse(v) is None:
                print("the baseline annotation part %s will not parse, so no inventory was "
                      "built" % n)
                return None
    chain = annotation_chain_defects(bparts)
    if chain:
        print("the baseline's annotation chain is broken (%s), so no inventory was built"
              % "; ".join(chain))
        return None
    comments = collect_comments(bparts)
    authors = {}
    for name in bparts:
        if XLSX_COMMENT_PART.match(name):
            root = parse(bparts[name])
            authors[name] = {(a.text or "").strip()
                             for a in (find_local(root, "author") if root is not None else [])}
    support_parts = {n: v for n, v in bparts.items()
                     if XLSX_COMMENT_PART.match(n) or XLSX_THREAD_PART.match(n)
                     or DOCX_COMMENT_PART.match(n) or DOCX_SUPPORT_PART.match(n)
                     or n.lower().startswith("xl/persons/") or n.lower().endswith(".vml")}
    rels_raw = {n: v for n, v in bparts.items() if n.endswith(".rels")}
    defaults = set()
    ct = parse(bparts.get("[Content_Types].xml", b""))
    if ct is not None:
        for node in find_local(ct, "Default"):
            if node.get("Extension"):
                defaults.add(node.get("Extension").lower())
    return {"keys": {comment_key(c) for c in comments},
            "index": {match_key(c): c for c in comments},
            "parts": set(bparts),
            "authors": authors,
            "defaults": defaults,
            "raw": support_parts,
            "rels_raw": rels_raw,
            "ct_raw": bparts.get("[Content_Types].xml", b""),
            "persons": set(persons_in(bparts))}


def replace_child(root, old, new):
    for parent in root.iter():
        kids = list(parent)
        if old in kids:
            parent.remove(old)
            parent.insert(kids.index(old), new)
            return True
    return False


def comment_verdict(c, inv):
    """Decide one annotation against the pre-edit inventory.

    An existing annotation is protected source content: not deleted, not
    rewritten, author unchanged. An annotation absent from the inventory was
    created during processing and is removed. One matching by position but
    differing in author or text was altered and is restored exactly.

    Without an inventory nothing is guessed at: everything is preserved and
    the condition is reported, because the run cannot then certify that no
    annotation was created.
    """
    if inv is None:
        return "keep-unverified", ("no pre-edit inventory supplied, so the annotation is "
                                   "preserved and this run cannot certify that it is "
                                   "pre-existing")
    if comment_key(c) in inv["keys"]:
        return "keep", "present in the pre-edit inventory, unchanged"
    original = inv["index"].get(match_key(c))
    if (original is not None and c["kind"] == "docx"
            and c.get("anchor_context", ()) != original.get("anchor_context", ())
            and canon_comment(c) == canon_comment(original)
            and c["author"] == original["author"]):
        return "relocated", ("the comment is unchanged but it is attached to different text "
                             "than in the pre-edit inventory. Where it belongs cannot be "
                             "inferred, so the file is left as it is and the comment is "
                             "resolved by hand")
    if original is not None and canon_comment(c) == canon_comment(original) \
            and c["author"] == original["author"]:
        return "restore", ("the annotation itself is unchanged but a record supporting it was "
                           "altered during processing, so the supporting record is restored")
    if c["kind"] == "pptx":
        return "report-manual", ("absent from the pre-edit inventory, but PowerPoint comment "
                                 "identity is not implemented, so it is preserved and must be "
                                 "removed by hand")
    original = inv["index"].get(match_key(c))
    if original is not None:
        return "restore", ("present in the pre-edit inventory but altered during processing, "
                           "restored exactly (author %s)" % (original.get("author") or "none"))
    return "remove", "not present in the pre-edit inventory, created during processing"


def prune_authors(parts, part, inv, actions, touched):
    """Drop author entries that processing introduced and nothing now uses.

    Every author entry that was in the baseline stays, used or not.
    """
    root = parse(parts[part])
    if root is None:
        return
    lists = find_local(root, "authors")
    nodes = find_local(root, "author")
    if not lists or not nodes:
        return
    names = [(a.text or "").strip() for a in nodes]
    used = set()
    for cnode in find_local(root, "comment"):
        try:
            used.add(int(cnode.get("authorId") or 0))
        except ValueError:
            pass
    baseline_authors = (inv or {}).get("authors", {}).get(part, set())
    keep_idx = [i for i, nm in enumerate(names) if i in used or nm in baseline_authors]
    if len(keep_idx) == len(names):
        return
    dropped = [names[i] for i in range(len(names)) if i not in keep_idx]
    remap = {old: new for new, old in enumerate(keep_idx)}
    for i, node in enumerate(nodes):
        if i not in remap:
            lists[0].remove(node)
    for cnode in find_local(root, "comment"):
        try:
            cnode.set("authorId", str(remap[int(cnode.get("authorId") or 0)]))
        except (ValueError, KeyError):
            pass
    parts[part] = serialize(root)
    touched.add(part)
    actions.append("removed %d author entr(ies) introduced during processing and now unused "
                   "from %s: %s" % (len(dropped), part, ", ".join(dropped)))


def prune_persons(parts, inv, actions, touched):
    """Drop person entries introduced during processing that nothing now uses."""
    used = set()
    for name in parts:
        if XLSX_THREAD_PART.match(name):
            root = parse(parts[name])
            for n in (find_local(root, "threadedComment") if root is not None else []):
                used.add((n.get("personId") or "").lower())
    baseline_persons = (inv or {}).get("persons", set())
    for name in [n for n in list(parts) if n.lower().startswith("xl/persons/")]:
        root = parse(parts[name])
        if root is None:
            continue
        lists = find_local(root, "personList")
        dropped = []
        for p in find_local(root, "person"):
            pid = (p.get("id") or "").lower()
            if pid not in used and pid not in baseline_persons:
                if lists and remove_child(root, p):
                    dropped.append(p.get("displayName") or pid)
        if dropped:
            parts[name] = serialize(root)
            touched.add(name)
            actions.append("removed %d person entr(ies) introduced during processing and now "
                           "unused from %s: %s" % (len(dropped), name, ", ".join(dropped)))


def drop_introduced_part(parts, name, inv, actions, touched):
    """Remove a part processing introduced, with its relationship and declaration."""
    if name not in parts or (inv and name in inv["parts"]):
        return False
    parts.pop(name)
    for rels in [n for n in parts if n.endswith(".rels")]:
        root = parse(parts[rels])
        if root is None:
            continue
        gone = []
        for r in relationships(root):
            t = r.get("Target")
            if t and resolve_target(rels, t) == name:
                gone.append(r.get("Id"))
                remove_child(root, r)
        if gone:
            parts[rels] = serialize(root)
            touched.add(rels)
    if "[Content_Types].xml" in parts:
        root = parse(parts["[Content_Types].xml"])
        if root is not None:
            changed = False
            for node in find_local(root, "Override"):
                if (node.get("PartName") or "").lstrip("/") == name:
                    changed = remove_child(root, node) or changed
            # A VML drawing is declared by extension, not by an Override. An
            # extension declaration introduced during processing goes once no
            # surviving part needs it; one that was in the baseline stays.
            ext = os.path.splitext(name)[1].lstrip(".").lower()
            baseline_defaults = (inv or {}).get("defaults", set())
            if ext and ext not in baseline_defaults and not [
                    n for n in parts if n.lower().endswith("." + ext)]:
                for node in find_local(root, "Default"):
                    if (node.get("Extension") or "").lower() == ext:
                        if remove_child(root, node):
                            changed = True
                            actions.append("removed the introduced content-type declaration "
                                           "for .%s, no part needs it" % ext)
            if changed:
                parts["[Content_Types].xml"] = serialize(root)
                touched.add("[Content_Types].xml")
    actions.append("removed %s, introduced during processing and no longer needed" % name)
    return True


def drop_legacy_drawing_ref(parts, vml_name, actions, touched):
    """Remove the worksheet reference to a VML drawing that has gone."""
    for sheet in [n for n in parts if re.match(r"^xl/worksheets/sheet", n, re.I)]:
        rels = "xl/worksheets/_rels/" + os.path.basename(sheet) + ".rels"
        if rels not in parts:
            continue
        rids = set()
        root = parse(parts[rels])
        for r in (relationships(root) if root is not None else []):
            t = r.get("Target")
            if t and resolve_target(rels, t) == vml_name:
                rids.add(r.get("Id"))
        if not rids:
            continue
        sroot = parse(parts[sheet])
        if sroot is None:
            continue
        changed = False
        for node in list(sroot.iter()):
            if local_name(node.tag) == "legacyDrawing":
                rid = None
                for a, v in node.attrib.items():
                    if local_name(a) == "id":
                        rid = v
                if rid in rids:
                    changed = remove_child(sroot, node) or changed
        if changed:
            parts[sheet] = serialize(sroot)
            touched.add(sheet)
            actions.append("removed the legacyDrawing reference from %s" % sheet)


def prune_vml(parts, comment_part, refs, inv, actions, touched):
    """Remove note shapes for removed cell comments, on that worksheet only."""
    targets = {col_row(r) for r in refs if col_row(r)}
    for vml in sheet_vml_for(parts, comment_part):
        if vml not in parts:
            continue
        raw = as_text(parts[vml])
        blocks, close = split_vml(raw)
        kept, removed = [], 0
        for block in blocks:
            if shape_cell(block) in targets:
                removed += 1
                continue
            kept.append(block)
        if not removed:
            continue
        new = "".join(kept) + close
        parts[vml] = new.encode("utf-8")
        touched.add(vml)
        actions.append("removed %d note shape(s) from %s" % (removed, vml))
        if 'ObjectType="Note"' not in new:
            # The worksheet reference is found through the relationship, so it
            # must go first, while that relationship still exists.
            if not inv or vml not in inv["parts"]:
                drop_legacy_drawing_ref(parts, vml, actions, touched)
                drop_introduced_part(parts, vml, inv, actions, touched)


def prune_docx_support(parts, paraids, inv, actions, touched):
    """Drop the commentsExtended, Ids and Extensible records of removed comments.

    commentsExtensible records are tied through durableId, not paraId, so the
    durable ids are resolved from commentsIds before anything is pruned.
    """
    durable = set()
    for name in [n for n in parts if re.match(r"^word/commentsIds\.xml$", n, re.I)]:
        root = parse(parts[name])
        for node in (root.iter() if root is not None else []):
            pid = (attr_local(node, "paraId") or "").lower()
            did = attr_local(node, "durableId")
            if pid in paraids and did:
                durable.add(did.lower())

    for name in [n for n in list(parts) if re.match(r"^word/commentsExtensible\.xml$", n, re.I)]:
        root = parse(parts[name])
        if root is None:
            continue
        dropped = 0
        for node in list(root.iter()):
            if node is root:
                continue
            did = (attr_local(node, "durableId") or "").lower()
            if did and did in durable:
                dropped += remove_child(root, node)
        if dropped:
            parts[name] = serialize(root)
            touched.add(name)
            actions.append("removed %d record(s) for the removed comment(s) from %s, matched "
                           "on durableId" % (dropped, name))

    for name in [n for n in list(parts) if DOCX_SUPPORT_PART.match(n)]:
        root = parse(parts[name])
        if root is None:
            continue
        dropped = 0
        for node in list(root.iter()):
            if node is root:
                continue
            ids = {v.lower() for a, v in node.attrib.items() if local_name(a) == "paraId"}
            if ids & paraids:
                dropped += remove_child(root, node)
        if dropped:
            parts[name] = serialize(root)
            touched.add(name)
            actions.append("removed %d record(s) for the removed comment(s) from %s"
                           % (dropped, name))
        root2 = parse(parts[name])
        if root2 is not None and not list(root2):
            drop_introduced_part(parts, name, inv, actions, touched)


def support_id(kind, name, item):
    """What makes one support record the same record as another."""
    if kind == "vml":
        return (kind, name, shape_cell(item))
    if kind == "legacydrawing":
        return (kind, name, "legacyDrawing")
    if kind == "anchor":
        return (kind, name, local_name(item.tag),
                item.get("{%s}id" % W_NS) or item.get("id"))
    if kind == "rel":
        return (kind, name, item.get("Id"))
    if kind == "person":
        return (kind, name, (item.get("id") or "").lower())
    return (kind, name, frozenset((local_name(a), v) for a, v in item.attrib.items()
                                  if local_name(a) in ("paraId", "durableId")))


def restore_missing_part(parts, name, inv, actions, touched):
    """Put back a support part that was deleted, with its relationship and declaration."""
    raw = (inv or {}).get("raw", {}).get(name)
    if raw is None or name in parts:
        return False
    parts[name] = raw
    touched.add(name)
    for rels, braw in (inv or {}).get("rels_raw", {}).items():
        broot = parse(braw)
        for r in (relationships(broot) if broot is not None else []):
            t = r.get("Target")
            if not t or resolve_target(rels, t) != name:
                continue
            if rels not in parts:
                parts[rels] = braw
                touched.add(rels)
                break
            croot = parse(parts[rels])
            if croot is None:
                break
            have = {x.get("Id") for x in relationships(croot)}
            if r.get("Id") not in have:
                croot.append(r)
                parts[rels] = serialize(croot)
                touched.add(rels)
            break
    bct = parse((inv or {}).get("ct_raw", b""))
    cct = parse(parts.get("[Content_Types].xml", b""))
    if bct is not None and cct is not None:
        changed = False
        have_over = {(n.get("PartName") or "").lstrip("/") for n in find_local(cct, "Override")}
        for node in find_local(bct, "Override"):
            if (node.get("PartName") or "").lstrip("/") == name and name not in have_over:
                cct.append(node)
                changed = True
        ext = os.path.splitext(name)[1].lstrip(".").lower()
        have_def = {(n.get("Extension") or "").lower() for n in find_local(cct, "Default")}
        for node in find_local(bct, "Default"):
            if (node.get("Extension") or "").lower() == ext and ext not in have_def:
                cct.append(node)
                changed = True
        if changed:
            parts["[Content_Types].xml"] = serialize(cct)
            touched.add("[Content_Types].xml")
    actions.append("restored %s, a support part deleted during processing" % name)
    return True


def vml_insert_shape(parts, name, block, actions, touched):
    """Put a deleted note shape back into its drawing."""
    blocks, close = split_vml(as_text(parts[name]))
    parts[name] = ("".join(blocks) + block + close).encode("utf-8")
    touched.add(name)
    actions.append("restored a note shape deleted during processing in %s" % name)


def vml_drop_shape(parts, name, cell, actions, touched):
    blocks, close = split_vml(as_text(parts[name]))
    kept = [b for b in blocks if shape_cell(b) != cell]
    if len(kept) != len(blocks):
        parts[name] = ("".join(kept) + close).encode("utf-8")
        touched.add(name)
        actions.append("removed a note shape added during processing from %s" % name)


def restore_support(parts, current, original, actions, touched, inv=None):
    """Reconcile the annotation's support set against the baseline.

    Three cases, all handled: a baseline record that was altered is replaced
    with the baseline version; a baseline record that was deleted is put back,
    with its part, relationship and declaration where the whole part had gone;
    and a record added during processing that the baseline did not have is
    removed.
    """
    base = {support_id(k, n, it): (k, n, it) for k, n, it in original.get("support", [])}
    now = {support_id(k, n, it): (k, n, it) for k, n, it in current.get("support", [])}

    for key, (kind, name, item) in base.items():
        if name not in parts:
            restore_missing_part(parts, name, inv, actions, touched)
        if name not in parts:
            actions.append("could not restore %s, the baseline copy is not available" % name)
            continue
        if kind == "anchor":
            root = parse(parts[name])
            if root is None:
                continue
            found = [n for n in root.iter() if support_id(kind, name, n) == key]
            if not found:
                actions.append("the %s anchor for comment %s is missing from %s and its "
                               "position cannot be inferred, so it was not reinserted; the run "
                               "fails and the anchor is restored by hand"
                               % (local_name(item.tag), current.get("id"), name))
            elif canon_node(found[0]) != canon_node(item):
                if replace_child(root, found[0], item):
                    parts[name] = serialize(root)
                    touched.add(name)
                    actions.append("restored the %s anchor for comment %s in %s"
                                   % (local_name(item.tag), current.get("id"), name))
            continue
        if kind == "rel":
            root = parse(parts[name]) if name in parts else None
            if root is None:
                if not restore_missing_part(parts, name, inv, actions, touched):
                    continue
                root = parse(parts[name])
            have = {r.get("Id") for r in relationships(root)}
            if item.get("Id") not in have:
                root.append(item)
                parts[name] = serialize(root)
                touched.add(name)
                actions.append("restored the comments relationship %s in %s"
                               % (item.get("Id"), name))
            continue
        if kind == "legacydrawing":
            root = parse(parts[name])
            if root is None:
                continue
            follower = original.get("legacy_follower", "")
            kids = list(root)
            found = [n for n in kids if local_name(n.tag) == "legacyDrawing"]
            here = ""
            if found:
                i = kids.index(found[0])
                here = local_name(kids[i + 1].tag) if i + 1 < len(kids) else ""
            if found and canon_node(found[0]) == canon_node(item) and here == follower:
                continue
            for n in found:
                remove_child(root, n)
            kids = list(root)
            at = len(kids)
            if follower:
                for i, n in enumerate(kids):
                    if local_name(n.tag) == follower:
                        at = i
                        break
            root.insert(at, item)
            parts[name] = serialize(root)
            touched.add(name)
            actions.append("restored the legacyDrawing reference in %s at its baseline position"
                           % name)
            continue
        if kind == "vml":
            blocks, close = split_vml(as_text(parts[name]))
            cell = shape_cell(item)
            if not any(shape_cell(b) == cell for b in blocks):
                vml_insert_shape(parts, name, item, actions, touched)
                continue
            out = [item if shape_cell(b) == cell else b for b in blocks]
            if out != blocks:
                parts[name] = ("".join(out) + close).encode("utf-8")
                touched.add(name)
                actions.append("restored the note shape in %s for the annotation at %s"
                               % (name, current.get("ref")))
            continue
        root = parse(parts[name])
        if root is None:
            continue
        target = None
        for node in ([n for n in find_local(root, "person")] if kind == "person"
                     else list(root)):
            if support_id(kind, name, node) == key:
                target = node
                break
        if target is None:
            root.append(item)
            parts[name] = serialize(root)
            touched.add(name)
            actions.append("restored the %s record in %s that was deleted during processing"
                           % (kind, name))
        elif canon_node(target) != canon_node(item):
            if replace_child(root, target, item):
                parts[name] = serialize(root)
                touched.add(name)
                actions.append("restored the %s record in %s that supports the annotation"
                               % (kind, name))

    for key, (kind, name, item) in now.items():
        if key in base or name not in parts:
            continue
        if inv and name not in inv["parts"]:
            drop_introduced_part(parts, name, inv, actions, touched)
            continue
        if kind == "vml":
            vml_drop_shape(parts, name, shape_cell(item), actions, touched)
            continue
        root = parse(parts[name])
        if root is None:
            continue
        for node in ([n for n in find_local(root, "person")] if kind == "person"
                     else list(root)):
            if support_id(kind, name, node) == key and remove_child(root, node):
                parts[name] = serialize(root)
                touched.add(name)
                actions.append("removed the %s record in %s added during processing, the "
                               "baseline had none" % (kind, name))
                break


def remove_comments(parts, decisions, actions, touched, inv=None):
    if inv is None:
        actions.append("no pre-edit inventory, so no annotation, author or person entry was "
                       "removed, pruned or restored")
        return
    return _remove_comments(parts, decisions, actions, touched, inv)


def _remove_comments(parts, decisions, actions, touched, inv=None):
    """Apply restorations and removals.

    Text outside the annotations is never altered, and infrastructure a
    pre-existing annotation still needs is never removed.
    """
    restored = {}
    for c, verdict, why in decisions:
        if verdict != "restore" or verdict in NO_MUTATION:
            continue
        original = (inv or {}).get("index", {}).get(match_key(c))
        if original is None:
            continue
        root = c["root"]
        if not replace_child(root, c["node"], original["node"]):
            continue
        if c["kind"] == "xlsx":
            lists = find_local(root, "authors")
            nodes = find_local(root, "author")
            if lists:
                names = [(a.text or "").strip() for a in nodes]
                want = original.get("author") or ""
                if want not in names:
                    tag = nodes[0].tag if nodes else "author"
                    new = ET.SubElement(lists[0], tag)
                    new.text = want
                    names.append(want)
                original["node"].set("authorId", str(names.index(want)))
        restore_support(parts, c, original, actions, touched, inv)
        restored.setdefault(c["part"], []).append(c)
    for part, items in restored.items():
        parts[part] = serialize(items[0]["root"])
        touched.add(part)
        actions.append("restored %d pre-existing annotation(s) in %s exactly as they were "
                       "before processing" % (len(items), part))

    by_part = {}
    for c, verdict, why in decisions:
        if verdict in NO_MUTATION:
            continue
        if verdict == "remove":
            by_part.setdefault(c["part"], []).append((c, why))

    docx_ids, docx_paraids, xlsx_refs = set(), set(), {}
    for part, items in by_part.items():
        root = items[0][0]["root"]
        for c, why in items:
            if c["kind"] == "docx":
                docx_ids.add(str(c.get("id")))
                docx_paraids |= para_ids(c["node"])
            if c["kind"] == "xlsx":
                xlsx_refs.setdefault(part, []).append(c["ref"])
            remove_child(root, c["node"])
        parts[part] = serialize(root)
        touched.add(part)
        actions.append("removed %d annotation(s) from %s: %s"
                       % (len(items), part,
                          "; ".join("%s%s, %s" % (c.get("ref") and c["ref"] + " " or "",
                                                  c.get("author") or "no author", why)
                                    for c, why in items)))

    for part, refs in xlsx_refs.items():
        prune_vml(parts, part, refs, inv, actions, touched)

    for part in [n for n in list(parts) if XLSX_COMMENT_PART.match(n)]:
        prune_authors(parts, part, inv, actions, touched)

    for part in list(by_part):
        if part not in parts:
            continue
        root = parse(parts[part])
        if root is None:
            continue
        if XLSX_COMMENT_PART.match(part):
            if not find_local(parse(parts[part]), "comment"):
                drop_introduced_part(parts, part, inv, actions, touched)
        elif XLSX_THREAD_PART.match(part):
            if not find_local(root, "threadedComment"):
                drop_introduced_part(parts, part, inv, actions, touched)

    if any(XLSX_THREAD_PART.match(p) for p in by_part):
        prune_persons(parts, inv, actions, touched)
        for name in [n for n in list(parts) if n.lower().startswith("xl/persons/")]:
            root = parse(parts[name])
            if root is not None and not find_local(root, "person"):
                drop_introduced_part(parts, name, inv, actions, touched)

    if docx_ids:
        # The anchors go with the comment, or Word repairs the file. Only the
        # anchor elements are removed; no text is touched.
        for name in [n for n in parts if re.match(
                r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$", n, re.I)]:
            root = parse(parts[name])
            if root is None:
                continue
            changed = 0
            for node in list(root.iter()):
                tag = local_name(node.tag)
                nid = node.get("{%s}id" % W_NS) or node.get("id")
                if tag in ("commentRangeStart", "commentRangeEnd") and nid in docx_ids:
                    changed += remove_child(root, node)
                elif tag == "commentReference" and nid in docx_ids:
                    parent = None
                    for cand in root.iter():
                        if node in list(cand):
                            parent = cand
                            break
                    changed += remove_child(root, node)
                    # The run goes only when nothing functional is left in it.
                    # A run can hold a break, a tab, a drawing or text next to
                    # the reference, and none of that belongs to the comment.
                    if parent is not None and local_name(parent.tag) == "r":
                        rest = [k for k in list(parent) if local_name(k.tag) != "rPr"]
                        if not rest and not (parent.text or "").strip():
                            changed += remove_child(root, parent)
            if changed:
                parts[name] = serialize(root)
                touched.add(name)
                actions.append("removed %d comment anchor(s) from %s, no text altered"
                               % (changed, name))
        prune_docx_support(parts, docx_paraids, inv, actions, touched)
        for name in [n for n in list(parts) if DOCX_COMMENT_PART.match(n)]:
            root = parse(parts[name])
            if root is not None and not find_local(root, "comment"):
                drop_introduced_part(parts, name, inv, actions, touched)
                for sup in [n for n in list(parts) if DOCX_SUPPORT_PART.match(n)]:
                    drop_introduced_part(parts, sup, inv, actions, touched)


def verify_comments(data, inv):
    """Final validation of the annotation rule. Returns (ok, checks)."""
    checks = []
    after = collect_comments(data)
    if inv is None:
        checks.append("annotation validation: NOT PERFORMED, no pre-edit inventory supplied. "
                      "%d annotation(s) present, all preserved. Without the inventory this run "
                      "can certify neither that none was created nor that none was lost earlier "
                      "in the workflow, so the result is not a pass. Supply --baseline."
                      % len(after))
        return False, checks

    after_keys = {comment_key(c) for c in after}
    added = [c for c in after if comment_key(c) not in inv["keys"]]
    missing = inv["keys"] - after_keys
    checks.append("no annotation exists that was not in the pre-edit inventory: %s"
                  % ("pass" if not added else "FAIL, %d added: %s"
                     % (len(added), "; ".join("%s %s" % (c["part"], c.get("ref") or c.get("id"))
                                              for c in added[:5]))))
    checks.append("every pre-existing annotation is still present and unchanged: %s"
                  % ("pass" if not missing else "FAIL, %d missing or altered: %s"
                     % (len(missing), "; ".join(str(k[:3]) for k in sorted(missing)[:3]))))

    orphans = []
    for name in data:
        low = name.lower()
        if XLSX_COMMENT_PART.match(name):
            root = parse(data[name])
            if root is not None:
                if not find_local(root, "comment"):
                    orphans.append(name + " (comment part with no comments)")
                names = [(a.text or "").strip() for a in find_local(root, "author")]
                used = set()
                for cnode in find_local(root, "comment"):
                    try:
                        used.add(int(cnode.get("authorId") or 0))
                    except ValueError:
                        pass
                base = inv["authors"].get(name, set())
                stray = [nm for i, nm in enumerate(names) if i not in used and nm not in base]
                if stray:
                    orphans.append("%s (author entr(ies) introduced and unused: %s)"
                                   % (name, ", ".join(stray)))
                for nm in base:
                    if nm not in names:
                        orphans.append("%s (baseline author %s no longer present)" % (name, nm))
        if XLSX_THREAD_PART.match(name):
            root = parse(data[name])
            if root is not None and not find_local(root, "threadedComment"):
                orphans.append(name + " (threaded-comment part with no comments)")
        if DOCX_COMMENT_PART.match(name):
            root = parse(data[name])
            if root is not None and not find_local(root, "comment"):
                orphans.append(name + " (comment part with no comments)")
        if low.endswith(".vml"):
            raw = as_text(data[name])
            shapes = len(re.findall(r'ObjectType="Note"', raw))
            if shapes and not [c for c in after if c["kind"] == "xlsx"]:
                orphans.append(name + " (%d note shape(s) with no comment)" % shapes)

    people = persons_in(data)
    used_persons = {c["person"] for c in after if c["kind"] == "xlsx-threaded"}
    for pid in used_persons:
        if pid and pid not in people:
            orphans.append("threaded comment references person %s, which is not present" % pid)
    for pid in people:
        if pid not in used_persons and pid not in inv["persons"]:
            orphans.append("person %s introduced during processing and unreferenced" % pid)
    for pid in inv["persons"]:
        if pid not in people:
            orphans.append("baseline person %s no longer present" % pid)

    # a worksheet reference to a drawing that has gone
    for sheet in [n for n in data if re.match(r"^xl/worksheets/sheet", n, re.I)]:
        rels = "xl/worksheets/_rels/" + os.path.basename(sheet) + ".rels"
        known = set()
        root = parse(data[rels]) if rels in data else None
        for r in (relationships(root) if root is not None else []):
            known.add(r.get("Id"))
        sroot = parse(data[sheet])
        for node in (sroot.iter() if sroot is not None else []):
            if local_name(node.tag) == "legacyDrawing":
                rid = attr_local(node, "id")
                if rid and rid not in known:
                    orphans.append("%s legacyDrawing points at %s, which no longer exists"
                                   % (sheet, rid))

    for original in inv["index"].values():
        for kind, name, item in original.get("support", []):
            if kind != "legacydrawing":
                continue
            root = parse(data[name]) if name in data else None
            found = [n for n in (root.iter() if root is not None else [])
                     if local_name(n.tag) == "legacyDrawing"]
            kids = list(root) if root is not None else []
            if not found:
                orphans.append("%s no longer has the legacyDrawing reference the baseline had"
                               % name)
            elif canon_node(found[0]) != canon_node(item):
                orphans.append("%s legacyDrawing differs from the baseline" % name)
            else:
                i = kids.index(found[0])
                here = local_name(kids[i + 1].tag) if i + 1 < len(kids) else ""
                if here != original.get("legacy_follower", ""):
                    orphans.append("%s legacyDrawing has moved from its baseline position"
                                   % name)

    # a content-type declaration introduced during processing that nothing needs
    ct = parse(data.get("[Content_Types].xml", b""))
    for node in (find_local(ct, "Default") if ct is not None else []):
        ext = (node.get("Extension") or "").lower()
        if ext and ext not in inv["defaults"] and not [
                n for n in data if n.lower().endswith("." + ext)]:
            orphans.append("content-type declaration for .%s with no part that needs it" % ext)

    # the paraId to durableId chain in the Word support parts
    live_para = set()
    for name in data:
        if DOCX_COMMENT_PART.match(name):
            root = parse(data[name])
            for cnode in (find_local(root, "comment") if root is not None else []):
                live_para |= para_ids(cnode)
    live_durable = set()
    for name in data:
        if re.match(r"^word/commentsIds\.xml$", name, re.I):
            root = parse(data[name])
            for node in (root.iter() if root is not None else []):
                pid = (attr_local(node, "paraId") or "").lower()
                did = attr_local(node, "durableId")
                if pid and pid not in live_para:
                    orphans.append("%s holds a record for paraId %s with no comment" % (name, pid))
                elif did:
                    live_durable.add(did.lower())
    for name in data:
        if re.match(r"^word/commentsExtensible\.xml$", name, re.I):
            root = parse(data[name])
            for node in (root.iter() if root is not None else []):
                did = (attr_local(node, "durableId") or "").lower()
                if did and did not in live_durable:
                    orphans.append("%s holds a record for durableId %s with no comment"
                                   % (name, did))
        if re.match(r"^word/commentsExtended\.xml$", name, re.I):
            root = parse(data[name])
            for node in (root.iter() if root is not None else []):
                pid = (attr_local(node, "paraId") or "").lower()
                if pid and pid not in live_para:
                    orphans.append("%s holds a record for paraId %s with no comment" % (name, pid))

    for rels in [n for n in data if n.endswith(".rels")]:
        for t in internal_targets(rels, data[rels]):
            if t not in data:
                orphans.append("%s -> %s" % (rels, t))

    checks.append("no orphaned comment, threaded-comment, person, author, relationship or VML "
                  "object was introduced: %s"
                  % ("pass" if not orphans else "FAIL: " + "; ".join(sorted(set(orphans))[:5])))
    return (not added and not missing and not orphans), checks


def signature_parts(parts):
    sigs = [n for n in parts if SIGNATURE_PART.match(n)]
    for n in parts:
        if n.endswith(".rels") and "digital-signature" in as_text(parts[n]):
            sigs.append(n)
    return sorted(set(sigs))


def drop_relationships(parts, removed, actions):
    dropped_ids = {}
    for rels in [n for n in parts if n.endswith(".rels")]:
        root = parse(parts[rels])
        if root is None:
            actions.append("could not parse %s as XML, relationships left untouched" % rels)
            continue
        ids = []
        for r in relationships(root):
            if rel_is_external(r):
                continue
            t = r.get("Target")
            if t and resolve_target(rels, t) in removed:
                ids.append(r.get("Id"))
                remove_child(root, r)
        if ids:
            parts[rels] = serialize(root)
            dropped_ids[rels] = ids
            actions.append("removed %d relationship entr(ies) in %s, parsed as XML and matched "
                           "on the resolved full target" % (len(ids), rels))
    return dropped_ids


def drop_content_types(parts, removed, actions):
    if "[Content_Types].xml" not in parts:
        return
    root = parse(parts["[Content_Types].xml"])
    if root is None:
        actions.append("could not parse [Content_Types].xml as XML, overrides left untouched")
        return
    dropped = 0
    for node in find_local(root, "Override"):
        if (node.get("PartName") or "").lstrip("/") in removed:
            dropped += remove_child(root, node)
    if dropped:
        parts["[Content_Types].xml"] = serialize(root)
        actions.append("removed %d content-type override(s) for the removed parts" % dropped)


def prune_taskpanes(parts, dropped_ids, actions):
    R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    gone = set()
    for tp in [n for n in list(parts) if TASKPANES_PART.match(n)]:
        rels = os.path.dirname(tp) + "/_rels/" + os.path.basename(tp) + ".rels"
        ids = dropped_ids.get(rels, [])
        if not ids:
            continue
        root = parse(parts[tp])
        if root is None:
            actions.append("could not parse %s as XML, task pane left untouched" % tp)
            continue
        removed_panes = 0
        for pane in [c for c in list(root) if local_name(c.tag) == "taskpane"]:
            rids = [d.get("{%s}id" % R) or d.get("id")
                    for d in pane.iter() if local_name(d.tag) == "webextensionref"]
            if any(r in ids for r in rids):
                removed_panes += remove_child(root, pane)
        if removed_panes:
            parts[tp] = serialize(root)
            actions.append("removed %d task-pane entr(ies) in %s, matched on local element name"
                           % (removed_panes, tp))
        if not [c for c in list(root) if local_name(c.tag) == "taskpane"]:
            parts.pop(tp, None)
            parts.pop(rels, None)
            gone |= {tp, rels}
            actions.append("removed %s, no task pane left" % tp)
    return gone


def strip_custom_properties(parts, actions, reported):
    if "docProps/custom.xml" not in parts:
        return set()
    root = parse(parts["docProps/custom.xml"])
    if root is None:
        actions.append("could not parse docProps/custom.xml as XML, properties left untouched")
        return set()
    removed_props = []
    for node in find_local(root, "property"):
        verdict, why = custom_property_verdict(node)
        label = node.get("name") or "(unnamed)"
        if verdict == "remove":
            if remove_child(root, node):
                removed_props.append("%s (%s)" % (label, why))
        elif verdict == "report":
            reported.append("custom property %s %s" % (label, why))
    if not removed_props:
        return set()
    if not find_local(root, "property"):
        parts.pop("docProps/custom.xml")
        actions.append("removed docProps/custom.xml, every property qualified: "
                       + ", ".join(removed_props))
        return {"docProps/custom.xml"}
    parts["docProps/custom.xml"] = serialize(root)
    actions.append("removed custom propert(ies): " + ", ".join(removed_props))
    return set()


def trees_equal(a, b):
    """Structural comparison. Namespace URIs and local names, never prefixes."""
    if a is None or b is None:
        return a is b
    if a.tag != b.tag or a.attrib != b.attrib:
        return False
    if (a.text or "").strip() != (b.text or "").strip():
        return False
    if (a.tail or "").strip() != (b.tail or "").strip():
        return False
    ca, cb = list(a), list(b)
    if len(ca) != len(cb):
        return False
    return all(trees_equal(x, y) for x, y in zip(ca, cb))


def remove_abspath_tree(root):
    """Remove absPath and any wrapper it leaves empty. Returns paths removed."""
    removed = []
    for node in [n for n in root.iter() if local_name(n.tag) == "absPath"]:
        removed.append(node.get("url") or "")
        remove_child(root, node)
    if not removed:
        return removed
    for _ in range(3):                       # Choice, then AlternateContent
        empties = [n for n in root.iter()
                   if local_name(n.tag) in ("Choice", "Fallback", "AlternateContent")
                   and not list(n) and not (n.text or "").strip()]
        if not empties:
            break
        for n in empties:
            remove_child(root, n)
    return removed


def strip_abspath(parts, actions):
    """Removed through the XML tree, matched on local name. No substitution."""
    for name in list(parts):
        if not name.lower().endswith(".xml"):
            continue
        root = parse(parts[name])
        if root is not None and not [n for n in root.iter()
                                     if local_name(n.tag) == "absPath"]:
            continue
        if root is None:
            actions.append("could not parse %s as XML, absPath left in place" % name)
            continue
        removed = remove_abspath_tree(root)
        if removed:
            parts[name] = serialize(root)
            actions.append("removed the absolute working path record absPath from %s (%s)"
                           % (name, "; ".join(v for v in removed if v)))


def clean_docprops(parts, author_mode, author_name, actions, suspicious, accepted):
    """All writes go through the XML parser, so values are escaped correctly."""
    for part in ("docProps/core.xml", "docProps/app.xml"):
        if part not in parts:
            continue
        root = parse(parts[part])
        if root is None:
            actions.append("could not parse %s as XML, left untouched" % part)
            continue
        changed = False

        for node in find_local(root, "HyperlinkBase"):
            lp = path_hits_in_field(node.text or "")
            if lp:
                node.text = ""
                changed = True
                actions.append("cleared HyperlinkBase in %s, its value was a local working "
                               "path (%s)" % (part, "; ".join(lp)))

        if author_mode == "blank":
            for tag in AUTHOR_TAGS + COMPANY_TAGS:
                for node in find_local(root, tag):
                    if (node.text or "").strip():
                        node.text = ""
                        changed = True
                        actions.append("blanked %s in %s, instructed by --blank-author"
                                       % (tag, part))
        elif author_mode == "set":
            for tag in AUTHOR_TAGS:          # Company and Manager are not touched
                nodes = find_local(root, tag)
                if not nodes:
                    if part != "docProps/core.xml":
                        continue
                    node = ET.SubElement(root, "{%s}%s" % (AUTHOR_NS[tag], tag))
                    node.text = author_name
                    changed = True
                    actions.append("created %s in %s and set it to %r, instructed by --author; "
                                   "the field was absent" % (tag, part, author_name))
                    continue
                for node in nodes:
                    node.text = author_name  # the parser escapes & < > for us
                    changed = True
                    actions.append("set %s in %s to %r, instructed by --author"
                                   % (tag, part, author_name))

        for tag in AUTHOR_TAGS + COMPANY_TAGS:
            for node in find_local(root, tag):
                value = (node.text or "").strip()
                if not value or not has_marker(value):
                    continue
                kw, lp = markers(value)
                if acceptable(kw, lp) and (part, tag, value) in accepted:
                    continue          # an explicit decision has been recorded
                suspicious.append("%s in %s = %s" % (tag, part, value))

        if changed:
            parts[part] = serialize(root)


def clean_ooxml(parts, unnecessary, author_mode, author_name, accepted,
                comment_decisions=None, touched=None, inv=None):
    actions, suspicious, reported = [], [], []
    out = dict(parts)
    removed = set()

    for n in unnecessary:
        out.pop(n, None)
        removed.add(n)
        rels = os.path.dirname(n) + "/_rels/" + os.path.basename(n) + ".rels"
        if rels in out:
            out.pop(rels)
            removed.add(rels)
    if unnecessary:
        actions.append("removed %d web-extension part(s) carrying a marker: %s"
                       % (len(unnecessary), ", ".join(sorted(unnecessary))))

    dropped_ids = drop_relationships(out, removed, actions)
    gone = prune_taskpanes(out, dropped_ids, actions)
    removed |= gone
    if gone:
        drop_relationships(out, removed, actions)
    removed |= strip_custom_properties(out, actions, reported)
    drop_relationships(out, removed, actions)
    drop_content_types(out, removed, actions)
    strip_abspath(out, actions)
    clean_docprops(out, author_mode, author_name, actions, suspicious, accepted)
    if comment_decisions:
        remove_comments(out, comment_decisions, actions,
                        touched if touched is not None else set(), inv)

    for n in [x for x in list(out) if WEBEXT_DIR.match(x) and x.endswith(".rels")]:
        base = n.replace("/_rels/", "/")[:-len(".rels")]
        if base not in out:
            out.pop(n)
            removed.add(n)
            actions.append("removed orphaned relationship part " + n)

    return out, actions, removed, suspicious, reported


def write_package(parts, dest):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        if "[Content_Types].xml" in parts:
            z.writestr("[Content_Types].xml", parts["[Content_Types].xml"])
        for n in parts:
            if n != "[Content_Types].xml":
                z.writestr(n, parts[n])


# ---------------------------------------------------------------- verification

def verify_package(dest, original_parts, removed_names, preserved_ext, suspicious,
                   author_mode=None, author_name=None, accepted=None, matched=None,
                   comment_touched=None, inv=None, comment_removed=None,
                   comment_added=None, base_parts=None, detail=None):
    checks = []
    ok = True
    try:
        with zipfile.ZipFile(dest) as z:
            bad = z.testzip()
            names = set(z.namelist())
            data = {n: z.read(n) for n in names}
    except Exception as e:
        return False, ["package will not open as a zip: %s" % e], ["package unreadable"]
    defects = package_defects(data)
    checks.append("required package structure present, that is the content-type manifest, the "
                  "root officeDocument relationship, its target and the main part's content "
                  "type: %s" % ("pass" if not defects else "FAIL, " + "; ".join(defects)))
    ok = ok and not defects

    checks.append("package opens and every member decompresses: %s"
                  % ("pass" if bad is None else "FAIL " + str(bad)))
    ok = ok and bad is None

    ns_defects = namespace_defects(data, original_parts)
    checks.append("namespace references resolve in scope to their original URIs: %s"
                  % ("pass" if not ns_defects else "FAIL, " + "; ".join(ns_defects[:5])))
    ok = ok and not ns_defects

    unparsable = [n for n in sorted(names)
                  if n.lower().endswith((".xml", ".rels")) and parse(data[n]) is None]
    checks.append("every XML part parses: %s"
                  % ("pass" if not unparsable else "FAIL, will not parse: "
                     + ", ".join(unparsable[:5])))
    ok = ok and not unparsable

    expected = ((set(original_parts) | set(comment_added or ()))
                - set(removed_names) - set(comment_removed or ()))
    missing, extra = expected - names, names - expected
    checks.append("part count %d, expected %d" % (len(names), len(expected)))
    if missing:
        ok = False
        checks.append("FAIL parts missing: " + ", ".join(sorted(missing)))
    if extra:
        ok = False
        checks.append("FAIL unexpected parts: " + ", ".join(sorted(extra)))

    unresolved = []
    for rels in [n for n in names if n.endswith(".rels")]:
        for t in internal_targets(rels, data[rels]):
            if t not in names:
                unresolved.append("%s -> %s" % (rels, t))
    checks.append("internal relationship targets resolve: %s"
                  % ("pass" if not unresolved else "FAIL, dangling: " + "; ".join(unresolved[:5])))
    ok = ok and not unresolved

    declared = set()
    ct_root = parse(data.get("[Content_Types].xml", b""))
    if ct_root is not None:
        for node in find_local(ct_root, "Override"):
            if node.get("PartName"):
                declared.add(node.get("PartName").lstrip("/"))
    orphan = sorted(d for d in declared if d not in names)
    checks.append("content-type overrides all point at a present part: %s"
                  % ("pass" if not orphan else "FAIL " + ", ".join(orphan[:5])))
    ok = ok and not orphan

    allowed = re.compile(r"(^\[Content_Types\]\.xml$|\.rels$|^docProps/|"
                         r"webextensions/taskpanes\.xml$)", re.I)
    comment_touched = comment_touched or set()
    unauthorized, text_moved = [], []
    for n in sorted(names & set(original_parts)):
        if data[n] == original_parts[n] or allowed.search(n):
            continue
        if n in comment_touched:
            # A comment removal may change this part. Text must not move with it.
            rb, ra = parse(original_parts[n]), parse(data[n])
            def body_text(root):
                if root is None:
                    return None
                return " ".join(
                    (e.text or "").strip() for e in root.iter()
                    if local_name(e.tag) in ("t", "v") and (e.text or "").strip())
            if n.lower().startswith("word/") and not n.lower().endswith("comments.xml"):
                if body_text(rb) != body_text(ra):
                    text_moved.append(n)
            continue
        rb = parse(original_parts[n])
        if rb is not None and [x for x in rb.iter() if local_name(x.tag) == "absPath"]:
            if remove_abspath_tree(rb) and trees_equal(rb, parse(data[n])):
                continue          # the only change is the absPath removal
        unauthorized.append(n)
    checks.append("every part outside the authorized metadata, relationship and comment set "
                  "is byte-identical to the original: %s"
                  % ("pass" if not unauthorized else "FAIL, changed: "
                     + ", ".join(unauthorized[:6])))
    ok = ok and not unauthorized
    if comment_touched:
        checks.append("parts changed by the comment removal: " + ", ".join(sorted(comment_touched)))
        checks.append("document text in those parts is unchanged: %s"
                      % ("pass" if not text_moved else "FAIL, text differs in "
                         + ", ".join(text_moved)))
        ok = ok and not text_moved

    sheets = [n for n in names if re.match(r"^xl/worksheets/sheet", n, re.I)]
    if sheets:
        def formulas(xml):
            return re.findall(r"<(?:[A-Za-z0-9_.-]+:)?f\b[^>]*>(.*?)</(?:[A-Za-z0-9_.-]+:)?f>",
                              xml, re.S)
        before = [f for n in sheets if n in original_parts
                  for f in formulas(as_text(original_parts[n]))]
        after = [f for n in sheets for f in formulas(as_text(data[n]))]
        checks.append("worksheet formula expressions compared in order, %d before, %d after: %s"
                      % (len(before), len(after),
                         "identical" if before == after else "FAIL, text differs"))
        ok = ok and before == after
        errs = ["%s in %s" % (tok, n) for n in sheets
                for tok in ("#REF!", "#VALUE!", "#NAME?", "#DIV/0!", "#N/A")
                if tok in as_text(data[n])]
        checks.append("literal error residues in worksheets: %s"
                      % ("none detected" if not errs else "; ".join(sorted(set(errs))[:5])))

    for label, rx, by_part in (
            ("defined names", re.compile(r"<(?:[A-Za-z0-9_.-]+:)?definedName\b"), False),
            ("data validation", re.compile(r"<(?:[A-Za-z0-9_.-]+:)?dataValidation\b"), False),
            ("conditional formatting",
             re.compile(r"<(?:[A-Za-z0-9_.-]+:)?conditionalFormatting\b"), False),
            ("charts", re.compile(r"^(xl|word|ppt)/charts/chart\d+\.xml$", re.I), True),
            ("tables", re.compile(r"^xl/tables/", re.I), True),
            ("pivot structures", re.compile(r"^xl/pivot", re.I), True),
            ("embedded objects", re.compile(r"(embeddings/|oleObject)", re.I), True)):
        if by_part:
            b = len([n for n in original_parts if rx.search(n)])
            a = len([n for n in names if rx.search(n)])
        else:
            b = sum(len(rx.findall(as_text(v))) for k, v in original_parts.items()
                    if k.endswith(".xml"))
            a = sum(len(rx.findall(as_text(v))) for k, v in data.items() if k.endswith(".xml"))
        checks.append("%s before %d, after %d: %s" % (label, b, a, "pass" if b == a else "FAIL"))
        ok = ok and b == a

    stranded = []
    for ext in preserved_ext:
        if ext not in names:
            stranded.append(ext + " (part removed)")
            continue
        owner_rels = os.path.dirname(ext) + "/_rels/taskpanes.xml.rels"
        tp = os.path.dirname(ext) + "/taskpanes.xml"
        if owner_rels not in names or tp not in names:
            stranded.append(ext + " (task pane or its relationships removed)")
        elif ext not in internal_targets(owner_rels, data[owner_rels]):
            stranded.append(ext + " (no relationship from the task pane)")
        elif not any(tp in internal_targets(r, data[r])
                     for r in names if r.endswith(".rels") and r != owner_rels):
            stranded.append(tp + " (task pane no longer referenced by any part)")
    if preserved_ext:
        checks.append("retained web extension(s) still reachable through the full relationship "
                      "chain: %s" % ("pass" if not stranded else "FAIL, stranded: "
                                     + "; ".join(stranded)))
        ok = ok and not stranded

    if author_mode == "set":
        core = parse(data.get("docProps/core.xml", b""))
        got = {}
        for tag in AUTHOR_TAGS:
            nodes = find_local(core, tag) if core is not None else []
            got[tag] = (nodes[0].text or "").strip() if nodes else None
        good = all(got[t] == author_name for t in AUTHOR_TAGS)
        checks.append("both author fields hold the requested value: %s"
                      % ("pass" if good else "FAIL, creator=%r lastModifiedBy=%r, requested %r"
                         % (got["creator"], got["lastModifiedBy"], author_name)))
        ok = ok and good

    if suspicious:
        checks.append("author or company field carrying a tool name or a path, reported and NOT "
                      "altered, decide and re-run with --author or --blank-author: "
                      + "; ".join(suspicious))
        ok = False

    # The same classification routine that produced the inspection.
    final = classify(data, accepted, matched, base_parts)
    residue = ["%s: %s" % (n, d) for k, n, d in final if k in FAILING]
    content = ["%s: %s" % (n, d) for k, n, d in final if k == "content"]
    checks.append("post-clean classification, same routine as the inspection: %s"
                  % ("no package-level item remains" if not residue
                     else "NOT CLEAR, still present, " + "; ".join(residue[:8])))
    if content:
        checks.append("tool name inside visible document content, reviewer decision, not removed "
                      "automatically: " + "; ".join(content[:5]))
    c_ok, c_checks = verify_comments(data, inv)
    checks.extend(c_checks)
    ok = ok and c_ok

    info = ["%s: %s" % (n, d) for k, n, d in final if k == "info"]
    if info:
        checks.append("informational findings, disclosed and not a failure: "
                      + "; ".join(info[:8]))

    checks.append("Excel, Word or PowerPoint application open and recalculation verification: "
                  "NOT PERFORMED, no native application in this runtime")
    if detail is not None:
        detail["struct_ok"] = ok      # every check except the classified residue
        detail["final"] = final
    ok = ok and not residue
    return ok, checks, residue


# ---------------------------------------------------------------- other formats

def xmp_values(root):
    """Every named value in an XMP tree.

    XMP stores a property either as element text or as an XML attribute, and
    both forms are valid, so both are read. An attribute is named by its local
    name and classified exactly as the equivalent element would be.
    """
    out = []
    for node in root.iter():
        for attr, value in node.attrib.items():
            name = local_name(attr)
            if name in ("about", "lang", "parseType", "resource", "nodeID", "ID", "datatype"):
                continue                      # RDF plumbing, not a property
            value = (value or "").strip()
            if value:
                out.append((name, value))
        if list(node):
            continue                          # a container holds no text value
        text = (node.text or "").strip()
        if text:
            out.append((local_name(node.tag), text))
    return out


def _pypdf():
    try:
        import pypdf
        return pypdf
    except ImportError:
        try:
            import PyPDF2 as pypdf
            return pypdf
        except ImportError:
            return None


def scan_pdf(path, accepted=None, matched=None):
    """Inspect PDF metadata.

    A PDF parser is used where one is installed, and its reading is complete
    enough to support a pass. Without one, this routine reads only what is
    plain text, which cannot establish that nothing was missed: a hexadecimal
    string, a compressed object stream or an encoded name all hide metadata
    from it. In that case the result is INDETERMINATE, never a pass.

    Returns (report lines, confirmed traces, reasons the inspection is
    incomplete).
    """
    raw = open(path, "rb").read()
    out, traces, incomplete, review, infos = [], [], [], [], []
    accepted = accepted or {}
    if matched is None:
        matched = set()

    pypdf = _pypdf()
    if pypdf is not None:
        try:
            reader = pypdf.PdfReader(path)
            out.append("read with %s, a PDF parser, so the metadata below is the active "
                       "metadata and not only what is plain text" % pypdf.__name__)
            info = reader.metadata or {}
            for field in info:
                value = str(info[field])
                out.append("%s = %s" % (field, value[:120]))
                kw, lp = markers(value)
                if not kw and not lp:
                    continue
                key = ("pdf", field, value)
                if acceptable(kw, lp) and key in accepted:
                    matched.add(key)
                    out.append("%s = %s, %s" % (field, value, accept_note(accepted, key)))
                elif lp or field in PDF_PROVENANCE:
                    traces.append("%s carries %s" % (field, describe(kw, lp)))
                else:
                    review.append("%s = %s, a descriptive field carrying %s, which may be the "
                                  "subject rather than provenance" % (field, value,
                                                                      describe(kw, lp)))
            xmp = getattr(reader, "xmp_metadata", None)
            if xmp is None:
                out.append("no XMP packet present")
            else:
                raw_xmp = None
                try:                                   # the XMP stream itself, as bytes
                    raw_xmp = xmp.stream.get_data()
                except Exception:
                    for attr in ("rdf_root", "rdfRoot"):   # API name has changed
                        node = getattr(xmp, attr, None)
                        if node is not None:
                            try:
                                raw_xmp = node.toxml().encode("utf-8")
                            except Exception:
                                raw_xmp = str(node).encode("utf-8", "replace")
                            break
                if raw_xmp is None:
                    incomplete.append("the parser reports an XMP packet but its content could "
                                      "not be read, so the XMP was not inspected")
                else:
                    # Parsed from bytes, so a UTF-16 packet is read by its own
                    # declaration rather than mangled by a UTF-8 decode.
                    root = parse(raw_xmp)
                    if root is None:
                        incomplete.append("the XMP packet will not parse as XML, so it was not "
                                          "inspected")
                    else:
                        out.append("XMP packet read by the parser")
                        for tag, value in xmp_values(root):
                            if tag in PDF_PROVENANCE or tag in PDF_DESCRIPTIVE:
                                out.append("XMP %s = %s" % (tag, value[:120]))
                            kw, lp = markers(value)
                            if not kw and not lp:
                                continue
                            key = ("pdf", tag, value)
                            if acceptable(kw, lp) and key in accepted:
                                matched.add(key)
                                out.append("XMP %s = %s, %s"
                                           % (tag, value, accept_note(accepted, key)))
                            elif lp or tag in PDF_PROVENANCE:
                                traces.append("XMP %s carries %s" % (tag, describe(kw, lp)))
                            else:
                                review.append("XMP %s = %s, a descriptive field carrying %s, "
                                              "which may be the subject rather than provenance"
                                              % (tag, value, describe(kw, lp)))
            if b"/EmbeddedFile" in raw:
                out.append("embedded file(s) present")
            if b"/Sig" in raw or b"/DocMDP" in raw:
                out.append("signature dictionary present, do not rewrite this file")
            pdf_artifacts(reader, out, traces, review, infos, accepted, matched)
            out.append("metadata sanitation was NOT performed; this routine only inspects")
            return out, traces, incomplete, review, infos
        except Exception as e:
            incomplete.append("the PDF parser could not read this file (%s)" % e)

    # No parser available, or it failed. Plain-text reading only, and it can
    # never establish completeness, so every such file is indeterminate.
    for m in re.finditer(rb"/(Author|Creator|Producer|Company|Title|Subject|Keywords)"
                         rb"\s*\((?:\\.|[^\\()])*\)", raw):
        block = m.group(0).decode("latin-1", "replace")
        key, _, value = block.partition("(")
        value = value.rstrip(")")
        field = key.strip()
        out.append("%s = %s" % (field, value[:120]))
        kw, lp = markers(value)
        if kw or lp:
            if lp or field in PDF_PROVENANCE:
                traces.append("%s carries %s" % (field, describe(kw, lp)))
            else:
                review.append("%s = %s, a descriptive field carrying %s"
                              % (field, value, describe(kw, lp)))

    # Hexadecimal strings are a valid representation and are read here too, so
    # they are at least reported rather than passing unseen.
    for m in re.finditer(rb"/(Author|Creator|Producer|Company|Title|Subject|Keywords)"
                         rb"\s*<([0-9A-Fa-f\s]+)>", raw):
        key = m.group(1).decode()
        try:
            value = bytes.fromhex(re.sub(rb"\s", b"", m.group(2)).decode()).decode(
                "utf-16-be" if m.group(2).strip()[:4].lower() == b"feff" else "latin-1",
                "replace")
        except ValueError:
            continue
        out.append("/%s = %s (hexadecimal string)" % (key, value[:120]))
        kw, lp = markers(value)
        if kw or lp:
            if lp or ("/" + key) in PDF_PROVENANCE:
                traces.append("/%s carries %s" % (key, describe(kw, lp)))
            else:
                review.append("/%s = %s, a descriptive field carrying %s"
                              % (key, value, describe(kw, lp)))

    for m in re.finditer(rb"<\?xpacket begin.*?<\?xpacket end[^>]*\?>", raw, re.S):
        xmp = m.group(0).decode("utf-8", "replace")
        root = parse(m.group(0))
        if root is not None:
            for tag, value in xmp_values(root):
                if tag in PDF_PROVENANCE or tag in PDF_DESCRIPTIVE:
                    out.append("XMP %s = %s" % (tag, value[:120]))
                kw, lp = markers(value)
                if not kw and not lp:
                    continue
                if lp or tag in PDF_PROVENANCE:
                    traces.append("XMP %s carries %s" % (tag, describe(kw, lp)))
                else:
                    review.append("XMP %s = %s, a descriptive field carrying %s"
                                  % (tag, value, describe(kw, lp)))
        else:
            incomplete.append("an XMP packet will not parse as XML, so it was not inspected")

    if b"/EmbeddedFile" in raw:
        out.append("embedded file(s) present")
    if b"/Annots" in raw:
        out.append("annotations present")
    if b"/Sig" in raw or b"/DocMDP" in raw:
        out.append("signature dictionary present, do not rewrite this file")

    incomplete.append("no PDF parser is installed, so only plain-text metadata was read. "
                      "A hexadecimal string, a compressed object stream or an encoded name "
                      "can hide metadata from this reading, so the absence of a trace here "
                      "proves nothing")
    out.append("inspection limited to plain-text metadata. Install pypdf, or inspect the file "
               "with a PDF tool, before treating any PDF as cleared.")
    out.append("page text and link targets were not inspected for citation tokens or the "
               "ChatGPT tracking parameter, which needs a PDF parser")
    return out, traces, incomplete, review, infos


def pdf_artifacts(reader, out, traces, review, info, accepted, matched):
    """Citation tokens and the ChatGPT tracking parameter in a PDF's page text
    and link targets (AI Fix only; Fix Language does not handle PDF). Read
    only. Hidden Unicode is not classified in PDF text: what an extractor
    returns depends on the fonts, so a character there is not evidence."""
    checked = 0
    try:
        for i, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            checked += 1
            for _s, _e, token, what, confirmed in citation_hits(text):
                key = ("pdf", "citation", token)
                if confirmed:
                    traces.append("page %d: %s %s, a generation-only token. A PDF is not "
                                  "edited by this procedure: correct the source and regenerate"
                                  % (i, what, visible_snippet(token, 0, len(token), 0)))
                elif key in accepted:
                    matched.add(key)
                    info.append("page %d: %s %s, %s" % (i, what, token,
                                                        accept_note(accepted, key)))
                else:
                    review.append("page %d: %s %s; purpose ambiguous. Record --accept "
                                  "'pdf|citation|TOKEN|REVIEWER|REASON' or correct the source"
                                  % (i, what, visible_snippet(token, 0, len(token), 0)))
            if UTM_CHATGPT.search(text):
                traces.append("page %d: %s in the page text, a ChatGPT "
                              "tracking parameter; correct the source and regenerate"
                              % (i, utm_found(text)))
            for annot in (page.get("/Annots") or []):
                try:
                    obj = annot.get_object()
                    action = obj.get("/A")
                    uri = action.get_object().get("/URI") if action is not None else None
                except Exception:
                    uri = None
                if uri and UTM_CHATGPT.search(str(uri)):
                    traces.append("page %d: link target %s carries %s, a "
                                  "ChatGPT tracking parameter; correct the source and "
                                  "regenerate" % (i, uri, utm_found(str(uri))))
        out.append("page text and link targets of %d page(s) inspected for citation tokens and "
                   "the ChatGPT tracking parameter" % checked)
    except Exception as e:
        out.append("page text and link targets could not be fully inspected for citation tokens "
                   "(%s); %d page(s) read" % (e, checked))


def scan_text_file(path):
    """Visible-content notes only. A text file carries no package metadata."""
    text = open(path, encoding="utf-8", errors="replace").read()
    kw, lp = markers(text)
    out = ["tool name appears in the visible text: " + k for k in kw]
    out += ["path-like string in the visible text: " + p for p in lp]
    residue = sorted({m.group(0).lower() for m in EXTENSION_RESIDUE.finditer(text)})
    out += ["browser-extension markup left in the text: %s. Remove it in the edit as a "
            "generation artifact (AI Fix rule 10); this script changes nothing" % r
            for r in residue]
    return out


# ---------------------------------------------------------------- main

PACKAGE_MARKERS = (("xlsx", "xl/workbook.xml", "xl/"),
                   ("docx", "word/document.xml", "word/"),
                   ("pptx", "ppt/presentation.xml", "ppt/"))


def detect_package_type(path):
    """What the file actually is, read from its bytes.

    Returns xlsx, docx, pptx, pdf, other or invalid. The extension is a label
    a user can change; the package content is what decides whether the Office
    controls apply, so this is the one authority for that question. Renaming a
    certified Office package must not downgrade what is required of it.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return "invalid"
    if head.startswith(b"%PDF"):
        return "pdf"
    if not head.startswith(b"PK\x03\x04"):
        return "other"
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
    except Exception:
        return "invalid"
    if "[Content_Types].xml" not in names:
        return "other"
    for kind, main_part, prefix in PACKAGE_MARKERS:
        if main_part in names:
            return kind
    for kind, main_part, prefix in PACKAGE_MARKERS:
        if any(n.startswith(prefix) for n in names):
            return kind
    return "other"


OOXML_TYPES = ("xlsx", "docx", "pptx")


def resolved(path):
    """A path reduced to one comparable form: absolute, symlinks followed,
    case normalized where the platform is case insensitive."""
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def same_object(dest, protected):
    """True where writing dest would write protected, or where that cannot be
    ruled out. Existing files are compared by filesystem identity, which
    catches a hard link, a symlink and a second path to the same file. A path
    that does not exist yet is compared in resolved form, which catches a
    relative path, a `..` walk, a symlinked directory and a dangling symlink
    pointing at the protected path."""
    try:
        if os.path.exists(dest) and os.path.exists(protected):
            if os.path.samefile(dest, protected):
                return True
        return resolved(dest) == resolved(protected)
    except OSError:
        return True


def write_collision(dest, protected):
    """The first protected file dest would overwrite, as (label, path), or None.
    protected is a list of (label, path); empty paths are skipped."""
    for label, path in protected:
        if path and same_object(dest, path):
            return label, path
    return None


def refuse_log(dest, hit):
    """Report an unsafe log destination without writing anything there."""
    msg = ("refused: the log destination %s is the protected %s file (%s), or cannot be "
           "shown to be separate from it. Nothing was written and no certification is "
           "issued. Pass --log with a separate path." % (dest, hit[0], hit[1]))
    print(msg)
    sys.stderr.write(msg + "\n")
    return 2


def validate_output_destination(source, baseline, output, extra=()):
    """Refuse an output that is the source or the baseline.

    The source and the pre-edit baseline are immutable protected inputs. The
    candidate has to be a separate filesystem object, and nothing is ever
    restored after an accidental overwrite, so this runs before the
    destination is opened.

    Identity is checked two ways, because comparing names is not enough. Where
    the destination already exists, the filesystem's own notion of identity is
    used, which catches a hard link as well as a symlink or a second path to
    the same file. Where it does not yet exist, the resolved absolute paths are
    compared, which catches a relative path, a `..` walk and a symlinked
    directory. Where identity cannot be established, the operation is refused
    rather than risked.

    Returns (ok, reason).
    """
    src_type = detect_package_type(source) if source else "other"
    if src_type in OOXML_TYPES:
        want = "." + src_type
        got = os.path.splitext(output)[1].lower()
        if got != want:
            return False, ("%s source requires a %s output candidate; the requested "
                           "destination is %s. The candidate keeps the source's package "
                           "type, and the output is not silently renamed."
                           % (src_type.upper(), want, got or "an extensionless path"))
    for label, protected in (("source", source), ("baseline", baseline)) + tuple(extra):
        if not protected:
            continue
        try:
            if os.path.exists(output) and os.path.exists(protected):
                if os.path.samefile(output, protected):
                    return False, ("the output destination is the protected %s file (%s). "
                                   "Write the cleaned candidate to a separate file."
                                   % (label, protected))
            if resolved(output) == resolved(protected):
                return False, ("the output destination resolves to the protected %s file "
                               "(%s). Write the cleaned candidate to a separate file."
                               % (label, protected))
        except OSError as e:
            return False, ("the output destination cannot be compared with the protected %s "
                           "file safely (%s), so nothing was written." % (label, e))
    return True, ""


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


CERT_FIELDS = {
    "deliverable": re.compile(r"^- Final deliverable: (.+?)\s*$", re.M),
    "final_sha": re.compile(r"^- Final SHA-256: ([0-9a-fA-F]{64})\s*$", re.M),
    "baseline": re.compile(r"^- Baseline: (.+?)\s*$", re.M),
    "baseline_sha": re.compile(r"^- Baseline SHA-256: ([0-9a-fA-F]{64})\s*$", re.M),
    "verification": re.compile(r"^- Final verification: (PASS WITH INFORMATIONAL FINDINGS"
                               r"|PASS|REVIEW REQUIRED|FAIL)\s*$", re.M),
}


def read_certificate(path):
    """Read the certification record, by explicitly defined fields only.

    Nothing is inferred and nothing is reconstructed from the files at hand.
    A field that is absent, malformed or not a 64-character hexadecimal hash
    makes the record unusable.
    """
    if not path:
        return None, "no certification record was supplied"
    if not os.path.exists(path):
        return None, "the certification record %s does not exist" % path
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except Exception as e:
        return None, "the certification record cannot be read (%s)" % e
    out = {}
    for name, rx in CERT_FIELDS.items():
        m = rx.search(text)
        if not m:
            return None, "the certification record has no usable %s field" % name.replace(
                "_", " ")
        out[name] = m.group(1)
    out["final_sha"] = out["final_sha"].lower()
    out["baseline_sha"] = out["baseline_sha"].lower()
    if out["verification"] not in (OUTCOME_PASS, OUTCOME_INFO):
        return None, "the certification record does not record a pass"
    return out, ""


def certification_block(dest, baseline, passed, note="", modified="No", expect=None,
                        label=None):
    """The record that ties a verdict to one exact file.

    The hash is taken after the final scan, from the file on disk, so what was
    verified and what is delivered cannot drift apart. The modified state comes
    from the same hash comparison that decides whether the certificate holds,
    so the block can never say No while the run says the file has changed.
    """
    current = file_sha256(dest) if os.path.exists(dest) else "no file"
    baseline_hash = (file_sha256(baseline)
                     if baseline and os.path.exists(baseline) else "none")
    lines = ["", "## Final deliverable", "",
             "- Final deliverable: %s" % os.path.basename(dest),
             "- Final SHA-256: %s" % current,
             "- Baseline: %s" % (os.path.basename(baseline) if baseline else "none supplied"),
             "- Baseline SHA-256: %s" % baseline_hash,
             "- Final verification: %s" % (label if label and is_pass(label) == passed
                                           else ("PASS" if passed else "FAIL")),
             "- Modified after final verification: %s" % modified]
    if expect and expect != current:
        lines += ["- SHA-256 recorded at verification: %s" % expect,
                  "- SHA-256 of the file now: %s" % current]
    if note:
        lines.append("- Note: %s" % note)
    if not passed:
        lines += ["",
                  "This file is NOT certified. Do not describe it as clean, sanitized or "
                  "ready for delivery, and do not deliver it as a hygiene pass."]
    else:
        lines += ["",
                  "Deliver this exact file. Do not reopen and save it, rewrite its package, "
                  "regenerate it or run any tool that mutates it. Read-only inspection is "
                  "permitted. Any change to the SHA-256 above invalidates this certification "
                  "and the final scan must be run again."]
    return lines


def recertify(path, expect, baseline, accepted, matched, certificate=None):
    """Re-check one exact file against the certification issued for it.

    Two fingerprints bind the check. The deliverable must still be the file
    whose hash the certificate records, and the baseline offered now must be
    the same bytes as the baseline that was used when the certificate was
    issued. Identity is the recorded hash, not a path and not a file name, so
    a renamed copy of the genuine baseline is accepted and a copy of the
    candidate is not.
    """
    log = ["# Metadata hygiene log", "", "File: %s" % os.path.basename(path), "",
           "## Recertification", ""]
    if not os.path.exists(path):
        log.append("- the file named for delivery does not exist")
        return 2, log, None, "Unknown"
    digest = file_sha256(path)
    ext = os.path.splitext(path)[1].lower()
    ptype = detect_package_type(path)
    is_office = ptype in OOXML_TYPES
    if is_office:
        log.append("- Package type read from the file content: %s" % ptype)
        if ext != "." + ptype:
            log.append("- Note: the extension %s does not match the package type. The content "
                       "decides which controls apply, so the %s rules are enforced in full."
                       % (ext or "(none)", ptype.upper()))
    cert, why = read_certificate(certificate)
    if is_office and cert is None:
        log.append("- SHA-256 now: %s" % digest)
        log.append("- FAIL, certification is impossible: %s. A supported Office file is "
                   "recertified against the record issued when it was certified, and that "
                   "record is not reconstructed from the files at hand." % why)
        return 2, log, digest, "Unknown"
    if cert is not None:
        if expect and expect.lower() != cert["final_sha"]:
            log.append("- FAIL, the hash given on the command line does not match the one in "
                       "the certification record.")
            return 2, log, digest, "Unknown"
        expect = cert["final_sha"]
        log.append("- Certification record: %s" % os.path.basename(certificate))
        log.append("- Baseline SHA-256 recorded at certification: %s" % cert["baseline_sha"])
    bparts = None
    log.append("- SHA-256 now: %s" % digest)
    log.append("- SHA-256 recorded at verification: %s" % (expect or "none supplied"))
    if not expect:
        modified = "Unknown"
    elif digest == expect:
        modified = "No"
    else:
        modified = "Yes"
    if modified == "Yes":
        log += ["- FAIL, the file has changed since it was verified, so that certification is "
                "void. Run the hygiene clean and the final scan again before delivering."]
        return 2, log, digest, modified
    try:
        parts = read_parts(path)
    except Exception as e:
        log.append("- FAIL, the file will not open as a package: %s" % e)
        return 2, log, digest, modified

    # The baseline is mandatory for an Office package, and the requirement does
    # not depend on what the file happens to contain. A file with no comment,
    # note, VML or tracked item still needs the baseline, because without it
    # the run cannot establish that none was lost before it arrived here.
    if is_office:
        if not baseline:
            log.append("- FAIL, certification is impossible: the mandatory baseline was not "
                       "supplied. A supported Office file is never recertified without the "
                       "pre-edit baseline, whatever the file contains.")
            return 2, log, digest, modified
        if not os.path.exists(baseline):
            log.append("- FAIL, certification is impossible: the mandatory baseline %s does "
                       "not exist." % baseline)
            return 2, log, digest, modified
        try:
            bparts = read_parts(baseline)
        except Exception as e:
            log.append("- FAIL, certification is impossible: the mandatory baseline cannot be "
                       "read as a package (%s)." % e)
            return 2, log, digest, modified
        defects = package_defects(bparts)
        if defects:
            log.append("- FAIL, certification is impossible: the mandatory baseline is not a "
                       "usable Office package (%s)." % "; ".join(defects))
            return 2, log, digest, modified
        baseline_digest = file_sha256(baseline)
        log.append("- Baseline SHA-256 now: %s" % baseline_digest)
        if cert is not None and baseline_digest != cert["baseline_sha"]:
            log.append("- FAIL, the supplied baseline does not match the certified baseline "
                       "fingerprint. It is not the pre-edit baseline this file was certified "
                       "against. A cleaned candidate, or a copy of one, is never a baseline.")
            log.append("  - recorded at certification: %s" % cert["baseline_sha"])
            log.append("  - supplied now: %s" % baseline_digest)
            return 2, log, digest, modified
    inv = baseline_inventory(baseline) if baseline else None
    if is_office and inv is None:
        log.append("- FAIL, certification is impossible: the mandatory baseline cannot be used "
                   "for the required integrity checks. The reason is printed above.")
        return 2, log, digest, modified
    comments = collect_comments(parts)
    decisions = [(c,) + comment_verdict(c, inv) for c in comments]
    findings = classify(parts, accepted, matched, bparts)
    fails = failing_items(findings)
    fails += [("annotation", c["part"], w) for c, v, w in decisions
              if v in ("remove", "restore", "relocated", "report-manual", "keep-unverified")]
    if inv is not None:
        present = {comment_key(c) for c in comments}
        for key in sorted(inv["keys"] - present):
            fails.append(("annotation", key[1], "an annotation in the pre-edit inventory is "
                                                "missing or altered"))
    elif comments:
        fails.append(("annotation", os.path.basename(path),
                      "no pre-edit inventory supplied, so the annotation state cannot be "
                      "certified"))
    label = outcome(findings, failed=any(f[0] == "annotation" for f in fails))
    log += ["- " + ("no package-level item and no annotation discrepancy remains"
                    if not fails else "%s, %d unresolved item(s)" % (label, len(fails)))]
    log += ["  - [%s] %s: %s" % f for f in fails[:8]]
    infos = [f for f in findings if f[0] in INFO_KINDS]
    if infos:
        log += ["- informational findings, disclosed and not a failure:"]
        log += ["  - [%s] %s: %s" % f for f in infos[:8]]
    log += ["- Outcome: %s" % label]
    return (0 if is_pass(label) else 2), log, digest, modified


def main():
    ap = argparse.ArgumentParser(description="Package and metadata hygiene, AI Fix")
    ap.add_argument("path")
    ap.add_argument("--clean", action="store_true", help="write a cleaned copy")
    ap.add_argument("--recertify", action="store_true",
                    help="re-check one exact file before delivering it. With --expect-sha it "
                         "also confirms the file has not changed since it was verified.")
    ap.add_argument("--expect-sha", metavar="HASH",
                    help="the SHA-256 recorded in the hygiene report for this file")
    ap.add_argument("--certificate", metavar="REPORT",
                    help="the hygiene report issued when this file was certified. Required to "
                         "recertify a supported Office file: it carries the deliverable's hash "
                         "and the hash of the pre-edit baseline the file was certified "
                         "against, and both are checked.")
    ap.add_argument("--baseline", metavar="FILE",
                    help="the file as it was before this work started. Any comment present in "
                         "the deliverable but not in the baseline was added after it and is "
                         "removed; a comment present in both is pre-existing and is kept.")
    ap.add_argument("--accept", action="append", default=[],
                    metavar="PART|FIELD|VALUE|REVIEWER|REASON",
                    help="record a reviewed decision that one exact value in one named field "
                         "of one named part is legitimate, for example "
                         "'docProps/custom.xml|ProjectName|OpenAI Headquarters|A. Preparer|"
                         "client name, not provenance'. Use pdf as the part for a PDF field. "
                         "Repeatable. It resolves an ambiguous tool name only: it can never "
                         "clear a local path, an integration key, an add-in, a structural "
                         "defect, a signature or an indeterminate reading, it deletes nothing, "
                         "and it never applies beyond that exact value.")
    ap.add_argument("-o", "--output")
    ap.add_argument("--log", metavar="FILE",
                    help="where to write this run's report. Default: the input's name with "
                         "_metahygiene.md. The report is never written over the source, the "
                         "baseline, the certificate, the candidate or the file being "
                         "recertified; an unsafe destination is refused with nothing written.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--blank-author", action="store_true",
                   help="blank creator, lastModifiedBy, Company and Manager")
    g.add_argument("--author",
                   help="set creator and lastModifiedBy only; Company and Manager are left "
                        "exactly as found")
    a = ap.parse_args()

    recorded = time.strftime("%d-%b-%y %H:%M", time.localtime())
    accepted, bad_accept, matched = {}, [], set()
    for entry in a.accept:
        bits = entry.split("|")
        if len(bits) != 5 or not all(b.strip() for b in bits):
            bad_accept.append(entry)
            continue
        accepted[(bits[0].strip(), bits[1].strip(), bits[2].strip())] = {
            "reviewer": bits[3].strip(), "reason": bits[4].strip(), "recorded": recorded}
    if bad_accept:
        print("ignoring malformed --accept, expected PART|FIELD|VALUE|REVIEWER|REASON: "
              + "; ".join(bad_accept))

    if a.recertify:
        out_log = a.log or (os.path.splitext(a.path)[0] + "_metahygiene.md")
        hit = write_collision(out_log, [("file being recertified", a.path),
                                        ("baseline", a.baseline),
                                        ("certificate", a.certificate)])
        if hit:
            return refuse_log(out_log, hit)
        status, log, digest, modified = recertify(a.path, a.expect_sha, a.baseline,
                                                  accepted, matched, a.certificate)
        label = next((x[len("- Outcome: "):] for x in reversed(log)
                      if x.startswith("- Outcome: ")),
                     OUTCOME_PASS if status == 0 else OUTCOME_FAIL)
        log += certification_block(a.path, a.baseline, status == 0,
                                   "re-checked before delivery", modified, a.expect_sha,
                                   label)
        with open(out_log, "w", encoding="utf-8") as f:
            f.write("\n".join(log) + "\n")
        print("recertification: %s" % label)
        if digest:
            print("SHA-256: %s" % digest)
        print("log: %s" % out_log)
        return status

    src, ext = a.path, os.path.splitext(a.path)[1].lower()
    stem = os.path.splitext(src)[0]
    # Every write destination is settled and checked before anything is read
    # or written: the source, the baseline, a supplied certificate and the
    # candidate are all protected from the report, and the report and the
    # candidate may not be the same file.
    dest = (a.output or (stem + "_clean" + ext)) if a.clean else None
    out_log = a.log or (stem + "_metahygiene.md")
    hit = write_collision(out_log, [("source", src), ("baseline", a.baseline),
                                    ("certificate", a.certificate), ("candidate", dest)])
    if hit:
        return refuse_log(out_log, hit)
    log = ["# Metadata hygiene log", "", "File: %s" % os.path.basename(src), ""]
    status = 0
    assistant_seen = False
    generator_seen = False

    # What the file is decides which branch runs, and that comes from its
    # bytes. An Office package renamed .md, .bin or .tmp is still an Office
    # package and gets the Office scan and clean; a text file named .xlsx is
    # not one and never gets them. The extension is only used afterwards, for
    # naming the candidate.
    ptype = detect_package_type(src)
    if ptype in OOXML_TYPES and ext != "." + ptype:
        log.append("Package type read from the file content: %s. The extension %s does not "
                   "match, and the content decides which controls apply."
                   % (ptype, ext or "(none)"))
        log.append("")

    if ptype not in OOXML_TYPES and ptype != "pdf" and ext in SUPPORTED_TEXT:
        hits = scan_text_file(src)
        assistant_seen = mentions_writing_assistant(hits)
        log += ["Type: plain text. No OOXML package and no document properties, so there is "
                "nothing to sanitize and no hygiene result to give.", "",
                "Visible-content notes, informational only:", ""]
        log += ["- " + h for h in hits] or ["- nothing found"]
        log += ["", "A tool name in a text file is visible content, not metadata residue. It "
                    "may be the subject matter, so it is never treated as a hygiene failure "
                    "and nothing is changed."]
        # Rev37 / Rev 3.20: citation tokens, the tracking parameter and hidden
        # Unicode are generation artifacts, not tool names, and are classified.
        text = open(src, encoding="utf-8", errors="replace").read()
        base_text = None
        if (a.baseline and os.path.exists(a.baseline)
                and detect_package_type(a.baseline) not in OOXML_TYPES + ("pdf",)):
            base_text = open(a.baseline, encoding="utf-8", errors="replace").read()
        tf = text_trace_findings(text, accepted, matched, base_text)
        generator_seen = mentions_generator(hits)
        label = outcome(tf)
        log += ["", "## Trace inspection", "",
                "Citation tokens, the ChatGPT tracking parameter and hidden Unicode characters. "
                "Read only; nothing is changed.", ""]
        log += ["- [%s] %s: %s" % f for f in tf] or ["- nothing found"]
        log += ["", "Trace inspection result: %s" % label]
        print("trace inspection result: %s" % label)
        status = 0 if is_pass(label) else 2
    elif ptype == "pdf":
        hits, traces, incomplete, review, info = scan_pdf(src, accepted, matched)
        assistant_seen = mentions_writing_assistant(hits + traces + review)
        generator_seen = mentions_generator(hits + traces + review)
        log += ["Type: PDF. Inspection only, no content or metadata written.", ""]
        log += ["- " + h for h in hits] or ["- nothing found"]
        log += ["", "PDF metadata sanitation was NOT performed by this script. Where it is "
                    "required, carry it out with a PDF tool and record it."]
        if review:
            log += ["", "Reported for a decision, a descriptive field carrying a tool name is "
                        "not by itself provenance. Record a decision with --accept "
                        "'pdf|FIELD|VALUE|REVIEWER|REASON' where the name is legitimate:", ""]
            log += ["- " + r for r in review]
        if info:
            log += ["", "Informational findings, disclosed and not a failure:", ""]
            log += ["- " + i for i in info]
        if traces:
            log += ["", "Inspection result: FAIL, a confirmed tool, generator or local-path trace "
                        "in a provenance field, or a confirmed generation artifact. The file is "
                        "not cleared for delivery until it is resolved by hand or the source is "
                        "corrected and the PDF regenerated.", ""]
            log += ["- " + t for t in traces]
            print("inspection result: FAIL, confirmed metadata trace or generation artifact")
            status = 2
        elif review:
            log += ["", "Inspection result: REVIEW REQUIRED, a decision is needed on the "
                        "finding(s) listed above. No provenance trace was found."]
            print("inspection result: REVIEW REQUIRED, a decision is needed first")
            status = 2
        elif incomplete:
            log += ["", "Inspection result: INDETERMINATE, not a pass. The inspection could not "
                        "be completed, so the absence of a trace proves nothing:", ""]
            log += ["- " + i for i in incomplete]
            log += ["", "Inspect this file with a PDF parser before issuing it, and record the "
                        "result."]
            print("inspection result: FAIL, INDETERMINATE, inspection could not be completed")
            status = 2
        else:
            label = OUTCOME_INFO if info else OUTCOME_PASS
            log += ["", "Inspection result: %s, no tool or local-path trace in the metadata, "
                        "read with a PDF parser." % label]
            print("inspection result: %s" % label)
    elif ptype in OOXML_TYPES:
        try:
            parts = read_parts(src)
        except Exception as e:
            print("cannot read package: %s" % e)
            return 2

        ns_defects = namespace_defects(parts)
        if ns_defects:
            print("namespace preservation: FAIL; no cleaned package written")
            for defect in ns_defects:
                print("- " + defect)
            return 2

        inv = None
        if a.baseline:
            inv = baseline_inventory(a.baseline)
            if inv is None:
                print("cannot read the baseline file, no annotation inventory is available")

        base_parts = None
        if a.baseline:
            try:
                base_parts = read_parts(a.baseline)
            except Exception:
                base_parts = None

        comments = collect_comments(parts)
        comment_decisions = [(c,) + comment_verdict(c, inv) for c in comments]

        sigs = signature_parts(parts)
        findings = classify(parts, accepted, matched, base_parts)
        unnecessary, preserved = classify_web_extensions(parts)
        log += ["Type: Office Open XML package, %d parts." % len(parts), ""]
        if accepted:
            log += ["## Reviewed and accepted", "",
                    "Recorded by the operator with --accept. Each entry resolves one exact "
                    "value in one named field of one named part, deletes nothing, and cannot "
                    "clear a local path, an integration key, an add-in or a structural "
                    "defect.", ""]
            for key in sorted(accepted):
                e = accepted[key]
                log.append("- %s | %s | %s | reviewer %s | %s | recorded %s"
                           % (key[0], key[1], key[2], e["reviewer"], e["reason"], e["recorded"]))
            log.append("")
        if comments:
            log += ["## Comments", "",
                    "Pre-edit inventory: %s" % (a.baseline if inv is not None
                                                else "none supplied, so every annotation is "
                                                     "preserved and this run cannot certify "
                                                     "that none was created"), ""]
            for c, verdict, why in comment_decisions:
                log.append("- [%s] %s%s, author %s: %s"
                           % (verdict, c["part"] + " ", c.get("ref") or "",
                              c.get("author") or "none", why))
            log.append("")
        assistant_seen = mentions_writing_assistant("%s %s %s" % f for f in findings)
        generator_seen = mentions_generator("%s %s %s" % f for f in findings)
        log += ["## Inspection", ""]
        log += ["- [%s] %s: %s" % f for f in findings] or ["- nothing found"]

        # Rev34: report-only inspection of embedded image metadata and of
        # revisions and hidden content. It reads the package, changes nothing
        # and does not affect the hygiene result.
        try:
            import inspect_content
            images = inspect_content.inspect_images(parts)
            revisions, rev_problems = inspect_content.inspect_revisions(parts, ptype)
            log += inspect_content.report_lines(images, revisions, rev_problems,
                                                comments_present=bool(comments))
            print(inspect_content.summary(images, revisions, rev_problems))
        except Exception as exc:      # never let a failed inspection read as clean
            log += ["", "## Pre-delivery review findings (report only)", "",
                    "- INSPECTION INCOMPLETE: the report-only inspection could not run (%s); "
                    "embedded image metadata, revisions and hidden content were not inspected"
                    % exc]
            print("review findings (report only): inspection could not run: %s" % exc)

        if sigs:
            log += ["", "## Refused", "",
                    "- the package carries a digital signature (%s). Rebuilding it invalidates "
                    "the signature, so no cleaning was performed. Remove the signature, clean, "
                    "then re-sign; or clean the unsigned source and re-issue." % ", ".join(sigs)]
            print("digitally signed package, cleaning refused")
            status = 2
        elif a.clean:
            # The destination is settled and checked before any work touches
            # it: the failure has to happen before mutation, not after.
            allowed, why = validate_output_destination(
                src, a.baseline, dest, (("certificate", a.certificate), ("report", out_log)))
            if not allowed:
                log += ["", "## Stopped before writing", "",
                        "- FAIL, %s Nothing was written. The source and the baseline are "
                        "untouched and no certification is issued." % why]
                print("stopped before writing: %s" % why)
                with open(out_log, "w", encoding="utf-8") as f:
                    f.write("\n".join(log) + "\n")
                print("log: %s" % out_log)
                return 2
            mode = "blank" if a.blank_author else ("set" if a.author else None)
            if mode == "set":
                # An explicit --author is the reviewer's decision on those two
                # fields, so the value it writes is accepted for them, unless
                # the value is itself a local path, which no decision clears.
                if not path_hits_in_field(a.author):
                    for t in AUTHOR_TAGS:
                        accepted.setdefault(("docProps/core.xml", t, a.author),
                                            {"reviewer": "--author", "recorded": recorded,
                                             "reason": "author set explicitly on the command "
                                                       "line"})
            comment_touched = set()
            before_parts = set(parts)
            cleaned, actions, removed, suspicious, reported = clean_ooxml(
                parts, unnecessary, mode, a.author, accepted,
                comment_decisions, comment_touched, inv)
            comment_removed = (before_parts - set(cleaned)) - removed
            comment_added = set(cleaned) - before_parts
            ns_defects = namespace_defects(cleaned, parts)
            if ns_defects:
                print("namespace preservation: FAIL; no cleaned package written")
                for defect in ns_defects:
                    print("- " + defect)
                return 2
            write_package(cleaned, dest)
            detail = {}
            ok, checks, residue = verify_package(dest, parts, removed, preserved,
                                                 suspicious, mode, a.author, accepted, matched,
                                                 comment_touched, inv, comment_removed,
                                                 comment_added, base_parts, detail)
            log += ["", "## Removed", ""]
            log += ["- " + x for x in actions] or ["- nothing removed"]
            log += ["", "## Retained deliberately", "",
                    "- every part not listed above, including formulas, defined names, "
                    "validation, conditional formatting, charts, tables, pivot structures, "
                    "comments, external links, custom XML, embedded objects and "
                    "document-control properties"]
            if preserved:
                log.append("- Office web extension(s) carrying no marker: " + ", ".join(preserved))
            for r in reported:
                log.append("- " + r)
            log += ["", "## Package verification performed", ""]
            log += ["- " + c for c in checks]
            moved = [c for c, v, w in comment_decisions if v == "relocated"]
            if moved:
                ok = False
                log += ["", "%d comment(s) are attached to different text than the pre-edit "
                            "inventory records. Nothing was moved and nothing was removed; "
                            "resolve each by hand:" % len(moved)]
                log += ["- %s comment %s" % (c["part"], c.get("id")) for c in moved]
            manual = [c for c, v, w in comment_decisions if v == "report-manual"]
            if manual:
                ok = False
                log += ["", "%d PowerPoint comment(s) are absent from the inventory. They were "
                            "preserved because slide comment identity is not implemented; "
                            "remove them by hand." % len(manual)]
            unverified = [c for c, v, w in comment_decisions if v == "keep-unverified"]
            if unverified:
                log += ["", "%d annotation(s) were preserved without a pre-edit inventory. "
                            "Nothing was guessed at and nothing was removed. Supply --baseline "
                            "to certify that none was created during processing."
                            % len(unverified)]
            failed = (not detail.get("struct_ok", False) or bool(moved) or bool(manual)
                      or not os.path.exists(dest))
            label = outcome(detail.get("final", []), failed=failed)
            ok = is_pass(label)
            log += ["", "Hygiene result: %s" % (label if ok else label + ", do not issue")]
            if residue:
                log.append("Reason: an item classified as package-level residue, a confirmed "
                           "artifact or a finding awaiting review remains.")
            if not os.path.exists(dest):
                log.append("Reason: the cleaned candidate was not written, so there is nothing "
                           "to certify.")
            log += certification_block(dest, a.baseline, ok, label=label)
            print("written: %s" % dest)
            print("hygiene result: %s" % label)
            if ok:
                print("Final verified deliverable: %s" % os.path.basename(dest))
                print("Final hygiene verification: %s" % label)
                print("SHA-256: %s" % file_sha256(dest))
            else:
                print("not certified: do not deliver %s as clean" % os.path.basename(dest))
            status = 0 if ok else 2
        else:
            fails = failing_items(findings)
            fails += [("report", c["part"], "annotation preserved, %s" % w)
                      for c, v, w in comment_decisions
                      if v in ("keep-unverified", "report-manual")]
            fails += [("annotation", c["part"], w) for c, v, w in comment_decisions
                      if v in ("remove", "restore", "relocated", "report-manual")]
            if inv is not None:
                present = {comment_key(c) for c in comments}
                for key in sorted(inv["keys"] - present):
                    fails.append(("annotation", key[1],
                                  "an annotation in the pre-edit inventory (%s %s) is missing "
                                  "or altered in this file" % (key[0], key[2])))
            if inv is None:
                fails.append(("annotation", os.path.basename(src),
                              "no pre-edit inventory supplied, so this scan cannot certify the "
                              "annotation state"))
            for kind, part, why in [f for f in fails if f[0] == "annotation"]:
                log.append("- [annotation] %s: %s" % (part, why))
            label = outcome(findings, failed=any(f[0] in ("annotation", "report")
                                                 for f in fails))
            log += ["", "Scan only. Nothing was written. Re-run with --clean to act."]
            log += ["", "Scan result: %s"
                    % ("%s, no package-level tool or path item found" % label if not fails
                       else "%s, %d item(s) found" % (label, len(fails)))]
            if fails:
                print("scan result: %s, %d item(s) found" % (label, len(fails)))
            else:
                print("scan result: %s" % label)
            print("not certified: a scan is not a hygiene pass and writes no deliverable")
            status = 0 if is_pass(label) else 2
    elif ptype == "invalid":
        log += ["Type: the file begins like a zip package but will not open as one, so it "
                "cannot be inspected. Nothing was scanned and nothing was written.", ""]
        print("unreadable package: %s" % src)
        status = 2
    else:
        print("unsupported file type: %s (content reads as %s)" % (ext, ptype))
        return 2

    unmatched = sorted(set(accepted) - matched)
    if unmatched:
        log += ["", "## Unmatched acceptance entries", "",
                "Recorded with --accept but matching no current finding. Check the part, "
                "field and exact value.", ""]
        log += ["- %s | %s | %s" % k for k in unmatched]
        print("warning: %d --accept entr(ies) matched no finding" % len(unmatched))

    # Driven by the findings themselves, never by the log text, so a file or
    # baseline merely named after the tool draws no note about findings that
    # were never made.
    if assistant_seen:
        log += ["", "## Classification of the writing-assistant findings", "",
                WRITING_ASSISTANT_NOTE]
    if generator_seen:
        log += ["", "## Classification of the generator-library findings", "",
                GENERATOR_NOTE]

    with open(out_log, "w", encoding="utf-8") as f:
        f.write("\n".join(log) + "\n")
    print("log: %s" % out_log)
    return status


if __name__ == "__main__":
    try:
        sys.exit(main())
    except NamespacePreservationError as exc:
        print("namespace preservation: FAIL: %s" % exc)
        sys.exit(2)
