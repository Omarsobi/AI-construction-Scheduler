#!/usr/bin/env python3
"""Run every executable suite for ai-language-fix and print one summary.

    python tests/run_all.py

Exit status 0 when every suite exits 0, 1 otherwise. A suite that reports
SKIPPED cases is listed, because a skipped case is not a passed case. These
optional libraries remove the skips: python-docx, openpyxl, python-pptx,
reportlab, pypdf, commonmark and markdown-it-py. They are test-only; the
scripts use the standard library.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = ["test_annotations.py", "test_delivery.py", "test_extract.py",
          "test_inspection.py", "test_paths.py", "test_traces.py",
          "test_clean_text.py", "test_writing_assistants.py", "test_rev3.py"]


def main():
    failed = []
    for name in SUITES:
        r = subprocess.run([sys.executable, os.path.join(HERE, name)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=os.path.dirname(HERE))
        out = (r.stdout or "") + (r.stderr or "")
        fails = sum(1 for line in out.splitlines() if line.lstrip().startswith("FAIL"))
        skips = sum(1 for line in out.splitlines() if line.lstrip().startswith("SKIPPED"))
        tail = [line for line in out.strip().splitlines() if line.strip()][-1:]
        status = "ok  " if r.returncode == 0 and not fails else "FAIL"
        if status == "FAIL":
            failed.append(name)
        print("%s %-28s exit %d, %d failed, %d skipped  | %s"
              % (status, name, r.returncode, fails, skips, tail[0][:70] if tail else ""))
    print("\n%d suite(s) run, %d failed" % (len(SUITES), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
