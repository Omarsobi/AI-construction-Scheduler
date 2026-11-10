#!/usr/bin/env python3
"""List repeated phrases, sentence openings and sentence closings in a document.

Supports scan item 43, which tests adjacent and consecutive paragraphs, and
scan item 44, which tests the document as a whole. The script reports where
wording repeats and how far apart the occurrences sit. It makes no judgment
about whether a repetition is a defect: a defined term, status code, approved
classification, name, heading, required boilerplate or the repeated wording a
register or table carries is expected to repeat, and the reviewer decides.

Usage:
    python scan_repetition.py FILE [--min-words N] [--max-words N]
                                   [--min-count N] [--top N]

Works on .docx, .pptx, .xlsx and plain text formats. Text extraction is
shared with extract_text.py.

Coverage caveat. This finds literal repetition of the extracted text only. It
does not find paraphrase, repeated paragraph structure, repeated rhetorical
function or repeated cadence, all of which items 43 and 44 still require the
reviewer to read for. A clean run is not proof of coverage and never stands in
for reading the document.
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
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_text import (extract_report, parse, word_paragraphs,  # noqa: E402
                          drawing_paragraphs)

# Openers that are checked separately at item 43 and reported even when the
# rest of the sentence differs.
TRANSITIONS = {
    "furthermore", "moreover", "additionally", "however", "therefore",
    "consequently", "accordingly", "nevertheless", "nonetheless", "similarly",
    "conversely", "overall", "importantly", "notably", "finally",
}

WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]*")
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


# Extraction problems met while reading the file, reported in the output.
INCOMPLETE = []


def structural_exclusions(path):
    """Return the set of extract_text locations that are table or heading text.

    The location label alone cannot carry this. In a .docx every paragraph,
    including a table cell and a heading, is labelled body:document.xml:pN. In
    a .pptx, title placeholders and table paragraphs are likewise labelled as
    ordinary slide passages. The parts therefore have to be read, and they are
    read with the same parser and the same paragraph sequence extract_text
    uses, so the indices line up whatever namespace prefix the file uses.
    """
    excluded = set()
    if not path.lower().endswith((".docx", ".pptx", ".xlsm", ".xlsx")):
        return excluded
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        return excluded
    with z:
        for part in z.namelist():
            is_doc = part == "word/document.xml"
            is_slide = part.startswith("ppt/slides/") and part.endswith(".xml")
            if not (is_doc or is_slide):
                continue
            try:
                root = parse(z.read(part))
            except Exception:
                continue          # reported as incomplete by extract_report
            if is_doc:
                for i, (_, _, in_table, heading) in enumerate(word_paragraphs(root), 1):
                    if in_table or heading:
                        excluded.add(f"body:document.xml:p{i}")
            else:
                base = os.path.basename(part)
                for i, (_, _, in_table, in_title) in enumerate(drawing_paragraphs(root), 1):
                    if in_table or in_title:
                        excluded.add(f"slide:{base}:a{i}")
    return excluded


def paragraphs(path):
    """Return (index, location, text) for each narrative passage.

    Table, heading, header and footer wording is excluded from the counts,
    because items 43 and 44 exempt the repetition a register, table or approved
    format carries. Excluded passages are listed so the reviewer can see what
    was skipped.
    """
    excluded = structural_exclusions(path)
    keep, skipped = [], []
    rows, problems, _ = extract_report(path)
    INCOMPLETE.extend(problems)
    for location, text in rows:
        text = " ".join(text.split())
        if not text:
            continue
        loc = location.lower()
        by_label = ("table" in loc or "cell" in loc or "sheet" in loc
                    or "header" in loc or "footer" in loc or "title" in loc)
        by_markup = text.startswith("#") or text.startswith("|")
        if location in excluded or by_label or by_markup:
            skipped.append((location, text))
        else:
            keep.append((len(keep), location, text))
    return keep, skipped


def sentences(text):
    return [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]


def span_label(where):
    """Classify by every pair, not by the outermost pair only.

    A phrase can be an item 43 defect and an item 44 defect at once, for
    example at passages 0, 1 and 4.
    """
    w = sorted(set(where))
    adjacent = any(b - a == 1 for a, b in zip(w, w[1:]))
    # If the outermost occurrences are at least two passages apart, at least
    # one non-adjacent pair exists, even where intermediate occurrences form
    # an adjacent run.
    separated = len(w) > 1 and w[-1] - w[0] >= 2
    if adjacent and separated:
        return "items 43 and 44, adjacent and separated pairs both present"
    if adjacent:
        return "item 43, adjacent passages"
    if separated:
        gap = min(b - a for a, b in zip(w, w[1:]))
        return f"item 44, nearest pair {gap} passages apart"
    return "same passage"


def ngrams(words, lo, hi):
    for n in range(lo, hi + 1):
        for i in range(len(words) - n + 1):
            yield " ".join(words[i:i + n])


def report_phrases(paras, lo, hi, min_count, top):
    seen = defaultdict(list)
    for idx, _, text in paras:
        words = [w.lower() for w in WORD.findall(text)]
        for g in set(ngrams(words, lo, hi)):
            seen[g].append(idx)

    rows = []
    for phrase, where in seen.items():
        if len(where) < min_count:
            continue
        # Drop a phrase fully contained in a longer reported phrase.
        rows.append((len(phrase.split()), len(where), phrase, sorted(where)))
    rows.sort(key=lambda r: (-r[0], -r[1]))

    kept = []
    for length, count, phrase, where in rows:
        if any(phrase in longer and phrase != longer for _, _, longer, _ in kept):
            continue
        kept.append((length, count, phrase, where))

    kept.sort(key=lambda r: (-r[1], -r[0]))
    kept = kept[:top]

    print("=" * 72)
    print("REPEATED PHRASES -- scan items 43 and 44")
    print("=" * 72)
    if not kept:
        print("  none at the current settings")
    for _, count, phrase, where in kept:
        print(f'  {count} x "{phrase}"')
        print(f"      passages {where}, {span_label(where)}")


def report_openings(paras):
    opens = defaultdict(list)
    closes = defaultdict(list)
    trans = []
    for idx, _, text in paras:
        sents = sentences(text)
        if not sents:
            continue
        first = WORD.findall(sents[0].lower())
        last = WORD.findall(sents[-1].lower())
        if first:
            if first[0] in TRANSITIONS:
                trans.append((idx, first[0]))
            opens[" ".join(first[:2])].append(idx)
        if last:
            closes[" ".join(last[:2])].append(idx)

    print()
    print("=" * 72)
    print("REPEATED PASSAGE OPENINGS AND CLOSINGS -- scan items 43 and 44")
    print("=" * 72)
    shown = False
    for label, table in (("opening", opens), ("closing", closes)):
        for phrase, where in sorted(table.items(), key=lambda kv: -len(kv[1])):
            if len(where) < 2:
                continue
            shown = True
            print(f'  {len(where)} passages {label} "{phrase} ..." '
                  f'-> {sorted(where)}, {span_label(where)}')
    if not shown:
        print("  no repeated opening or closing at two words")

    print()
    consecutive = [
        (a, b) for (a, wa), (b, wb) in zip(trans, trans[1:]) if b - a == 1
    ]
    if trans:
        print("  transition-word openings: "
              + ", ".join(f"passage {i} ({w})" for i, w in trans))
    if consecutive:
        for a, b in consecutive:
            print(f"  CONSECUTIVE passages {a} and {b} both open on a transition "
                  f"word -- item 43 fail unless the format requires it")
    elif trans:
        print("  no two consecutive passages open on a transition word")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path")
    ap.add_argument("--min-words", type=int, default=4)
    ap.add_argument("--max-words", type=int, default=8)
    ap.add_argument("--min-count", type=int, default=2)
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()

    paras, skipped = paragraphs(args.path)
    print(f"{args.path}: {len(paras)} narrative passages read, "
          f"{len(skipped)} table, heading, header or footer passages excluded")
    print()

    if skipped:
        print("EXCLUDED PASSAGES -- repetition here is expected and not tested")
        for location, text in skipped:
            preview = text if len(text) <= 70 else text[:67] + "..."
            print(f"  {location}: {preview}")
        print()

    report_phrases(paras, args.min_words, args.max_words,
                   args.min_count, args.top)
    report_openings(paras)

    print()
    print("This script reports repetition. It does not decide whether a")
    print("repetition is a defect. Defined terms, status codes, approved")
    print("classifications, names, headings, required boilerplate and the")
    print("wording a register or table carries are expected to repeat and are")
    print("not failures under items 43 and 44. It finds literal repetition")
    print("only, so a clean run is not proof of coverage.")
    if INCOMPLETE:
        print()
        print("INCOMPLETE: part of the document could not be read, so repetition in it")
        print("was not tested:")
        for p in INCOMPLETE:
            print("  " + p)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
