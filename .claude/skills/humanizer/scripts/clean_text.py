#!/usr/bin/env python3
"""Mechanical character cleanup for the fix-language skill.

Handles the mechanical half of Plain text and punctuation, invisible
characters and non-ASCII punctuation, so the rewrite can concentrate on
wording and rhythm. It changes characters only. It does not touch wording and
is not a substitute for the rewrite.

    python clean_text.py input.docx
    python clean_text.py input.txt -o cleaned.txt
    python clean_text.py input.docx --dry-run       # report only, writes nothing
    python clean_text.py input.docx --keep-dashes   # leave em and en dashes alone
    python clean_text.py input.docx --no-punct      # invisible characters only
    python clean_text.py input.docx --baseline original.docx -o work.docx --log work_log.md

Accepts .docx, .txt and .md. Writes <name>_cleaned.<ext> and <name>_cleanlog.md,
or the paths given with -o and --log.

Protected inputs. The input, and the pre-edit baseline where --baseline names
one, are never written. Before anything is written, the cleaned output and the
log are each checked against both, and against each other, by path, resolved
path, symbolic link and hard link. A collision is refused with exit status 2
and the reason on stdout and stderr; nothing is written, deleted or truncated.
--dry-run writes nothing and so needs no destination check.
Standard library only, with no dependency on an external zip executable, so it
runs unchanged on Windows, macOS and Linux.

Skill: fix-language
Revision: issued with Fix Language Rev 3.22, 16-Oct-26 (runs of two or more
variation selectors removed; a single selector kept)
Earlier issue: Rev 3.21, 08-Oct-26 (U+200C and U+200D preserved
unconditionally)
Earlier issue: Rev 3.17, 29-Sep-26 (destination protection)
Earlier issues: Rev 2.0 dated 19-Aug-26 and the tracked-change protection
added at Rev 3.11
"""

import argparse
import os
import re
import shutil
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
import tempfile
import zipfile
from collections import Counter

# ---------------------------------------------------------------- characters

# U+200C (zero-width non-joiner) and U+200D (zero-width joiner) are not in
# this set and are never removed, whatever the script, language, text node or
# neighbouring characters: Arabic, Persian and Indic text and emoji sequences
# depend on them, and a joiner can sit in a Word run of its own (Rev 3.21).
INVISIBLE = {
    "\u200b": "zero-width space",
    "\u2060": "word joiner",
    "\ufeff": "byte order mark",
    "\u00ad": "soft hyphen",
    "\u200e": "left-to-right mark",
    "\u200f": "right-to-left mark",
    "\u061c": "arabic letter mark",
    "\u202a": "left-to-right embedding",
    "\u202b": "right-to-left embedding",
    "\u202c": "pop directional formatting",
    "\u202d": "left-to-right override",
    "\u202e": "right-to-left override",
    "\u2066": "left-to-right isolate",
    "\u2067": "right-to-left isolate",
    "\u2068": "first strong isolate",
    "\u2069": "pop directional isolate",
    "\u2028": "line separator",
    "\u2029": "paragraph separator",
    "\u180e": "mongolian vowel separator",
    "\u2061": "function application",
    "\u2062": "invisible times",
    "\u2063": "invisible separator",
    "\u2064": "invisible plus",
    "\u115f": "hangul choseong filler",
    "\u1160": "hangul jungseong filler",
}

# Two or more consecutive variation selectors, in either range, carry no
# meaning in text and are the usual carrier of a hidden payload, so a run is
# removed whole. A single selector after a base character (an emoji
# presentation selector, an ideographic variant) is kept (Rev 3.22).
VS_RUN_RX = re.compile("[\ufe00-\ufe0f\U000e0100-\U000e01ef]{2,}")

PUNCT = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2026": "...",
    "\u2022": "-", "\u2023": "-", "\u25cf": "-", "\u25aa": "-", "\u00b7": "-",
    "\u2032": "'", "\u2033": "''",
    "\u00ab": '"', "\u00bb": '"',
    "\u2009": " ", "\u2002": " ", "\u2003": " ",
    "\u2004": " ", "\u2005": " ", "\u2006": " ", "\u2007": " ", "\u2008": " ",
    "\u00ae": "(R)", "\u2122": "(TM)", "\u00a9": "(C)",
    "\u2212": "-",
    # Beyond the documented list: hyphen variants that survive a plain
    # smart-quote sweep and read as introduced typography.
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2015": "-",
}

# ai-language-fix Rev3: a no-break space (U+00A0) or narrow no-break space
# (U+202F) beside a digit is deliberate typography: a currency code or unit
# held to its amount, a time held to AM or PM. It is kept. Between two other
# characters it is converted to an ordinary space.
NOBREAK = {"\u00a0": "no-break space", "\u202f": "narrow no-break space"}
NOBREAK_RX = re.compile("(.?)([\u00a0\u202f])(?=(.?))", re.S)

DASHES = "\u2013\u2014"

ARABIC = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff"
                    r"\ufb50-\ufdff\ufe70-\ufeff]")

# Spacing-aware dash handling, applied in this order.
DASH_RULES = [
    (re.compile(r"(\d)\s*[" + DASHES + r"]\s*(\d)"), r"\1-\2", "numeric range to hyphen"),
    (re.compile(r"\s+[" + DASHES + r"]\s+"), ", ", "spaced dash to comma"),
    (re.compile(r"(\w)[" + DASHES + r"](\w)"), r"\1-\2", "closed dash to hyphen"),
    (re.compile(r"[" + DASHES + r"]"), "-", "remaining dash to hyphen"),
]

DOCX_PARTS = ("word/document.xml", "word/header", "word/footer",
              "word/footnotes.xml", "word/endnotes.xml", "word/comments.xml")

W_T = re.compile(r"(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)", re.S)

# A tracked insertion, deletion or move is a record of who changed what.
# Editing text inside one rewrites that record, so those regions are left
# alone. w:moveFrom and w:moveTo hold the two halves of a tracked move and
# their text must stay identical to each other, so both are protected.
W_REVISION = re.compile(r"<w:(ins|del|moveFrom|moveTo)\b.*?</w:\1>", re.S)


def revision_spans(xml):
    return [(m.start(), m.end()) for m in W_REVISION.finditer(xml)]


def in_revision(pos, spans):
    return any(a <= pos < b for a, b in spans)


class Tally:
    def __init__(self):
        self.chars = Counter()
        self.dashes = Counter()
        self.arabic_skipped = 0
        self.parts = Counter()


def clean_string(text, tally, part, do_punct=True, do_dashes=True):
    """Clean one text node. A node containing Arabic is returned unchanged.

    Arabic text is reproduced exactly under Scope and limits, so such a node is
    excluded from every transformation here, invisible characters, punctuation
    conversion, dash handling and spacing, not from invisible characters alone.
    """
    if ARABIC.search(text):
        tally.arabic_skipped += 1
        return text

    for ch, name in INVISIBLE.items():
        if ch in text:
            n = text.count(ch)
            tally.chars[name] += n
            tally.parts[part] += n
            text = text.replace(ch, "")

    # After the invisible characters, so a run split by one of them is caught.
    for m in VS_RUN_RX.finditer(text):
        n = len(m.group(0))
        tally.chars["variation selector run"] += n
        tally.parts[part] += n
    text = VS_RUN_RX.sub("", text)

    if do_punct:
        for ch, repl in PUNCT.items():
            if ch in text:
                n = text.count(ch)
                tally.chars[f"{ch!r} to {repl!r}"] += n
                tally.parts[part] += n
                text = text.replace(ch, repl)

        def nobreak(m):
            before, ch, after = m.group(1), m.group(2), m.group(3)
            if before.isdigit() or after.isdigit():
                tally.chars[f"{NOBREAK[ch]} beside a digit, kept"] += 1
                return m.group(0)
            tally.chars[f"{ch!r} to ' '"] += 1
            tally.parts[part] += 1
            return before + " "
        text = NOBREAK_RX.sub(nobreak, text)

        if do_dashes:
            for pattern, repl, label in DASH_RULES:
                text, n = pattern.subn(repl, text)
                if n:
                    tally.dashes[label] += n
                    tally.parts[part] += n
            text = re.sub(r"[ \t]{2,}", " ", text)
            text = re.sub(r"\s+,", ",", text)
    return text


def clean_docx(src, dst, tally, do_punct, do_dashes, write=True):
    work = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(src) as z:
            z.extractall(work)
            names = z.namelist()
        skipped = []
        for part in names:
            if not part.startswith(DOCX_PARTS):
                continue
            path = os.path.join(work, *part.split("/"))
            if not os.path.exists(path):
                continue
            xml = open(path, encoding="utf8").read()

            spans = revision_spans(xml)

            def repl(m):
                if in_revision(m.start(), spans):
                    skipped.append(part)
                    return m.group(0)
                return m.group(1) + clean_string(
                    m.group(2), tally, part, do_punct, do_dashes) + m.group(3)

            new = W_T.sub(repl, xml)
            if write and new != xml:
                open(path, "w", encoding="utf8").write(new)
        if skipped:
            print("skipped %d text run(s) inside tracked revisions in %s; those are a record "
                  "of who changed what and are not edited automatically"
                  % (len(skipped), ", ".join(sorted(set(skipped)))))
        if write:
            if os.path.exists(dst):
                os.remove(dst)
            _repack(work, names, dst)
            if not os.path.exists(dst):
                raise RuntimeError(f"output not written: {dst}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _repack(work, names, dst):
    """Rebuild the .docx from the extracted tree using zipfile.

    Written in the original part order so the package structure is preserved.
    mimetype-style stored entries are not required by OOXML, so every part is
    deflated. No external zip executable is used.
    """
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for part in names:
            path = os.path.join(work, *part.split("/"))
            if part.endswith("/"):
                continue
            if not os.path.exists(path):
                continue
            z.write(path, part)


def clean_plain(src, dst, tally, do_punct, do_dashes, write=True):
    text = open(src, encoding="utf8").read()
    out = "\n".join(clean_string(line, tally, os.path.basename(src),
                                 do_punct, do_dashes) for line in text.split("\n"))
    if write:
        open(dst, "w", encoding="utf8").write(out)


def write_log(path, src, dst, tally, args):
    lines = [
        "# Character cleanup log", "",
        f"Source: {os.path.basename(src)}",
        f"Output: {os.path.basename(dst) if not args.dry_run else 'none, dry run'}",
        "Options: " + (
            " ".join(o for o, on in (("--keep-dashes", args.keep_dashes),
                                     ("--no-punct", args.no_punct),
                                     ("--dry-run", args.dry_run)) if on)
            or "none"),
        "",
        "## Characters changed", "",
    ]
    if tally.chars:
        lines += ["| Character | Count |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in sorted(tally.chars.items(),
                                                      key=lambda x: -x[1])]
    else:
        lines.append("None.")
    lines += ["", "## Dashes", ""]
    if tally.dashes:
        lines += ["| Rule | Count |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in sorted(tally.dashes.items())]
    elif args.keep_dashes:
        lines.append("Not processed, --keep-dashes was set. Resolve them by hand.")
    else:
        lines.append("None found.")
    lines += ["", "## Where", ""]
    if tally.parts:
        lines += ["| Part | Changes |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in sorted(tally.parts.items())]
    else:
        lines.append("No change made.")
    lines += [
        "", "## Not touched", "",
        "- Text nodes containing Arabic are left completely unchanged, no "
        "invisible-character removal, no punctuation conversion, no dash or "
        "spacing handling, because Arabic is reproduced exactly under Scope and "
        f"limits. Nodes left unchanged: {tally.arabic_skipped}.",
        "- Wording. This script changes characters only and is not a substitute "
        "for the rewrite.",
        "- In a .docx, only the text nodes in document, headers, footers, "
        "footnotes, endnotes and comments. Field codes, styles, numbering, table "
        "structure, images and tracked changes are left as they are.",
        "- Protected text under Scope and limits is not exempt, because this "
        "script works on characters without reading context. Where punctuation in "
        "clause wording, notices, quoted source text, defined terms, file names or "
        "code must be reproduced exactly, run --dry-run, read this log, and clean "
        "by hand instead.",
        "",
        "Read this log before accepting the output. State what was actually run.",
        "",
    ]
    text = "\n".join(lines)
    if args.dry_run:
        print(text)
    else:
        open(path, "w", encoding="utf8").write(text)
    return text


def _resolved(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def same_object(dest, protected):
    """True where writing dest would write protected, or where that cannot be
    ruled out. Existing files are compared by filesystem identity, which catches
    hard links and symlinks; a path not yet created is compared resolved."""
    try:
        if os.path.exists(dest) and os.path.exists(protected):
            if os.path.samefile(dest, protected):
                return True
        return _resolved(dest) == _resolved(protected)
    except OSError:
        return True


def destination_problem(dst, log_path, src, baseline):
    """The reason a write must be refused, or None. Checked before any write."""
    protected = [("input", src), ("baseline", baseline)]
    for out_label, out in (("cleaned output", dst), ("log", log_path)):
        for label, path in protected:
            if path and same_object(out, path):
                return ("the %s destination %s is the protected %s file (%s), or cannot be "
                        "shown to be separate from it" % (out_label, out, label, path))
    if same_object(dst, log_path):
        return "the cleaned output and the log resolve to the same file (%s)" % dst
    return None


def main():
    ap = argparse.ArgumentParser(description="Character cleanup for fix-language.")
    ap.add_argument("input")
    ap.add_argument("-o", "--output")
    ap.add_argument("--dry-run", action="store_true", help="report only, writes nothing")
    ap.add_argument("--keep-dashes", action="store_true", help="leave em and en dashes")
    ap.add_argument("--no-punct", action="store_true", help="invisible characters only")
    ap.add_argument("--baseline", metavar="FILE",
                    help="the untouched pre-edit original, preserved before any cleanup. "
                         "Protected: nothing is ever written to it")
    ap.add_argument("--log", metavar="FILE", help="where to write the cleanup log")
    args = ap.parse_args()

    src = args.input
    stem, ext = os.path.splitext(src)
    ext = ext.lower()
    if ext not in (".docx", ".txt", ".md"):
        sys.exit(f"Unsupported input {ext}. Accepts .docx, .txt and .md.")
    if not os.path.exists(src):
        sys.exit(f"Not found: {src}")

    dst = args.output or f"{stem}_cleaned{ext}"
    log_path = args.log or f"{stem}_cleanlog.md"
    tally = Tally()
    write = not args.dry_run
    if args.baseline and not os.path.exists(args.baseline):
        sys.exit(f"Baseline not found: {args.baseline}")
    if write:
        problem = destination_problem(dst, log_path, src, args.baseline)
        if problem:
            msg = f"refused: {problem}. Nothing was written."
            print(msg)
            print(msg, file=sys.stderr)
            sys.exit(2)

    if ext == ".docx":
        clean_docx(src, dst, tally, not args.no_punct, not args.keep_dashes, write)
    else:
        clean_plain(src, dst, tally, not args.no_punct, not args.keep_dashes, write)

    write_log(log_path, src, dst, tally, args)
    total = sum(tally.chars.values()) + sum(tally.dashes.values())
    if args.dry_run:
        print(f"# dry run, nothing written. {total} changes would be made.",
              file=sys.stderr)
    else:
        print(f"{dst}\n{log_path}")
        node = "node" if tally.arabic_skipped == 1 else "nodes"
        print(f"# {total} changes, {tally.arabic_skipped} Arabic {node} "
              f"left unchanged",
              file=sys.stderr)


if __name__ == "__main__":
    main()
