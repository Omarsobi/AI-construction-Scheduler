#!/usr/bin/env python3
"""ai-language-fix Rev3 cases: the further citation and tracking forms, the
no-break space rule, white text, and a sensitivity label left in place.

Fixtures are generated here. No project document is used or shipped.

    python tests/test_rev3.py

Exit status 0 when every case passes, 1 otherwise. The Word cases need
python-docx and are skipped, and reported as skipped, without it.
"""
import io
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
ARTIFACTS = os.path.join(SCRIPTS, "clean_artifacts.py")
HYGIENE = os.path.join(SCRIPTS, "metadata_hygiene.py")
CLEAN_TEXT = os.path.join(SCRIPTS, "clean_text.py")
INSPECT = os.path.join(SCRIPTS, "inspect_content.py")

try:
    import docx  # noqa: F401
    HAVE_DOCX = True
except ImportError:
    HAVE_DOCX = False


def run(script, *args):
    p = subprocess.run([sys.executable, script] + [str(a) for a in args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


class TokenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_new_confirmed_forms_are_artifacts_and_are_removed(self):
        src = write(os.path.join(self.tmp, "a.md"),
                    "Claim one oai_citation:2 here.\n"
                    'Claim two {"attribution":{"attributableIndex":"12-40"}} here.\n'
                    "See https://example.org/x?utm_source=openai&p=1 for detail.\n")
        code, out = run(ARTIFACTS, src)
        self.assertIn("[artifact] line 1: oai_citation token", out)
        self.assertIn("[artifact] line 2: attribution JSON fragment", out)
        self.assertIn("[artifact] line 3: utm_source=openai", out)
        dst = os.path.join(self.tmp, "a_clean.md")
        run(ARTIFACTS, src, "--clean", "-o", dst)
        cleaned = read(dst)
        self.assertNotIn("oai_citation", cleaned)
        self.assertNotIn("attributableIndex", cleaned)
        self.assertIn("https://example.org/x?p=1", cleaned)
        self.assertNotIn("utm_source", cleaned)
        code, _ = run(HYGIENE, src, "--log", os.path.join(self.tmp, "a_log.md"))
        self.assertEqual(code, 2)

    def test_ambiguous_forms_are_flagged_and_never_removed(self):
        text = "Ref attached_file:3 and grok_card and fact [web:1] end.\n"
        src = write(os.path.join(self.tmp, "b.md"), text)
        code, out = run(ARTIFACTS, src)
        for label in ("attached_file reference residue", "grok_card residue", "[web:N] source tag"):
            self.assertIn("[review] line 1: " + label, out)
        self.assertNotIn("[artifact]", out)
        dst = os.path.join(self.tmp, "b_clean.md")
        run(ARTIFACTS, src, "--clean", "-o", dst)
        if os.path.exists(dst):
            self.assertEqual(read(dst), text)

    def test_ordinary_text_and_other_tracking_are_not_findings(self):
        src = write(os.path.join(self.tmp, "c.md"),
                    "The attached_files list and the web: 1 result.\n"
                    "See https://example.org/x?utm_source=newsletter&utm_medium=email here.\n"
                    "The openai page at https://example.org/openai is ordinary.\n")
        code, out = run(ARTIFACTS, src)
        self.assertIn("found: 0", out)

    @unittest.skipUnless(HAVE_DOCX, "python-docx is not installed")
    def test_openai_tracking_in_a_word_hyperlink_target_is_removed(self):
        import test_traces as tt
        import zipfile
        src = tt.make_docx(os.path.join(self.tmp, "d.docx"), ["Body text."],
                           links=[("guide", "https://example.org/g?utm_source=openai&p=2")])
        code, _ = run(HYGIENE, src, "--log", os.path.join(self.tmp, "d_log.md"))
        self.assertEqual(code, 2)
        self.assertIn("utm_source=openai", read(os.path.join(self.tmp, "d_log.md")))
        dst = os.path.join(self.tmp, "d_clean.docx")
        run(ARTIFACTS, src, "--clean", "-o", dst)
        with zipfile.ZipFile(dst) as z:
            rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
        self.assertIn("https://example.org/g?p=2", rels)
        self.assertNotIn("utm_source", rels)


class NoBreakSpaceTest(unittest.TestCase):
    def test_kept_beside_a_digit_and_converted_between_words(self):
        tmp = tempfile.mkdtemp()
        src = write(os.path.join(tmp, "n.txt"),
                    "Pay SAR 1,000 and 10 % of it.\n"
                    "ordinary words and plain text here.\n")
        dst = os.path.join(tmp, "n_out.txt")
        code, out = run(CLEAN_TEXT, src, "-o", dst, "--log", os.path.join(tmp, "n_log.md"))
        self.assertEqual(code, 0, out)
        cleaned = read(dst)
        self.assertIn("SAR 1,000", cleaned)
        self.assertIn("10 %", cleaned)
        self.assertIn("ordinary words and plain text here.", cleaned)
        log = read(os.path.join(tmp, "n_log.md"))
        self.assertIn("beside a digit, kept", log)


@unittest.skipUnless(HAVE_DOCX, "python-docx is not installed")
class WhiteTextTest(unittest.TestCase):
    def test_white_text_is_reported_and_white_on_a_highlight_is_not(self):
        from docx import Document
        from docx.enum.text import WD_COLOR_INDEX
        from docx.shared import RGBColor
        tmp = tempfile.mkdtemp()
        d = Document()
        p = d.add_paragraph("Visible sentence. ")
        r = p.add_run("concealed instruction")
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        q = d.add_paragraph()
        r2 = q.add_run("banner label")
        r2.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        r2.font.highlight_color = WD_COLOR_INDEX.BLACK
        src = os.path.join(tmp, "w.docx")
        d.save(src)
        with open(src, "rb") as f:
            before = f.read()
        code, out = run(INSPECT, src)
        self.assertIn("white text, possibly invisible on a white background", out)
        self.assertIn("concealed instruction", out)
        self.assertNotIn("banner label", out)
        with open(src, "rb") as f:
            self.assertEqual(f.read(), before)


class SensitivityLabelTest(unittest.TestCase):
    def test_a_sensitivity_label_property_survives_the_clean(self):
        import test_writing_assistants as g
        tmp = tempfile.mkdtemp()
        parts = g.with_props(g.docx_with_comment(),
                             [("MSIP_Label_0000_Enabled", "true"),
                              ("MSIP_Label_0000_Name", "Internal")])
        _, code, out, log, output = g.clean(tmp, parts)
        self.assertEqual(code, 0, output[-300:])
        kept = g.custom(out)
        self.assertIn("MSIP_Label_0000_Enabled", kept)
        self.assertIn("MSIP_Label_0000_Name", kept)


if __name__ == "__main__":
    unittest.main(verbosity=1)
