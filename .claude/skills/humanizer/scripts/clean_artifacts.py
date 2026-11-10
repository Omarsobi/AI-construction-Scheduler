#!/usr/bin/env python3
"""Detect, and on request remove, AI citation artifacts and ChatGPT link tracking.

An edit-step tool (AI Fix Rev37, corrected at Rev39, Rev40 and Rev41,
workflow step 4). It reads document text and
hyperlink targets, including the OOXML relationship parts that ordinary text
extraction does not read, and reports:

  - generation-only citation tokens: ChatGPT contentReference and oaicite
    tokens, turn0search-style citation handles, their private-use wrappers
    and the 【n†source】 markers;
  - residues whose purpose is ambiguous: an incomplete handle, a stray wrapper
    character, or a confirmed token standing between quotation marks, which may
    be the subject of the text rather than an artifact;
  - the exact tracking parameter utm_source=chatgpt.com in a hyperlink target,
    a field-code link, a Markdown link or a URL in the text.

Usage
    python clean_artifacts.py FILE                    # report only, writes nothing
    python clean_artifacts.py FILE --clean -o OUT     # write a corrected copy
    python clean_artifacts.py FILE --clean -o OUT --log report.md

With --clean, and only then, a separate copy is written in which:
  - every confirmed token wholly inside one text node is removed, with the
    spaces directly before it in that node;
  - utm_source=chatgpt.com is removed from each affected URL, keeping the
    destination, every other parameter in its order and spelling, the fragment
    and a valid URL; each corrected link is recorded with its original and
    final value.
Nothing else changes. An ambiguous residue, a token split across runs, and
anything inside a formula or a tracked change is left exactly as it is and
flagged for review. In a Markdown file (.md, .markdown), fenced code blocks
(``` or ~~~, including inside a blockquote), indented code blocks and inline
code spans, including spans that cross a line break, are reproduced exactly;
a token or the tracking parameter inside one is flagged for review, never
removed (Rev39, corrected at Rev40 to read code across lines). Hidden
Unicode characters are reported by diff_text.py and
metadata_hygiene.py and are never touched here. The source is never
overwritten: an output that is the source, or resolves to it, is refused with
nothing written. The --log destination is checked in every mode, before
anything is written, against the source and, with --clean, against the actual
output, whether named with -o or defaulted, by filesystem identity and in
resolved form, so a hard link, a symbolic link or a second path to either is
refused with nothing written (Rev39). A digitally signed Office package is
reported and never rewritten: --clean refuses it before writing, since any
rewrite would invalidate the signature (Rev39).

Supports .docx, .pptx, .xlsx (content read from the package, not the file
name), and .md, .txt. A PDF is reported by metadata_hygiene.py and is not
edited.

Detection and the URL rule are the ones metadata_hygiene.py uses for
certification, imported from it, so the two cannot disagree.

Exit status 0 where nothing is found (report) or nothing is left (clean); 2
where a finding remains, the input cannot be read, or the run is refused.
Standard library only.
"""

import argparse
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
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metadata_hygiene as mh  # noqa: E402

TEXT_EXT = (".md", ".markdown", ".txt")
MARKDOWN_EXT = (".md", ".markdown")


def same_file(a, b):
    try:
        if os.path.exists(a) and os.path.exists(b) and os.path.samefile(a, b):
            return True
        return mh.resolved(a) == mh.resolved(b)
    except OSError:
        return True


# ---------------------------------------------------------------- text edits

def article(noun):
    return "an" if noun[:1].lower() in "aeiou" else "a"


def clean_string(s, where, changes, flags, protected=None):
    """Remove confirmed tokens and the tracking parameter from one string.
    Returns the new string. Ambiguous hits are added to flags, unchanged."""
    hits = mh.citation_hits(s)
    if protected:
        for _, _, token, what, _ in hits:
            flags.append("%s: %s %r inside %s %s, not edited"
                         % (where, what, token, article(protected), protected))
        if mh.UTM_CHATGPT.search(s):
            flags.append("%s: %s inside %s %s, not edited"
                         % (where, mh.utm_found(s), article(protected), protected))
        return s
    out = s
    for start, end, token, what, confirmed in sorted(hits, reverse=True):
        if not confirmed:
            flags.append("%s: %s %r, purpose ambiguous, left for review" % (where, what, token))
            continue
        lo = start
        while lo > 0 and out[lo - 1] in " \t":
            lo -= 1
        out = out[:lo] + out[end:]
        changes.append("%s: removed %s %r" % (where, what, token))
    if mh.UTM_CHATGPT.search(out):
        def fix(m):
            url = m.group(0)
            new, n = mh.strip_chatgpt_utm(url)
            if n:
                changes.append("%s: link corrected, %d tracking pair(s) removed; original %s ; "
                               "final %s" % (where, n, url, new))
            return new
        out = mh.URL_IN_TEXT.sub(fix, out)
        if mh.UTM_CHATGPT.search(out):
            flags.append("%s: %s outside a recognizable URL, left for review"
                         % (where, mh.utm_found(out)))
    return out


MD_FENCE = re.compile(r"^(`{3,}|~{3,})(.*)$")
MD_ATX = re.compile(r"^#{1,6}(?:[ \t]|$)")
MD_THEMATIC = re.compile(r"^([-*_])(?:[ \t]*\1){2,}[ \t]*$")
MD_SETEXT = re.compile(r"^(?:=+|-+)[ \t]*$")
MD_LIST = re.compile(r"^([-+*]|(\d{1,9})[.)])(?= |$)")
# HTML block start conditions 1 to 7 and their end conditions (CommonMark 4.6).
MD_HTML_BLOCK_TAGS = (
    "address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|"
    "details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|"
    "h1|h2|h3|h4|h5|h6|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|"
    "noframes|ol|optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|th|"
    "thead|title|tr|track|ul")
MD_HTML_START = [
    (1, re.compile(r"^<(?:script|pre|style|textarea)(?:\s|>|$)", re.I),
     re.compile(r"</(?:script|pre|style|textarea)>", re.I)),
    (2, re.compile(r"^<!--"), re.compile(r"-->")),
    (3, re.compile(r"^<\?"), re.compile(r"\?>")),
    (4, re.compile(r"^<![A-Za-z]"), re.compile(r">")),
    (5, re.compile(r"^<!\[CDATA\["), re.compile(r"\]\]>")),
    (6, re.compile(r"^</?(?:%s)(?:\s|/?>|$)" % MD_HTML_BLOCK_TAGS, re.I), None),
    (7, re.compile(r"^(?:<[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z_:][\w.:-]*(?:\s*=\s*"
                   r"(?:[^\s\"'=<>`]+|'[^']*'|\"[^\"]*\"))?)*\s*/?>|</[A-Za-z][A-Za-z0-9-]*\s*>)"
                   r"[ \t]*$"), None),
]


def _expand_tabs(line):
    """The line with each tab expanded to the next multiple of four columns,
    which is how CommonMark measures indentation. Used only to classify the
    line; ranges are always taken from the original text."""
    if "\t" not in line:
        return line
    out = []
    for ch in line:
        if ch == "\t":
            out.append(" " * (4 - len(out) % 4))
        else:
            out.append(ch)
    return "".join(out)


def _lead(s):
    return len(s) - len(s.lstrip(" "))


MD_ESCAPABLE = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")


def _code_spans(s):
    """(start, end) of each inline code span in s (CommonMark 6.1). Outside a
    span a backslash escapes the punctuation character after it, so an escaped
    backtick opens nothing; inside a span backslashes are literal. A backtick
    run with no closing run of the same length is literal text."""
    out, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "\\" and i + 1 < n and s[i + 1] in MD_ESCAPABLE:
            i += 2
            continue
        if ch != "`":
            i += 1
            continue
        j = i
        while j < n and s[j] == "`":
            j += 1
        run = j - i
        k = j
        close = -1
        while k < n:
            if s[k] == "`":
                m = k
                while m < n and s[m] == "`":
                    m += 1
                if m - k == run:
                    close = m
                    break
                k = m
            else:
                k += 1
        if close == -1:
            i = j                    # no closing run: the backticks are literal
            continue
        out.append((i, close))
        i = close
    return out


def _html_start(t, interrupting):
    """(type, end pattern) where t starts an HTML block, else None. Type 7
    cannot interrupt a paragraph, including one continued by a lazy line
    (CommonMark 4.6 and 5.1; commonmark.py differs, markdown-it-py agrees)."""
    for kind, start, end in MD_HTML_START:
        if start.match(t) and not (kind == 7 and interrupting):
            return kind, end
    return None


def markdown_code_ranges(text):
    """Character ranges of the code in a Markdown text, as (start, end, label),
    sorted and not overlapping. Rev41 reads the file with the CommonMark block
    structure: block quotes and list items, nested to any depth, are tracked as
    containers, and inside them

      - fenced code blocks (``` or ~~~, closed by a fence of the same
        character and at least the same length, or ended with their
        container or the file);
      - indented code blocks (four columns of indentation beyond the
        container, tabs counted to the next multiple of four), which start
        anywhere a paragraph is not open and never interrupt one;
      - inline code spans, a backtick run to the next run of the same length,
        inside one paragraph or heading, across line breaks, never across
        paragraphs; a backslash-escaped backtick outside a span opens nothing.

    A paragraph keeps lazy continuation lines (CommonMark section 5.1). An
    ordered item interrupts a paragraph only when it starts at 1, and an empty
    item never does (section 5.2); both limits apply only to a paragraph in the
    item's own container, not to a lazy line. HTML blocks of the seven
    CommonMark types are tracked (section 4.6) so that code is neither read
    into nor missed after one; their content is not code and is left to the
    ordinary rules. Disagreements between commonmark.py and markdown-it-py were
    resolved against CommonMark specification 0.31.2."""
    lines = text.split("\n")
    starts, pos = [], 0
    for line in lines:
        starts.append(pos)
        pos += len(line) + 1

    labels = [None] * len(lines)     # block code label per line
    group = [None] * len(lines)      # paragraph or heading id, for inline spans
    containers = []                  # each: ["quote"] or ["item", width, empty, has_content]
    tip = None                       # None, "para", "icode", ("fence", char, length)
    #                                  or ("html", end pattern or None)
    gid = 0

    for i, raw in enumerate(lines):
        s = _expand_tabs(raw)
        p = 0
        blank_line = not s.strip()

        # 1. match the open containers
        matched = 0
        for c in containers:
            rest = s[p:]
            if c[0] == "quote":
                n = _lead(rest)
                if n <= 3 and rest[n:n + 1] == ">":
                    p += n + 1
                    if s[p:p + 1] == " ":
                        p += 1
                    matched += 1
                    continue
                break
            if not rest.strip():
                if c[2] and not c[3]:
                    break            # an item may begin with at most one blank line
                matched += 1
                continue
            if _lead(rest) >= c[1]:
                p += c[1]
                matched += 1
                continue
            break
        all_matched = matched == len(containers)
        rest = s[p:]
        blank = not rest.strip()

        # 2. continue an open code block in a fully matched container
        if all_matched and isinstance(tip, tuple) and tip[0] == "html":
            if tip[1] is None and blank:
                tip = None           # types 6 and 7 end at a blank line
                continue
            if tip[1] is not None and tip[1].search(rest):
                tip = None           # types 1 to 5 end on the line with their end marker
            for c in containers:
                if c[0] == "item":
                    c[3] = True
            continue
        if all_matched and isinstance(tip, tuple):
            n = _lead(rest)
            m = MD_FENCE.match(rest[n:]) if n <= 3 else None
            labels[i] = "fenced code block"
            if m and m.group(1)[0] == tip[1] and len(m.group(1)) >= tip[2] \
                    and not m.group(2).strip():
                tip = None
            for c in containers:
                if c[0] == "item":
                    c[3] = True
            continue
        if all_matched and tip == "icode":
            if blank:
                continue
            if _lead(rest) >= 4:
                labels[i] = "indented code block"
                continue
            tip = None

        # 3. open new containers
        new = []
        para_open = tip == "para"
        while True:
            rest = s[p:]
            n = _lead(rest)
            if n >= 4:
                break
            t = rest[n:]
            if t[:1] == ">":
                p += n + 1
                if s[p:p + 1] == " ":
                    p += 1
                new.append(["quote"])
                continue
            if MD_ATX.match(t) or MD_FENCE.match(t) or MD_THEMATIC.match(t) or \
                    _html_start(t, para_open and not new):
                break
            if MD_SETEXT.match(t) and para_open and not new and all_matched:
                break
            lm = MD_LIST.match(t)
            if lm:
                after = t[lm.end():]
                empty = not after.strip()
                interrupting = para_open and not new and all_matched
                if interrupting and (empty or (lm.group(2) is not None
                                               and int(lm.group(2)) != 1)):
                    break
                sp = _lead(after)
                width = n + lm.end() + (1 if empty or sp >= 5 else sp)
                new.append(["item", width, empty, not empty])
                p = min(p + width, len(s))
                continue
            break
        rest = s[p:]
        n = _lead(rest)
        t = rest[n:]
        blank = not rest.strip()

        # 4. the leaf
        if n >= 4:
            kind = "text" if (para_open and not new) else ("blank" if blank else "icode")
        elif blank:
            kind = "blank"
        elif MD_ATX.match(t):
            kind = "atx"
        elif _html_start(t, para_open and not new):
            kind = "html"
        else:
            fm = MD_FENCE.match(t)
            if fm and not (fm.group(1)[0] == "`" and "`" in fm.group(2)):
                kind = "fence"
            elif MD_SETEXT.match(t) and para_open and not new and all_matched:
                kind = "setext"
            elif MD_THEMATIC.match(t):
                kind = "break"
            else:
                kind = "text"

        lazy = (not all_matched and para_open and not new and kind == "text")
        if not lazy:
            if not all_matched:
                containers = containers[:matched]
                tip = None
            if new:
                containers.extend(new)
                tip = None
        if kind != "blank":
            for c in containers:
                if c[0] == "item":
                    c[3] = True

        if kind == "blank":
            if tip == "para":
                tip = None
        elif kind == "icode":
            labels[i] = "indented code block"
            tip = "icode"
        elif kind == "fence":
            labels[i] = "fenced code block"
            tip = ("fence", fm.group(1)[0], len(fm.group(1)))
        elif kind == "atx":
            gid += 1
            group[i] = gid
            tip = None
        elif kind in ("setext", "break"):
            tip = None
        elif kind == "html":
            ht = _html_start(t, False)
            end = ht[1]
            tip = None if (end is not None and end.search(t)) else ("html", end)
        else:
            if tip == "para":
                group[i] = gid
            else:
                gid += 1
                group[i] = gid
                tip = "para"

    ranges = [(starts[i], starts[i] + len(lines[i]), lab)
              for i, lab in enumerate(labels) if lab]
    i = 0
    while i < len(lines):
        if group[i] is None:
            i += 1
            continue
        j = i
        while j + 1 < len(lines) and group[j + 1] == group[i]:
            j += 1
        a, b = starts[i], starts[j] + len(lines[j])
        for sa, sb in _code_spans(text[a:b]):
            ranges.append((a + sa, a + sb, "code span"))
        i = j + 1
    return sorted(ranges)


def clean_text_file(text, markdown=False):
    """Clean a plain-text file line by line. With markdown, every range that
    markdown_code_ranges() returns is reproduced exactly and any finding in it
    is flagged for review; only the text outside those ranges is cleaned
    (Rev39, corrected at Rev40)."""
    changes, flags = [], []
    lines = text.split("\n")
    ranges = markdown_code_ranges(text) if markdown else []
    out, pos, r = [], 0, 0
    for i, line in enumerate(lines, 1):
        where = "line %d" % i
        a, b = pos, pos + len(line)
        while r < len(ranges) and ranges[r][1] <= a:
            r += 1                   # ranges are sorted and do not overlap
        pieces, cur, k = [], a, r
        while k < len(ranges) and ranges[k][0] < b:
            lo, hi = max(ranges[k][0], a), min(ranges[k][1], b)
            if lo > cur:
                pieces.append(clean_string(text[cur:lo], where, changes, flags))
            pieces.append(clean_string(text[lo:hi], where, changes, flags, ranges[k][2]))
            cur = hi
            k += 1
        if cur < b or not pieces:
            pieces.append(clean_string(text[cur:b], where, changes, flags))
        out.append("".join(pieces))
        pos = b + 1
    return "\n".join(out), changes, flags


# ---------------------------------------------------------------- OOXML edits

def clean_xml_part(name, raw, changes, flags):
    """Edit text nodes, tails and field-code instructions in one part through
    the namespace-preserving parser. Returns new bytes, or None if unchanged."""
    root = mh.parse(raw)
    if root is None:
        flags.append("%s: will not parse as XML, not inspected for editing" % name)
        return None
    before = len(changes)
    counters = {}

    def walk(node, protected, label):
        if not isinstance(node.tag, str):
            return
        local = mh.local_name(node.tag)
        if local in mh.TRACE_BLOCKS and label is None:
            counters[local] = counters.get(local, 0) + 1
            label = "%s %d" % (mh.TRACE_BLOCKS[local], counters[local])
        if local in mh.REVISION_TAGS:
            protected = "tracked change"
        elif local == "f":
            protected = "formula"
        where = "%s %s" % (name, label or local)
        if node.text:
            node.text = clean_string(node.text, where, changes, flags, protected)
        for attr in list(node.attrib):
            # a simple field such as HYPERLINK, and picture alt text
            if mh.local_name(attr) in ("instr", "descr", "title"):
                node.attrib[attr] = clean_string(node.attrib[attr], where + " field",
                                                 changes, flags, protected)
        for child in node:
            walk(child, protected, label)
            if child.tail:
                child.tail = clean_string(child.tail, where, changes, flags, protected)

    walk(root, None, None)
    # A token that only exists across run boundaries cannot be removed safely.
    units = mh.text_units(mh.serialize(root)) or []
    for label, text, protected in units:
        for _, _, token, what, confirmed in mh.citation_hits(text):
            if confirmed and not protected:
                flags.append("%s %s: %s %r is split across runs and was not removed; remove "
                             "it by hand" % (name, label, what, token))
    if len(changes) == before:
        return None
    return mh.serialize(root)


def clean_rels_part(name, raw, changes, flags):
    root = mh.parse(raw)
    if root is None:
        flags.append("%s: will not parse as XML, link targets not inspected" % name)
        return None
    changed = False
    for r in mh.relationships(root):
        target = r.get("Target") or ""
        if not (mh.rel_is_external(r) and mh.UTM_CHATGPT.search(target)):
            continue
        new, n = mh.strip_chatgpt_utm(target)
        if n:
            r.set("Target", new)
            changed = True
            changes.append("%s %s: hyperlink target corrected, %d tracking pair(s) removed; "
                           "original %s ; final %s" % (name, r.get("Id"), n, target, new))
        else:
            flags.append("%s %s: %s in %s could not be removed safely"
                         % (name, r.get("Id"), mh.utm_found(target), target))
    return mh.serialize(root) if changed else None


def clean_package(parts):
    changes, flags, out = [], [], dict(parts)
    for name in sorted(parts):
        low = name.lower()
        try:
            if low.endswith(".rels"):
                new = clean_rels_part(name, parts[name], changes, flags)
            elif name in mh.trace_text_parts(parts):
                new = clean_xml_part(name, parts[name], changes, flags)
            else:
                continue
        except mh.NamespacePreservationError as e:
            flags.append("%s: not edited, the part cannot be rewritten without changing a "
                         "namespace reference (%s)" % (name, e))
            continue
        if new is not None:
            out[name] = new
    return out, changes, flags


def verify_candidate(dest, original, changed_names):
    """Package checks on the written copy. Returns (ok, lines)."""
    lines, ok = [], True
    try:
        with zipfile.ZipFile(dest) as z:
            bad = z.testzip()
            data = {n: z.read(n) for n in z.namelist()}
    except Exception as e:
        return False, ["FAIL, the written copy will not open as a package: %s" % e]
    lines.append("package opens and every member decompresses: %s"
                 % ("pass" if bad is None else "FAIL " + str(bad)))
    ok = ok and bad is None
    same_set = set(data) == set(original)
    lines.append("part list identical to the source: %s" % ("pass" if same_set else "FAIL"))
    ok = ok and same_set
    moved = [n for n in data if n in original and n not in changed_names
             and data[n] != original[n]]
    lines.append("every part not listed as changed is byte-identical: %s"
                 % ("pass" if not moved else "FAIL, " + ", ".join(moved[:5])))
    ok = ok and not moved
    unparsable = [n for n in changed_names if mh.parse(data.get(n, b"")) is None]
    lines.append("every changed part parses as XML: %s"
                 % ("pass" if not unparsable else "FAIL, " + ", ".join(unparsable)))
    ok = ok and not unparsable
    ns = mh.namespace_defects({n: data[n] for n in changed_names if n in data}, original)
    lines.append("namespace references in changed parts resolve to their original URIs: %s"
                 % ("pass" if not ns else "FAIL, " + "; ".join(ns[:3])))
    ok = ok and not ns
    rel_before = sum(len(mh.relationships(mh.parse(original[n])))
                     for n in original if n.endswith(".rels") and mh.parse(original[n]) is not None)
    rel_after = sum(len(mh.relationships(mh.parse(data[n])))
                    for n in data if n.endswith(".rels") and mh.parse(data[n]) is not None)
    lines.append("relationship count %d before, %d after: %s"
                 % (rel_before, rel_after, "pass" if rel_before == rel_after else "FAIL"))
    ok = ok and rel_before == rel_after
    dangling = [t for n in data if n.endswith(".rels")
                for t in mh.internal_targets(n, data[n]) if t not in data]
    lines.append("internal relationship targets resolve: %s"
                 % ("pass" if not dangling else "FAIL, " + "; ".join(dangling[:3])))
    ok = ok and not dangling
    sheets = [n for n in data if n.startswith("xl/worksheets/")]
    if sheets:
        import re
        rx = re.compile(r"<(?:[A-Za-z0-9_.-]+:)?f\b[^>]*>(.*?)</(?:[A-Za-z0-9_.-]+:)?f>", re.S)
        fb = [f for n in sheets for f in rx.findall(mh.as_text(original.get(n, b"")))]
        fa = [f for n in sheets for f in rx.findall(mh.as_text(data[n]))]
        lines.append("worksheet formulas compared in order, %d before, %d after: %s"
                     % (len(fb), len(fa), "identical" if fb == fa else "FAIL"))
        ok = ok and fb == fa
    lines.append("Excel, Word or PowerPoint application open verification: NOT PERFORMED, no "
                 "native application in this runtime")
    return ok, lines


# ---------------------------------------------------------------- reporting

def remaining(path_or_parts, is_text):
    """Findings left after the run, from the shared detection routine."""
    if is_text:
        found = mh.text_trace_findings(path_or_parts)
    else:
        found = mh.trace_findings(path_or_parts)
    return [f for f in found if f[0] in ("artifact", "review")
            and "U+" not in f[2][:8]     # hidden Unicode is reported elsewhere
            and not f[2].startswith("VS-RUN")]


def main():
    ap = argparse.ArgumentParser(description="AI citation artifacts and ChatGPT link "
                                             "tracking, AI Fix")
    ap.add_argument("path")
    ap.add_argument("--clean", action="store_true", help="write a corrected copy")
    ap.add_argument("-o", "--output")
    ap.add_argument("--log", metavar="FILE", help="also write the report to this file")
    a = ap.parse_args()

    src = a.path
    if not os.path.exists(src):
        print("cannot read %s: no such file" % src)
        return 2
    ptype = mh.detect_package_type(src)
    ext = os.path.splitext(src)[1].lower()
    is_text = ptype not in mh.OOXML_TYPES and ptype != "pdf" and ext in TEXT_EXT
    if ptype == "pdf":
        print("a PDF is not edited here; run metadata_hygiene.py, which reports citation "
              "tokens and link tracking in its page text and link targets")
        return 2
    if ptype not in mh.OOXML_TYPES and not is_text:
        print("unsupported file: %s (content reads as %s)" % (src, ptype))
        return 2

    dest = None
    if a.clean:
        dest = a.output or (os.path.splitext(src)[0] + "_artifacts" + ext)
        if same_file(dest, src):
            print("refused: the output %s is the source, or resolves to it. Nothing was "
                  "written." % dest)
            return 2
        if not is_text and os.path.splitext(dest)[1].lower() != "." + ptype:
            print("refused: a %s source needs a .%s output, got %s. Nothing was written."
                  % (ptype.upper(), ptype, dest))
            return 2
    if a.log:
        hit = mh.write_collision(a.log, [("source", src), ("output", dest)])
        if hit:
            print("refused: the log destination %s is the %s (%s), or resolves to it. "
                  "Nothing was written." % (a.log, hit[0], hit[1]))
            return 2

    report = ["# AI citation artifacts and link tracking", "",
              "File: %s" % os.path.basename(src),
              "Mode: %s" % ("clean, corrected copy written to %s" % os.path.basename(dest)
                            if a.clean else "report only, nothing written"), ""]

    signed = []
    if is_text:
        with open(src, encoding="utf-8", errors="surrogateescape", newline="") as fh:
            text = fh.read()
        found = remaining(text, True)
    else:
        try:
            parts = mh.read_parts(src)
        except Exception as e:
            print("cannot read package: %s" % e)
            return 2
        found = remaining(parts, False)
        signed = mh.signature_parts(parts)
        if a.clean and signed:
            print("refused: the package is digitally signed (%s). Rewriting it would "
                  "invalidate the signature, so nothing was written. Remove any token in "
                  "the authoring application and re-sign, or obtain an unsigned copy."
                  % ", ".join(signed))
            return 2

    report += ["## Found in the source", ""]
    report += ["- [%s] %s: %s" % f for f in found] or ["- nothing found"]
    if signed:
        report += ["", "Digitally signed package (%s): reported only. --clean refuses to "
                       "rewrite it, since that would invalidate the signature." % ", ".join(signed)]

    status = 0 if not found else 2
    if a.clean:
        if is_text:
            new, changes, flags = clean_text_file(text, ext in MARKDOWN_EXT)
            with open(dest, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
                fh.write(new)
            left = remaining(new, True)
            checks = ["text file written in its original encoding and line endings; line count %d before, %d after: %s"
                      % (text.count("\n"), new.count("\n"),
                         "pass" if text.count("\n") == new.count("\n") else "FAIL")]
            ok = text.count("\n") == new.count("\n")
        else:
            cleaned, changes, flags = clean_package(parts)
            changed = {n for n in cleaned if cleaned[n] is not parts[n]}
            mh.write_package(cleaned, dest)
            ok, checks = verify_candidate(dest, parts, changed)
            left = remaining(mh.read_parts(dest), False) if ok else found
        report += ["", "## Changes made", ""]
        report += ["- " + c for c in changes] or ["- none"]
        report += ["", "## Left for review, not edited", ""]
        report += ["- " + f for f in flags] or ["- none"]
        report += ["", "## Checks on the written copy", ""]
        report += ["- " + c for c in checks]
        report += ["", "## Still present after the run", ""]
        report += ["- [%s] %s: %s" % f for f in left] or ["- nothing"]
        result = ("nothing left" if ok and not left
                  else "items left, see above" if ok else "FAIL, the written copy did not pass "
                                                           "its checks; do not use it")
        report += ["", "Result: %s" % result]
        status = 0 if ok and not left else 2
        print("written: %s" % dest)
        print("changes: %d; left for review: %d; still present: %d"
              % (len(changes), len(flags), len(left)))
        print("result: %s" % result)
    else:
        print("found: %d (artifact %d, review %d); nothing written"
              % (len(found), len([f for f in found if f[0] == "artifact"]),
                 len([f for f in found if f[0] == "review"])))

    report += ["", "This tool edits text and link targets only. Package and metadata hygiene "
                   "(metadata_hygiene.py) is still the last mutating step and certifies the "
                   "file delivered. Nothing here is evidence of AI authorship."]
    text_out = "\n".join(report) + "\n"
    if a.log:
        with open(a.log, "w", encoding="utf-8") as fh:
            fh.write(text_out)
        print("log: %s" % a.log)
    else:
        print(text_out)
    return status


if __name__ == "__main__":
    sys.exit(main())
