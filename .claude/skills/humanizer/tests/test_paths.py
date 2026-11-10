#!/usr/bin/env python3
"""Write-destination protection suite for scripts/metadata_hygiene.py.

Every file the script writes, the cleaned candidate and every report, is
checked against every protected file before anything is written: the source,
the pre-edit baseline, a supplied certificate, the file being recertified, and
the other output of the same run. A refused run returns a nonzero status,
reports no PASS, and leaves every protected file byte-identical.

Fixtures are generated here. No project document is used or shipped.

    python tests/test_paths.py

Exit status 0 when no case fails. Link cases the platform cannot create are
recorded as skips, not passes.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "metadata_hygiene.py")

from test_annotations import docx_with_comment, write_zip  # noqa: E402

CASES = []
SKIP = object()


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run(*args, cwd=None):
    p = subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True,
                       text=True, encoding="utf-8",
                          errors="replace", cwd=cwd)
    return p.returncode, p.stdout + p.stderr


def setup(tmp):
    """A source, its pre-edit baseline, and their hashes."""
    src = os.path.join(tmp, "Report.docx")
    base = os.path.join(tmp, "Report_base.docx")
    write_zip(src, docx_with_comment())
    shutil.copy(src, base)
    return src, base


def refused(code, out):
    return code != 0 and "PASS" not in out and "refused" in out.lower()


def certified(tmp):
    """A cleaned, certified candidate with its certificate."""
    src, base = setup(tmp)
    cand = os.path.join(tmp, "Report_clean.docx")
    code, out = run(src, "--clean", "--baseline", base, "-o", cand)
    assert code == 0, out
    return src, base, cand, os.path.join(tmp, "Report_metahygiene.md")


def try_link(kind, target, link):
    try:
        if kind == "sym":
            os.symlink(target, link)
        else:
            os.link(target, link)
        return True
    except (OSError, NotImplementedError, AttributeError):
        return False


@case("P1. clean: default report path equal to the baseline is refused")
def p1(tmp):
    src = os.path.join(tmp, "Report.docx")
    write_zip(src, docx_with_comment())
    base = os.path.join(tmp, "Report_metahygiene.md")
    shutil.copy(src, base)
    before = (sha(src), sha(base))
    cand = os.path.join(tmp, "Report_clean.docx")
    code, out = run(src, "--clean", "--baseline", base, "-o", cand)
    return (refused(code, out) and (sha(src), sha(base)) == before
            and not os.path.exists(cand)), "exit %s: %s" % (code, out[-200:])


@case("P2. scan: report path equal to the baseline is refused")
def p2(tmp):
    src = os.path.join(tmp, "Report.docx")
    write_zip(src, docx_with_comment())
    base = os.path.join(tmp, "Report_metahygiene.md")
    shutil.copy(src, base)
    before = sha(base)
    code, out = run(src, "--baseline", base)
    return refused(code, out) and sha(base) == before, "exit %s" % code


@case("P3. --log naming the source through a relative path is refused")
def p3(tmp):
    src, base = setup(tmp)
    before = (sha(src), sha(base))
    sub = os.path.join(tmp, "sub")
    os.mkdir(sub)
    code, out = run("Report.docx", "--clean", "--baseline", "Report_base.docx",
                    "-o", "Report_clean.docx", "--log", "sub/../Report.docx", cwd=tmp)
    return (refused(code, out) and (sha(src), sha(base)) == before
            and not os.path.exists(os.path.join(tmp, "Report_clean.docx"))), \
        "exit %s: %s" % (code, out[-200:])


@case("P4. --log equal to the candidate is refused")
def p4(tmp):
    src, base = setup(tmp)
    cand = os.path.join(tmp, "Report_clean.docx")
    code, out = run(src, "--clean", "--baseline", base, "-o", cand, "--log", cand)
    return refused(code, out) and not os.path.exists(cand), "exit %s" % code


@case("P5. --log as a symlink to the source is refused")
def p5(tmp):
    src, base = setup(tmp)
    link = os.path.join(tmp, "report_link.md")
    if not try_link("sym", src, link):
        return SKIP, "symbolic links not supported here"
    before = sha(src)
    code, out = run(src, "--clean", "--baseline", base, "-o",
                    os.path.join(tmp, "Report_clean.docx"), "--log", link)
    return refused(code, out) and sha(src) == before, "exit %s" % code


@case("P6. a hard link to the baseline at the default report path is refused")
def p6(tmp):
    src = os.path.join(tmp, "Report.docx")
    write_zip(src, docx_with_comment())
    base = os.path.join(tmp, "Report_base.docx")
    shutil.copy(src, base)
    if not try_link("hard", base, os.path.join(tmp, "Report_metahygiene.md")):
        return SKIP, "hard links not supported here"
    before = sha(base)
    code, out = run(src, "--clean", "--baseline", base, "-o",
                    os.path.join(tmp, "Report_clean.docx"))
    return refused(code, out) and sha(base) == before, "exit %s" % code


@case("P7. failure path: a refused candidate cannot write its report over the baseline")
def p7(tmp):
    src = os.path.join(tmp, "Report.docx")
    write_zip(src, docx_with_comment())
    base = os.path.join(tmp, "Report_metahygiene.md")
    shutil.copy(src, base)
    before = (sha(src), sha(base))
    code, out = run(src, "--clean", "--baseline", base, "-o", src)
    return refused(code, out) and (sha(src), sha(base)) == before, "exit %s" % code


@case("P8. recertify: certificate at the default recertification report path is refused")
def p8(tmp):
    _, base, cand, cert = certified(tmp)
    moved = os.path.join(tmp, "Report_clean_metahygiene.md")
    shutil.move(cert, moved)
    before = (sha(cand), sha(base), sha(moved))
    code, out = run(cand, "--recertify", "--certificate", moved, "--baseline", base)
    return refused(code, out) and (sha(cand), sha(base), sha(moved)) == before, \
        "exit %s: %s" % (code, out[-200:])


@case("P9. recertify: --log as a symlink to the certificate is refused")
def p9(tmp):
    _, base, cand, cert = certified(tmp)
    link = os.path.join(tmp, "recert.md")
    if not try_link("sym", cert, link):
        return SKIP, "symbolic links not supported here"
    before = sha(cert)
    code, out = run(cand, "--recertify", "--certificate", cert, "--baseline", base,
                    "--log", link)
    return refused(code, out) and sha(cert) == before, "exit %s" % code


@case("P10. recertify: --log equal to the file being recertified or its baseline is refused")
def p10(tmp):
    _, base, cand, cert = certified(tmp)
    before = (sha(cand), sha(base), sha(cert))
    c1, o1 = run(cand, "--recertify", "--certificate", cert, "--baseline", base, "--log", cand)
    c2, o2 = run(cand, "--recertify", "--certificate", cert, "--baseline", base, "--log", base)
    return (refused(c1, o1) and refused(c2, o2)
            and (sha(cand), sha(base), sha(cert)) == before), "exits %s %s" % (c1, c2)


@case("P11. recertify with a separate report path passes and preserves every input")
def p11(tmp):
    _, base, cand, cert = certified(tmp)
    before = (sha(cand), sha(base), sha(cert))
    log = os.path.join(tmp, "recert_report.md")
    code, out = run(cand, "--recertify", "--certificate", cert, "--baseline", base,
                    "--log", log)
    return (code == 0 and "PASS" in out and os.path.exists(log)
            and (sha(cand), sha(base), sha(cert)) == before), "exit %s" % code


@case("P12. safe, distinct destinations still work, with and without --log")
def p12(tmp):
    src, base = setup(tmp)
    before = (sha(src), sha(base))
    c1, _ = run(src, "--clean", "--baseline", base, "-o", os.path.join(tmp, "a.docx"))
    c2, _ = run(src, "--clean", "--baseline", base, "-o", os.path.join(tmp, "b.docx"),
                "--log", os.path.join(tmp, "b_report.md"))
    return (c1 == 0 and c2 == 0 and os.path.exists(os.path.join(tmp, "b_report.md"))
            and (sha(src), sha(base)) == before), "exits %s %s" % (c1, c2)


@case("P13. the candidate may not be written over a supplied certificate")
def p13(tmp):
    src, base = setup(tmp)
    cert = os.path.join(tmp, "old_cert.docx")
    shutil.copy(src, cert)
    before = sha(cert)
    code, out = run(src, "--clean", "--baseline", base, "-o", cert, "--certificate", cert)
    return code != 0 and "PASS" not in out and sha(cert) == before, "exit %s" % code


def main():
    if not os.path.exists(SCRIPT):
        print("cannot find %s" % SCRIPT)
        return 1
    failures = skips = 0
    for name, fn in CASES:
        tmp = tempfile.mkdtemp(prefix="pathtest_")
        try:
            ok, detail = fn(tmp)
        except Exception as e:
            ok, detail = False, "raised %s" % e
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if ok is SKIP:
            skips += 1
            print("skip  %s  [%s]" % (name, detail))
            continue
        print("%s  %s%s" % ("pass" if ok else "FAIL", name, "" if ok else "  [%s]" % detail))
        failures += 0 if ok else 1
    print("\n%d case(s) run, %d failure(s), %d skipped" % (len(CASES), failures, skips))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
