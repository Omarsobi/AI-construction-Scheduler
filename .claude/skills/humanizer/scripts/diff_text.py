#!/usr/bin/env python3
"""Compare the text of an original document against a revised one.

Reports every changed and removed passage so scan item 39 can be applied to
each removal, and gives the counts the change summary needs. Also reports
characters present in the revised file that the original did not use, which
is the introduction test scan item 16 asks for.

Hidden characters (Rev37, variation selector runs at Rev38). Every hidden Unicode character present in the
revised file is reported, not only one the edit introduced: its code point,
name, class, count, count in the original and where it sits. The original is
the baseline, so each finding is marked pre-existing or introduced. Classes:
invisible control (zero-width space, word joiner and invisible operators,
byte-order mark inside text, bidirectional embedding, override and isolate
controls, tag characters, and from Rev38 variation selectors in a run of two
or more, reported under VS-RUN), language-dependent (zero-width non-joiner and
joiner, left-to-right and right-to-left marks, which Arabic and other scripts
need; informational, never a failure) and informational (soft hyphen, narrow
no-break space, a single variation selector, private-use characters). A byte-order
mark at the very start of a plain-text file is a valid encoding signature and
is not reported. Nothing is removed or normalized; this is a report. The
classification is the one metadata_hygiene.py uses for certification.

Usage:
    python diff_text.py ORIGINAL REVISED [--full]

Works on .docx, .pptx, .xlsx and plain text formats. Text extraction is
shared with extract_text.py, which reads XML by namespace and local name and
honours each part's encoding.

A comparison is only as complete as the extraction behind it. Where either
file could not be opened or a text-bearing part would not parse, the report is
marked INCOMPLETE, no "no changes" conclusion is drawn, and the exit status is
2. Where both files genuinely hold no text in the supported locations, the
report says so rather than reporting a clean comparison. Exit status 0 means
the comparison ran on complete extractions.
"""

import argparse
import difflib
import os
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_text import OOXML, extract_report  # noqa: E402
import metadata_hygiene as mh  # noqa: E402

# Characters an AI pass commonly introduces. Presence in the original is fine;
# only introduction is a failure.
WATCH = {
    "\u2013": "en dash", "\u2014": "em dash", "\u2018": "curly open quote",
    "\u2019": "curly apostrophe", "\u201c": "curly open double quote",
    "\u201d": "curly close double quote", "\u2011": "non-breaking hyphen",
    "\u00a0": "non-breaking space", "\u2026": "ellipsis character",
    "\u2022": "bullet character",
}


def texts(path):
    rows, problems, notes = extract_report(path)
    return [t for _, t in rows], problems, notes


def char_counts(seq):
    joined = "".join(seq)
    return {c: joined.count(c) for c in WATCH if c in joined}


def hidden_inventory(path, rows):
    """{code point: (count, [locations])} for the hidden characters in rows."""
    plain = os.path.splitext(path)[1].lower() not in OOXML
    out = {}
    for i, (loc, text) in enumerate(rows):
        for start, end, cp in mh.hidden_hits(text):
            if plain and i == 0 and start == 0 and cp == 0xFEFF:
                continue          # a valid initial byte-order mark
            count, where = out.get(cp, (0, []))
            where.append("%s [%s]" % (loc, mh.visible_snippet(text, start, end, 20)))
            out[cp] = (count + 1, where)
    return out


def report_hidden(orig_path, rows_a, rev_path, rows_b):
    """Presence report for the revised file, with the original as baseline.
    Returns True where an invisible control was introduced."""
    before = hidden_inventory(orig_path, rows_a)
    after = hidden_inventory(rev_path, rows_b)
    print("\nhidden-character check (presence, with the original as baseline):")
    if not after:
        print("  none present in the revised file")
    introduced_control = False
    for cp in sorted(after):
        count, where = after[cp]
        prior = before.get(cp, (0, []))[0]
        new = max(0, count - prior)
        cls = mh.hidden_class(cp)
        state = ("%d introduced" % new) if new else "pre-existing"
        if cls == mh.HIDDEN_CONTROL and new:
            introduced_control = True
            tail = "-- scan item 16 fail; remove the introduced character(s) in the edit"
        elif cls == mh.HIDDEN_CONTROL:
            tail = ("-- review: remove it in the edit unless it belongs to source-controlled "
                    "text; never removed automatically")
        elif cls == mh.HIDDEN_LANGUAGE:
            tail = "-- informational, preserve (joining or direction in Arabic and other scripts)"
        else:
            tail = "-- informational, may be legitimate"
        print("  [%s] %s: %d in the revised file, %d in the original, %s %s"
              % (cls, mh.unicode_label(cp), count, prior, state, tail))
        for w in where[:5]:
            print("      at " + w)
        if len(where) > 5:
            print("      and %d more" % (len(where) - 5))
    gone = [cp for cp in before if cp not in after]
    for cp in sorted(gone):
        print("  [%s] %s: %d in the original, 0 in the revised file -- removed; check it was "
              "not source-controlled text" % (mh.hidden_class(cp), mh.unicode_label(cp),
                                               before[cp][0]))
    return introduced_control


def texts_rows(path):
    rows, problems, notes = extract_report(path)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("original")
    ap.add_argument("revised")
    ap.add_argument("--full", action="store_true",
                    help="print whole passages instead of the first 200 characters")
    args = ap.parse_args()

    a, prob_a, notes_a = texts(args.original)
    b, prob_b, notes_b = texts(args.revised)
    problems = (["original: " + p for p in prob_a] + ["revised: " + p for p in prob_b])
    if problems:
        print("=" * 72)
        print("INCOMPLETE COMPARISON")
        print("=" * 72)
        for p in problems:
            print("  " + p)
        print("Text that could not be extracted was not compared. Changes in it are not")
        print("shown below, and the absence of a listed change proves nothing.")
        print()
    sm = difflib.SequenceMatcher(None, a, b)

    changed = removed = added = reduced = 0
    print("=" * 72)
    print("CHANGES")
    print("=" * 72)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        old, new = a[i1:i2], b[j1:j2]
        if tag == "replace":
            changed += 1
            wa = sum(len(t.split()) for t in old)
            wb = sum(len(t.split()) for t in new)
            if wb < wa:
                reduced += 1
                head = f"CHANGED, {wa - wb} words shorter -- apply scan item 39"
            else:
                head = "CHANGED"
        elif tag == "delete":
            removed += 1
            head = "REMOVED  -- apply scan item 39"
        else:
            added += 1
            head = "ADDED    -- confirm the records support it"
        print(f"\n[{head}]")
        for t in old:
            print("  OLD:", t if args.full else t[:200])
        for t in new:
            print("  NEW:", t if args.full else t[:200])

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"passages: {len(a)} -> {len(b)}")
    print(f"words:    {sum(len(t.split()) for t in a)} -> {sum(len(t.split()) for t in b)}")
    print(f"changed: {changed} (of which {reduced} lost words)   removed: {removed}   added: {added}")
    for n in sorted(set(notes_a + notes_b)):
        print("note: " + n)
    if problems:
        print("result: INCOMPLETE, %d extraction problem(s) listed above; this comparison "
              "cannot confirm that nothing else changed" % len(problems))
    elif not a and not b:
        print("result: both files hold no text in the supported locations, so there was "
              "nothing to compare. This is an empty result, not a confirmation.")
    elif not (changed or removed or added):
        print("result: no change found in the extracted text")

    ca, cb = char_counts(a), char_counts(b)
    print("\ncharacter check (introduction, not presence):")
    flagged = False
    for c, name in WATCH.items():
        na, nb = ca.get(c, 0), cb.get(c, 0)
        if nb > na:
            print(f"  INTRODUCED {nb - na} x {name} -- scan item 16 fail")
            flagged = True
        elif na != nb:
            print(f"  {name}: {na} -> {nb} (reduced; check it was not reproduced source text)")
            flagged = True
    if not flagged:
        print("  none introduced")

    report_hidden(args.original, texts_rows(args.original),
                  args.revised, texts_rows(args.revised))

    if removed or reduced:
        print("\nEvery removal and every shortened passage above must pass scan item 39")
        print("before issue: is the content required, or has anything supported been")
        print("lost rather than retained elsewhere? Relocation is not removal.")
    return 2 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
