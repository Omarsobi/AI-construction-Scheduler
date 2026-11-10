#!/usr/bin/env python3
"""Permanent character-cleanup regression. Run: python tests/test_clean_text.py

The fixture contains real insertion/deletion containers and named, paired move
ranges. Deleted w:delText is outside the cleaner's w:t sweep; the insertion and
two move halves account for the three reported skipped text nodes.
"""

import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from test_annotations import W, docx_with_comment, read_zip, strip_comments, write_zip


class TrackedCleanupTest(unittest.TestCase):
    def test_ordinary_cleanup_preserves_all_tracked_content(self):
        attrs = 'w:author="Reviewer" w:date="2026-09-05T00:00:00Z"'
        moved = 'Moved\u2014text'
        body = (
            '<w:p><w:r><w:t>Ordinary\u2014text</w:t></w:r>'
            '<w:ins w:id="1" {attrs}><w:r><w:t>Inserted\u2014text</w:t></w:r></w:ins>'
            '<w:del w:id="2" {attrs}><w:r><w:delText>Deleted\u2014text</w:delText></w:r></w:del>'
            '<w:moveFromRangeStart w:id="3" w:name="move1" {attrs}/>'
            '<w:moveFrom w:id="4" {attrs}><w:r><w:t>{moved}</w:t></w:r></w:moveFrom>'
            '<w:moveFromRangeEnd w:id="3"/>'
            '<w:moveToRangeStart w:id="5" w:name="move1" {attrs}/>'
            '<w:moveTo w:id="6" {attrs}><w:r><w:t>{moved}</w:t></w:r></w:moveTo>'
            '<w:moveToRangeEnd w:id="5"/></w:p>'
        ).format(attrs=attrs, moved=moved)
        document = ('<w:document xmlns:w="%s"><w:body>%s</w:body></w:document>'
                    % (W, body)).encode('utf-8')
        ET.fromstring(document)
        parts = strip_comments(docx_with_comment())
        parts['word/document.xml'] = document
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              'scripts', 'clean_text.py')
        with tempfile.TemporaryDirectory(prefix='cleantext_test_') as tmp:
            src, dst = [os.path.join(tmp, name + '.docx') for name in ('source', 'cleaned')]
            write_zip(src, parts)
            with open(src, 'rb') as f:
                original_zip = f.read()
            result = subprocess.run([sys.executable, script, src, '-o', dst],
                                    capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('skipped 3 text run(s) inside tracked revisions', result.stdout)
            actual = read_zip(dst)
            expected = dict(parts)
            expected['word/document.xml'] = document.replace(
                'Ordinary\u2014text'.encode('utf-8'), b'Ordinary-text')
            # Compare every part, including the tracked containers and ranges,
            # byte for byte. Only the ordinary text correction is permitted.
            self.assertEqual(actual, expected)
            with open(src, 'rb') as f:
                self.assertEqual(f.read(), original_zip)


SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'scripts', 'clean_text.py')


def _run(*args, cwd=None):
    return subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True,
                          text=True, encoding="utf-8",
                          errors="replace", cwd=cwd)


def _read(path):
    with open(path, 'rb') as f:
        return f.read()


class DestinationProtectionTest(unittest.TestCase):
    """The input and the baseline are never written, and the output and the log
    never collide with them or with each other. Refusals change nothing."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='cleantext_paths_')
        self.tmp = self._tmp.name
        self.src = os.path.join(self.tmp, 'draft.md')
        with open(self.src, 'w', encoding='utf-8') as f:
            f.write('A test \u2014 with a dash and \u201cquotes\u201d.\n')
        self.base = os.path.join(self.tmp, 'draft_base.md')
        with open(self.base, 'wb') as f:
            f.write(_read(self.src))
        self.before = (_read(self.src), _read(self.base))

    def tearDown(self):
        self._tmp.cleanup()

    def assertRefused(self, result):
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('refused', result.stdout.lower())
        self.assertEqual((_read(self.src), _read(self.base)), self.before)

    def test_output_equal_to_input_is_refused(self):
        self.assertRefused(_run(self.src, '-o', self.src))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'draft_cleanlog.md')))

    def test_output_relative_alias_of_input_is_refused(self):
        os.mkdir(os.path.join(self.tmp, 'sub'))
        self.assertRefused(_run('draft.md', '-o', 'sub/../draft.md', cwd=self.tmp))

    def test_output_symlink_to_input_is_refused(self):
        link = os.path.join(self.tmp, 'link.md')
        try:
            os.symlink(self.src, link)
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest('symbolic links not supported here')
        self.assertRefused(_run(self.src, '-o', link))

    def test_output_hard_link_to_input_is_refused(self):
        link = os.path.join(self.tmp, 'hard.md')
        try:
            os.link(self.src, link)
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest('hard links not supported here')
        self.assertRefused(_run(self.src, '-o', link))

    def test_output_equal_to_baseline_is_refused(self):
        self.assertRefused(_run(self.src, '--baseline', self.base, '-o', self.base))

    def test_log_equal_to_input_or_baseline_is_refused(self):
        out = os.path.join(self.tmp, 'out.md')
        self.assertRefused(_run(self.src, '-o', out, '--log', self.src))
        self.assertRefused(_run(self.src, '--baseline', self.base, '-o', out,
                                '--log', self.base))
        self.assertFalse(os.path.exists(out))

    def test_default_log_path_holding_the_baseline_is_refused(self):
        base = os.path.join(self.tmp, 'draft_cleanlog.md')
        with open(base, 'wb') as f:
            f.write(self.before[0])
        result = _run(self.src, '--baseline', base, '-o', os.path.join(self.tmp, 'o.md'))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(_read(base), self.before[0])

    def test_output_equal_to_log_is_refused(self):
        out = os.path.join(self.tmp, 'same.md')
        self.assertRefused(_run(self.src, '-o', out, '--log', out))
        self.assertFalse(os.path.exists(out))

    def test_docx_output_equal_to_input_is_refused(self):
        src = os.path.join(self.tmp, 'doc.docx')
        write_zip(src, strip_comments(docx_with_comment(body_text='Text\u2014here')))
        before = _read(src)
        result = _run(src, '-o', src)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(_read(src), before)

    def test_safe_distinct_destinations_work(self):
        out = os.path.join(self.tmp, 'clean.md')
        log = os.path.join(self.tmp, 'clean_log.md')
        result = _run(self.src, '--baseline', self.base, '-o', out, '--log', log)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(os.path.exists(out) and os.path.exists(log))
        self.assertNotIn('\u2014', _read(out).decode('utf-8'))
        self.assertEqual((_read(self.src), _read(self.base)), self.before)

    def test_dry_run_writes_nothing(self):
        listing = sorted(os.listdir(self.tmp))
        result = _run(self.src, '--dry-run', '-o', self.src)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sorted(os.listdir(self.tmp)), listing)
        self.assertEqual((_read(self.src), _read(self.base)), self.before)


# ---------------------------------------------------------------- Rev 3.21

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'scripts', 'clean_text.py')
ZWNJ, ZWJ = '‌', '‍'


def _clean(src, dst, *extra):
    return subprocess.run([sys.executable, SCRIPT, src, '-o', dst] + list(extra),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def _docx(path, runs_xml):
    """A real Word package whose body paragraph holds the given runs."""
    document = ('<w:document xmlns:w="%s"><w:body><w:p>%s</w:p></w:body></w:document>'
                % (W, runs_xml)).encode('utf-8')
    ET.fromstring(document)
    parts = strip_comments(docx_with_comment())
    parts['word/document.xml'] = document
    write_zip(path, parts)
    return parts


def _run_xml(text):
    return '<w:r><w:t xml:space="preserve">%s</w:t></w:r>' % text


class JoinerPreservationTest(unittest.TestCase):
    """U+200C and U+200D survive cleaning unconditionally (Rev 3.21)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='joiner_test_')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _plain(self, text, name='in.txt'):
        src, dst = os.path.join(self.tmp, name), os.path.join(self.tmp, 'out_' + name)
        with open(src, 'w', encoding='utf8') as f:
            f.write(text)
        result = _clean(src, dst)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with open(dst, encoding='utf8') as f:
            return f.read()

    def test_1_latin_text_keeps_each_joiner(self):
        for joiner in (ZWNJ, ZWJ):
            text = 'A' + joiner + 'B'
            self.assertEqual(self._plain(text), text)

    def test_2_devanagari_conjuncts_keep_each_joiner(self):
        # KA, VIRAMA, joiner, SSA: a half form with ZWJ, an explicit virama with ZWNJ.
        for joiner in (ZWJ, ZWNJ):
            text = 'क्' + joiner + 'ष'
            out = self._plain(text)
            self.assertEqual([hex(ord(c)) for c in out], [hex(ord(c)) for c in text])

    def test_3_emoji_zwj_sequences_keep_every_code_point(self):
        family = '\U0001F468‍\U0001F469‍\U0001F467'
        flag = '\U0001F3F3️‍\U0001F308'
        out = self._plain(family + ' ' + flag)
        self.assertEqual([ord(c) for c in out], [ord(c) for c in family + ' ' + flag])

    def test_4_split_word_runs_keep_standalone_joiner(self):
        for joiner in (ZWNJ, ZWJ):
            src = os.path.join(self.tmp, 'split.docx')
            dst = os.path.join(self.tmp, 'split_out.docx')
            parts = _docx(src, _run_xml('می') + _run_xml(joiner)
                          + _run_xml('خواهم'))
            result = _clean(src, dst)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            # Every part, every run and every character, byte for byte.
            self.assertEqual(read_zip(dst), parts)

    def test_4b_joiner_in_non_arabic_word_run(self):
        for joiner in (ZWNJ, ZWJ):
            src = os.path.join(self.tmp, 'latin.docx')
            dst = os.path.join(self.tmp, 'latin_out.docx')
            parts = _docx(src, _run_xml('A' + joiner + 'B'))
            result = _clean(src, dst)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(read_zip(dst), parts)

    def test_5_arabic_node_still_unchanged(self):
        text = 'المشروع “quoted” — note​'
        self.assertEqual(self._plain(text), text)

    def test_6_other_invisible_characters_still_removed(self):
        text = 'A​B' + ZWNJ + 'C⁠D­E' + ZWJ + 'F‮G'
        self.assertEqual(self._plain(text), 'AB' + ZWNJ + 'CDE' + ZWJ + 'FG')

    def test_7_dry_run_leaves_source_untouched(self):
        src = os.path.join(self.tmp, 'dry.docx')
        parts = _docx(src, _run_xml('A' + ZWNJ + 'B​C'))
        with open(src, 'rb') as f:
            before = f.read()
        listing = sorted(os.listdir(self.tmp))
        result = subprocess.run([sys.executable, SCRIPT, src, '--dry-run'],
                                capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with open(src, 'rb') as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(sorted(os.listdir(self.tmp)), listing)
        self.assertEqual(read_zip(src), parts)

    def test_8_cleaning_is_idempotent(self):
        src = os.path.join(self.tmp, 'idem.docx')
        once = os.path.join(self.tmp, 'once.docx')
        twice = os.path.join(self.tmp, 'twice.docx')
        _docx(src, _run_xml('A' + ZWNJ + 'B​—C') + _run_xml(ZWJ))
        self.assertEqual(_clean(src, once).returncode, 0)
        self.assertEqual(_clean(once, twice).returncode, 0)
        first, second = read_zip(once), read_zip(twice)
        self.assertEqual(first, second)
        body = first['word/document.xml'].decode('utf-8')
        self.assertIn('A' + ZWNJ + 'B-C', body)
        self.assertIn('>' + ZWJ + '<', body)
        self.assertNotIn('​', body)


class VariationSelectorRunTest(unittest.TestCase):
    """Runs of two or more variation selectors are removed; one is kept (Rev 3.22)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='vs_test_')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _plain(self, text, name='in.txt'):
        src, dst = os.path.join(self.tmp, name), os.path.join(self.tmp, 'out_' + name)
        with open(src, 'w', encoding='utf8') as f:
            f.write(text)
        result = _clean(src, dst)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with open(dst, encoding='utf8') as f:
            return f.read()

    def test_1_supplementary_range_run_removed(self):
        run = ''.join(chr(0xE0100 + i) for i in range(14))
        self.assertEqual(self._plain('The' + run + ' slab.'), 'The slab.')

    def test_2_basic_range_run_removed(self):
        run = ''.join(chr(0xFE00 + (i % 16)) for i in range(28))
        self.assertEqual(self._plain('The' + run + ' slab.'), 'The slab.')

    def test_3_single_selectors_kept(self):
        text = 'Done ✔️, variant 葛\U000e0100.'
        out = self._plain(text)
        self.assertEqual([ord(c) for c in out], [ord(c) for c in text])

    def test_4_run_split_by_an_invisible_character_removed(self):
        self.assertEqual(self._plain('A︁​︂B'), 'AB')

    def test_5_word_run_removed_and_logged(self):
        src = os.path.join(self.tmp, 'vs.docx')
        dst = os.path.join(self.tmp, 'vs_out.docx')
        log = os.path.join(self.tmp, 'vs_log.md')
        _docx(src, _run_xml('The' + '︄︍\U000e0130' + ' slab.'))
        result = _clean(src, dst, '--log', log)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        body = read_zip(dst)['word/document.xml'].decode('utf-8')
        self.assertIn('>The slab.<', body)
        with open(log, encoding='utf8') as f:
            self.assertIn('| variation selector run | 3 |', f.read())

    def test_6_arabic_node_still_unchanged(self):
        text = 'المشروع' + '︀︁'
        self.assertEqual(self._plain(text), text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
