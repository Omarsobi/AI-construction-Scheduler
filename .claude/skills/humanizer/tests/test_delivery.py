#!/usr/bin/env python3
"""Permanent delivery-certification regression suite.

The defect this guards against is not detection. It is delivering a file other
than the one that passed verification, or calling a run clean when the exact
final artefact was never verified.

Every fixture is generated here from scratch. No project document is used and
none is shipped. Run from anywhere:

    python tests/test_delivery.py

Exit status 0 when every case passes, 1 otherwise.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "metadata_hygiene.py")

from test_annotations import (CT, OFF, PKG, SS, read_zip, write_zip,  # noqa: E402
                              xlsx_with_comment)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(*args):
    p = subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    return p.returncode, p.stdout + p.stderr


def contaminated(with_path=True, with_fileid=True):
    """A workbook carrying the residue this skill exists to remove."""
    parts = xlsx_with_comment()
    if with_fileid:
        parts["xl/webextensions/webextension1.xml"] = (
            '<?xml version="1.0"?><we:webextension xmlns:we="http://we" id="{a}">'
            '<we:properties><we:property name="claude.fileId" value="abc"/>'
            '</we:properties></we:webextension>').encode()
        parts["xl/webextensions/taskpanes.xml"] = (
            '<?xml version="1.0"?><wetp:taskpanes xmlns:wetp="http://tp" xmlns:r="%s">'
            '<wetp:taskpane><wetp:webextensionref r:id="rId1"/></wetp:taskpane>'
            '</wetp:taskpanes>' % OFF).encode()
        parts["xl/webextensions/_rels/taskpanes.xml.rels"] = (
            '<?xml version="1.0"?><Relationships xmlns="%s">'
            '<Relationship Id="rId1" Type="http://we" Target="webextension1.xml"/>'
            '</Relationships>' % PKG).encode()
        parts["xl/_rels/workbook.xml.rels"] = parts["xl/_rels/workbook.xml.rels"].decode(
        ).replace("</Relationships>",
                  '<Relationship Id="rId9" Type="http://tp" '
                  'Target="webextensions/taskpanes.xml"/></Relationships>').encode()
        parts["[Content_Types].xml"] = parts["[Content_Types].xml"].decode().replace(
            "</Types>",
            '<Override PartName="/xl/webextensions/taskpanes.xml" ContentType="x"/>'
            '<Override PartName="/xl/webextensions/webextension1.xml" ContentType="x"/>'
            "</Types>").encode()
    if with_path:
        parts["xl/workbook.xml"] = parts["xl/workbook.xml"].decode().replace(
            "<sheets>",
            '<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/'
            'markup-compatibility/2006"><mc:Choice xmlns:x15ac="http://x15ac" '
            'Requires="x15ac"><x15ac:absPath url="C:\\Users\\jdoe\\Documents\\Claude\\'
            'Sample Project\\"/></mc:Choice></mc:AlternateContent><sheets>').encode()
    return parts


def traces_in(path):
    """Every tool trace left in a package, ignoring visible cell text."""
    hits = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.lower().startswith("xl/sharedstrings"):
                continue          # visible content, not metadata
            if not name.lower().endswith((".xml", ".rels", ".vml")):
                continue
            text = z.read(name).decode("utf-8", "replace")
            for kw in ("claude.fileId", "Claude", "Sample Project"):
                if kw in text:
                    hits.append((name, kw))
    return hits


CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def prepare(tmp, parts=None):
    """A contaminated original plus the baseline taken before any edit."""
    original = os.path.join(tmp, "original.xlsx")
    baseline = os.path.join(tmp, "baseline.xlsx")
    write_zip(original, parts if parts is not None else contaminated())
    shutil.copy(original, baseline)
    return original, baseline


def recorded_hash(log_path):
    for line in open(log_path, encoding="utf-8"):
        if line.startswith("- Final SHA-256:"):
            return line.split(":", 1)[1].strip()
    return None


def certificate_for(original):
    """The hygiene report the clean issued, used as the certification record."""
    return log_for(original)


def log_for(path):
    return os.path.splitext(path)[0] + "_metahygiene.md"


@case("1. the cleaned candidate passes and is the file named for delivery")
def case_pass(tmp):
    original, baseline = prepare(tmp)
    out = os.path.join(tmp, "original_clean.xlsx")
    code, log = run(original, "--clean", "--baseline", baseline, "-o", out)
    if code != 0:
        return False, "exit %s" % code
    recorded = recorded_hash(log_for(original))
    named = "Final verified deliverable: original_clean.xlsx" in log
    return (named and recorded == sha256(out) and not traces_in(out)), \
        "named %s, hash match %s" % (named, recorded == sha256(out))


@case("2. delivering the original instead of the candidate is a hard failure")
def case_wrong_file(tmp):
    original, baseline = prepare(tmp)
    out = os.path.join(tmp, "original_clean.xlsx")
    run(original, "--clean", "--baseline", baseline, "-o", out)
    recorded = recorded_hash(log_for(original))
    # the workflow reaches for the original by name instead of the candidate
    code, log = run(original, "--recertify", "--certificate", certificate_for(original),
                    "--baseline", baseline)
    return code == 2, "exit %s" % code


@case("3. a candidate modified after verification is not delivered on that certificate")
def case_modified_after(tmp):
    original, baseline = prepare(tmp)
    out = os.path.join(tmp, "original_clean.xlsx")
    run(original, "--clean", "--baseline", baseline, "-o", out)
    recorded = recorded_hash(log_for(original))
    with zipfile.ZipFile(out, "a") as z:      # any resave changes the bytes
        z.writestr("docProps/thumbnail.txt", "touched")
    code, log = run(out, "--recertify", "--certificate", certificate_for(original),
                    "--baseline", baseline)
    reruns = "run the hygiene clean and the final scan again" in open(
        log_for(out), encoding="utf-8").read().lower()
    return code == 2 and reruns, "exit %s, rerun demanded %s" % (code, reruns)


@case("4. a non-zero clean exit yields no success and no certified output")
def case_clean_fails(tmp):
    original, baseline = prepare(tmp)
    out = os.path.join(tmp, "original_clean.xlsx")
    # no baseline at all: the clean cannot certify, so it must not report a pass
    code, log = run(original, "--clean", "-o", out)
    text = open(log_for(original), encoding="utf-8").read()
    return (code != 0 and "Final verification: FAIL" in text
            and "NOT certified" in text), "exit %s" % code


@case("5. a missing cleaned file is a failure, not a pass")
def case_missing_output(tmp):
    original, baseline = prepare(tmp)
    out = os.path.join(tmp, "no", "such", "dir", "original_clean.xlsx")
    code, log = run(original, "--clean", "--baseline", baseline, "-o", out)
    return code != 0 and not os.path.exists(out), "exit %s" % code


@case("6. a trace surviving the clean fails and certifies nothing")
def case_trace_survives(tmp):
    original, baseline = prepare(tmp)
    out = os.path.join(tmp, "original_clean.xlsx")
    run(original, "--clean", "--baseline", baseline, "-o", out)
    # put a trace back into the candidate, as a later pass would
    with zipfile.ZipFile(out) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["docProps/custom.xml"] = (
        '<?xml version="1.0"?><Properties xmlns="cp" xmlns:vt="v">'
        '<property fmtid="{X}" pid="2" name="claude.fileId"><vt:lpwstr>abc</vt:lpwstr>'
        '</property></Properties>').encode()
    write_zip(out, parts)
    code, log = run(out, "--recertify", "--certificate", certificate_for(original),
                    "--baseline", baseline)
    return code == 2, "exit %s" % code


@case("7. a hash that differs from the recorded one fails")
def case_hash_mismatch(tmp):
    original, baseline = prepare(tmp)
    out = os.path.join(tmp, "original_clean.xlsx")
    run(original, "--clean", "--baseline", baseline, "-o", out)
    recorded = recorded_hash(log_for(original))
    bad_cert = os.path.join(tmp, "cert_wrong.md")
    open(bad_cert, "w", encoding="utf-8").write(
        open(certificate_for(original), encoding="utf-8").read().replace(
            "- Final SHA-256: " + recorded, "- Final SHA-256: " + "0" * 64))
    code, log = run(out, "--recertify", "--certificate", bad_cert, "--baseline", baseline)
    return code == 2 and "has changed since it was verified" in open(
        log_for(out), encoding="utf-8").read(), "exit %s" % code


@case("8. no baseline still fails closed")
def case_no_baseline(tmp):
    original, baseline = prepare(tmp)
    out = os.path.join(tmp, "original_clean.xlsx")
    code, log = run(original, "--clean", "-o", out)
    return code == 2, "exit %s" % code


@case("9. a file with no traces passes without a destructive rewrite")
def case_clean_input(tmp):
    original, baseline = prepare(tmp, contaminated(with_path=False, with_fileid=False))
    out = os.path.join(tmp, "original_clean.xlsx")
    code, log = run(original, "--clean", "--baseline", baseline, "-o", out)
    before, after = read_zip(original), read_zip(out)
    untouched = all(before[n] == after[n] for n in before
                    if n in after and not n.endswith(".rels")
                    and n not in ("[Content_Types].xml",)
                    and not n.startswith("docProps/"))
    return code == 0 and untouched, "exit %s, parts untouched %s" % (code, untouched)


@case("10. a legitimate comment survives the certified clean")
def case_comment_preserved(tmp):
    original, baseline = prepare(tmp)
    out = os.path.join(tmp, "original_clean.xlsx")
    code, log = run(original, "--clean", "--baseline", baseline, "-o", out)
    kept = b"Reviewer note" in read_zip(out).get("xl/comments1.xml", b"")
    return code == 0 and kept, "exit %s, comment kept %s" % (code, kept)


@case("11. claude.fileId in a web extension is removed and the candidate passes")
def case_fileid(tmp):
    original, baseline = prepare(tmp, contaminated(with_path=False, with_fileid=True))
    out = os.path.join(tmp, "original_clean.xlsx")
    code, log = run(original, "--clean", "--baseline", baseline, "-o", out)
    return code == 0 and not traces_in(out), "exit %s, traces %s" % (code, traces_in(out))


@case("12. a stored Claude working path is removed and the candidate passes")
def case_path(tmp):
    original, baseline = prepare(tmp, contaminated(with_path=True, with_fileid=False))
    out = os.path.join(tmp, "original_clean.xlsx")
    code, log = run(original, "--clean", "--baseline", baseline, "-o", out)
    return code == 0 and not traces_in(out), "exit %s, traces %s" % (code, traces_in(out))


@case("13. read-only inspection after verification leaves the certificate valid")
def case_readonly(tmp):
    original, baseline = prepare(tmp)
    out = os.path.join(tmp, "original_clean.xlsx")
    run(original, "--clean", "--baseline", baseline, "-o", out)
    recorded = recorded_hash(log_for(original))
    with zipfile.ZipFile(out) as z:           # read only, nothing written
        z.namelist()
    code, log = run(out, "--recertify", "--certificate", certificate_for(original),
                    "--baseline", baseline)
    return code == 0 and sha256(out) == recorded, "exit %s" % code


@case("14. a save after verification invalidates the certificate")
def case_resave(tmp):
    original, baseline = prepare(tmp)
    out = os.path.join(tmp, "original_clean.xlsx")
    run(original, "--clean", "--baseline", baseline, "-o", out)
    recorded = recorded_hash(log_for(original))
    parts = read_zip(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:   # reopened and saved
        for name, data in parts.items():
            z.writestr(name, data)
    changed = sha256(out) != recorded
    code, log = run(out, "--recertify", "--certificate", certificate_for(original),
                    "--baseline", baseline)
    return changed and code == 2, "hash changed %s, exit %s" % (changed, code)


def field(log_path, label):
    for line in open(log_path, encoding="utf-8"):
        if line.startswith("- %s:" % label):
            return line.split(":", 1)[1].strip()
    return None


def certified(tmp, parts=None):
    """A genuine pre-edit baseline, its cleaned candidate and the certificate."""
    original, baseline = prepare(tmp, parts)
    out = os.path.join(tmp, "original_clean.xlsx")
    code, _ = run(original, "--clean", "--baseline", baseline, "-o", out)
    return original, baseline, out, certificate_for(original), code


def clean_workbook(tmp):
    """A sound workbook with no comment, note, VML or tracked item at all."""
    path = os.path.join(tmp, "clean.xlsx")
    write_zip(path, clean_parts())
    return path


def traced_no_annotation_parts():
    """A workbook carrying residue but no annotation structure of any kind.

    Needed where the point is that the cleaned candidate differs from its
    baseline. A file with nothing to clean produces a candidate identical to
    the baseline, which would make a candidate-as-baseline test vacuous.
    """
    parts = dict(contaminated(with_path=True, with_fileid=True))
    for part in ("xl/comments1.xml", "xl/drawings/vml1.vml"):
        parts.pop(part, None)
    parts["xl/worksheets/sheet1.xml"] = parts["xl/worksheets/sheet1.xml"].decode().replace(
        '<legacyDrawing r:id="rId2"/>', "").encode()
    parts["xl/worksheets/_rels/sheet1.xml.rels"] = (
        '<?xml version="1.0"?><Relationships xmlns="%s"></Relationships>' % PKG).encode()
    ct = parts["[Content_Types].xml"].decode()
    ct = ct.replace('<Default Extension="vml" ContentType="application/vnd.openxmlformats-'
                    'officedocument.vmlDrawing"/>', "")
    ct = ct.replace('<Override PartName="/xl/comments1.xml" ContentType="application/vnd.'
                    'openxmlformats-officedocument.spreadsheetml.comments+xml"/>', "")
    parts["[Content_Types].xml"] = ct.encode()
    return parts


def clean_parts():
    """The parts of a workbook with no annotation structure of any kind."""
    parts = contaminated(with_path=False, with_fileid=False)
    for part in ("xl/comments1.xml", "xl/drawings/vml1.vml"):
        parts.pop(part, None)
    parts["xl/worksheets/sheet1.xml"] = parts["xl/worksheets/sheet1.xml"].decode().replace(
        '<legacyDrawing r:id="rId2"/>', "").encode()
    parts["xl/worksheets/_rels/sheet1.xml.rels"] = (
        '<?xml version="1.0"?><Relationships xmlns="%s"></Relationships>' % PKG).encode()
    ct = parts["[Content_Types].xml"].decode()
    ct = ct.replace('<Default Extension="vml" ContentType="application/vnd.openxmlformats-'
                    'officedocument.vmlDrawing"/>', "")
    ct = ct.replace('<Override PartName="/xl/comments1.xml" ContentType="application/vnd.'
                    'openxmlformats-officedocument.spreadsheetml.comments+xml"/>', "")
    parts["[Content_Types].xml"] = ct.encode()
    return parts


@case("15. recertifying an Office file without the mandatory baseline fails")
def case_recert_no_baseline(tmp):
    original, baseline, path, cert, _ = certified(tmp, clean_parts())
    code, log = run(path, "--recertify", "--certificate", cert)
    text = open(log_for(path), encoding="utf-8").read()
    named = "mandatory baseline was not supplied" in text
    no_pass = "Final verification: PASS" not in text and "recertification: PASS" not in log
    return code == 2 and named and no_pass, \
        "exit %s, reason named %s, no contradictory pass %s" % (code, named, no_pass)


@case("16. recertifying against a baseline that does not exist fails")
def case_recert_missing_baseline(tmp):
    original, baseline, path, cert, _ = certified(tmp, clean_parts())
    code, log = run(path, "--recertify", "--certificate", cert,
                    "--baseline", os.path.join(tmp, "no_such_baseline.xlsx"))
    text = open(log_for(path), encoding="utf-8").read()
    return code == 2 and "does not exist" in text and "Final verification: PASS" not in text, \
        "exit %s" % code


@case("17. recertifying against an unusable baseline fails with a reason")
def case_recert_bad_baseline(tmp):
    original, baseline, path, cert, _ = certified(tmp, clean_parts())
    bad = os.path.join(tmp, "bad_baseline.xlsx")
    open(bad, "wb").write(b"this is not an office package")
    code, log = run(path, "--recertify", "--certificate", cert, "--baseline", bad)
    text = open(log_for(path), encoding="utf-8").read()
    reason = "cannot be read as a package" in text or "not a usable Office package" in text
    return code == 2 and reason and "Final verification: PASS" not in text, \
        "exit %s, reason given %s" % (code, reason)


@case("18. recertifying with a valid baseline and a matching hash passes")
def case_recert_good(tmp):
    original, baseline, path, cert, _ = certified(tmp, clean_parts())
    code, log = run(path, "--recertify", "--certificate", cert, "--baseline", baseline)
    modified = field(log_for(path), "Modified after final verification")
    return code == 0 and modified == "No", "exit %s, modified %s" % (code, modified)


@case("19. a wrong expected hash fails and reports the file as modified")
def case_recert_wrong_hash(tmp):
    original, baseline, path, cert, _ = certified(tmp, clean_parts())
    bad_cert = os.path.join(tmp, "cert_wrong.md")
    open(bad_cert, "w", encoding="utf-8").write(
        open(cert, encoding="utf-8").read().replace(
            "- Final SHA-256: " + sha256(path), "- Final SHA-256: " + "0" * 64))
    code, log = run(path, "--recertify", "--certificate", bad_cert, "--baseline", baseline)
    text = open(log_for(path), encoding="utf-8").read()
    modified = field(log_for(path), "Modified after final verification")
    return (code == 2 and modified == "Yes" and "Final verification: PASS" not in text), \
        "exit %s, modified %s" % (code, modified)


@case("20. baseline enforcement does not depend on the file holding annotations")
def case_recert_no_annotations(tmp):
    original, baseline, path, cert, _ = certified(tmp, clean_parts())
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
    has_annotation = any("comment" in n.lower() or n.lower().endswith(".vml") for n in names)
    if has_annotation:
        return False, "fixture is not annotation free"
    code, log = run(path, "--recertify", "--certificate", cert)
    return code == 2, "exit %s on an annotation-free file" % code


@case("21. the certification record carries both fingerprints")
def case_record_fields(tmp):
    original, baseline, out, cert, code = certified(tmp)
    text = open(cert, encoding="utf-8").read()
    return (code == 0
            and ("- Final SHA-256: " + sha256(out)) in text
            and ("- Baseline SHA-256: " + sha256(baseline)) in text), "exit %s" % code


@case("22. the genuine pre-edit baseline recertifies")
def case_genuine_baseline(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    code, log = run(out, "--recertify", "--certificate", cert, "--baseline", baseline)
    modified = field(log_for(out), "Modified after final verification")
    return code == 0 and modified == "No", "exit %s, modified %s" % (code, modified)


@case("23. the candidate offered as its own baseline fails")
def case_candidate_as_baseline(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    code, log = run(out, "--recertify", "--certificate", cert, "--baseline", out)
    text = open(log_for(out), encoding="utf-8").read()
    return (code == 2 and "certified baseline fingerprint" in text
            and "Final verification: PASS" not in text), "exit %s" % code


@case("24. a byte-for-byte copy of the candidate offered as baseline fails")
def case_candidate_copy_as_baseline(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    copy = os.path.join(tmp, "looks_like_a_baseline.xlsx")
    shutil.copy(out, copy)
    code, log = run(out, "--recertify", "--certificate", cert, "--baseline", copy)
    text = open(log_for(out), encoding="utf-8").read()
    return (code == 2 and sha256(copy) == sha256(out)
            and "certified baseline fingerprint" in text), "exit %s" % code


@case("25. an altered genuine baseline fails and says why")
def case_altered_baseline(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    altered = os.path.join(tmp, "altered.xlsx")
    shutil.copy(baseline, altered)
    with zipfile.ZipFile(altered, "a") as z:
        z.writestr("docProps/note.txt", "one byte more")
    code, log = run(out, "--recertify", "--certificate", cert, "--baseline", altered)
    text = open(log_for(out), encoding="utf-8").read()
    return code == 2 and "certified baseline fingerprint" in text, "exit %s" % code


@case("26. an unrelated valid Office file offered as baseline fails")
def case_unrelated_baseline(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    other = os.path.join(tmp, "unrelated.xlsx")
    write_zip(other, clean_parts())
    code, log = run(out, "--recertify", "--certificate", cert, "--baseline", other)
    return code == 2, "exit %s" % code


@case("27. recertifying with no baseline fails")
def case_recert_baseline_absent(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    code, log = run(out, "--recertify", "--certificate", cert)
    return code == 2, "exit %s" % code


@case("28. recertifying with no certification record fails")
def case_no_certificate(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    code, log = run(out, "--recertify", "--baseline", baseline)
    text = open(log_for(out), encoding="utf-8").read()
    return (code == 2 and "no certification record was supplied" in text
            and "Final verification: PASS" not in text), "exit %s" % code


@case("29. an unreadable or malformed certification record fails")
def case_bad_certificate(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    junk = os.path.join(tmp, "junk.md")
    open(junk, "w", encoding="utf-8").write("this is not a certification record\n")
    missing = os.path.join(tmp, "gone.md")
    a, _ = run(out, "--recertify", "--certificate", junk, "--baseline", baseline)
    b, _ = run(out, "--recertify", "--certificate", missing, "--baseline", baseline)
    return a == 2 and b == 2, "malformed %s, missing %s" % (a, b)


@case("30. a record without the baseline fingerprint fails")
def case_cert_no_baseline_sha(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    stripped = os.path.join(tmp, "no_baseline_sha.md")
    open(stripped, "w", encoding="utf-8").write("\n".join(
        l for l in open(cert, encoding="utf-8").read().splitlines()
        if not l.startswith("- Baseline SHA-256:")))
    code, log = run(out, "--recertify", "--certificate", stripped, "--baseline", baseline)
    return code == 2, "exit %s" % code


@case("31. a record without the final fingerprint fails")
def case_cert_no_final_sha(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    stripped = os.path.join(tmp, "no_final_sha.md")
    open(stripped, "w", encoding="utf-8").write("\n".join(
        l for l in open(cert, encoding="utf-8").read().splitlines()
        if not l.startswith("- Final SHA-256:")))
    code, log = run(out, "--recertify", "--certificate", stripped, "--baseline", baseline)
    return code == 2, "exit %s" % code


@case("32. a record carrying an invalid hash fails")
def case_cert_bad_hash(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    bad = os.path.join(tmp, "bad_hash.md")
    open(bad, "w", encoding="utf-8").write(
        open(cert, encoding="utf-8").read().replace(
            "- Baseline SHA-256: " + sha256(baseline), "- Baseline SHA-256: not-a-hash"))
    code, log = run(out, "--recertify", "--certificate", bad, "--baseline", baseline)
    return code == 2, "exit %s" % code


@case("33. a candidate whose hash differs from the record reports it as modified")
def case_candidate_changed(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    with zipfile.ZipFile(out, "a") as z:
        z.writestr("docProps/note.txt", "touched")
    code, log = run(out, "--recertify", "--certificate", cert, "--baseline", baseline)
    modified = field(log_for(out), "Modified after final verification")
    return code == 2 and modified == "Yes", "exit %s, modified %s" % (code, modified)


@case("34. a renamed but byte-identical genuine baseline still passes")
def case_renamed_baseline(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    renamed = os.path.join(tmp, "some_other_name.xlsx")
    shutil.copy(baseline, renamed)
    code, log = run(out, "--recertify", "--certificate", cert, "--baseline", renamed)
    return code == 0 and sha256(renamed) == sha256(baseline), "exit %s" % code


@case("35. a renamed but byte-identical candidate still passes")
def case_renamed_candidate(tmp):
    # Identity is the recorded hash, not the file name. A renamed copy of the
    # certified deliverable is the same artefact and is accepted.
    original, baseline, out, cert, _ = certified(tmp)
    renamed = os.path.join(tmp, "delivered_under_another_name.xlsx")
    shutil.copy(out, renamed)
    code, log = run(renamed, "--recertify", "--certificate", cert, "--baseline", baseline)
    modified = field(log_for(renamed), "Modified after final verification")
    return code == 0 and modified == "No", "exit %s, modified %s" % (code, modified)


@case("36. recertification mutates neither the candidate nor the baseline")
def case_readonly_both(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    before_out, before_base = sha256(out), sha256(baseline)
    code, log = run(out, "--recertify", "--certificate", cert, "--baseline", baseline)
    return (code == 0 and sha256(out) == before_out
            and sha256(baseline) == before_base), "exit %s" % code


@case("37. an annotation-free file cannot be its own baseline either")
def case_no_annotations_self_baseline(tmp):
    original, baseline, out, cert, _ = certified(tmp, traced_no_annotation_parts())
    if sha256(out) == sha256(baseline):
        return False, "fixture is vacuous: the candidate equals its baseline"
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    if any("comment" in n.lower() or n.lower().endswith(".vml") for n in names):
        return False, "fixture is not annotation free"
    code, log = run(out, "--recertify", "--certificate", cert, "--baseline", out)
    return code == 2, "exit %s on an annotation-free file" % code


def rejected(tmp, output, parts=None):
    """Attempt a clean whose output is the given destination.

    Returns (exit code, log text, source unchanged, baseline unchanged).
    """
    original, baseline = prepare(tmp, parts)
    before_src, before_base = sha256(original), sha256(baseline)
    code, log = run(original, "--clean", "--baseline", baseline, "-o", output)
    text = ""
    if os.path.exists(log_for(original)):
        text = open(log_for(original), encoding="utf-8").read()
    return (code, text,
            sha256(original) == before_src, sha256(baseline) == before_base,
            original, baseline)


@case("38. an output equal to the source is refused before anything is written")
def case_output_is_source(tmp):
    original, baseline = prepare(tmp)
    before_src, before_base = sha256(original), sha256(baseline)
    code, log = run(original, "--clean", "--baseline", baseline, "-o", original)
    text = open(log_for(original), encoding="utf-8").read()
    return (code == 2 and "protected source file" in text
            and "Final verification: PASS" not in text
            and sha256(original) == before_src
            and sha256(baseline) == before_base), "exit %s" % code


@case("39. an output equal to the baseline is refused before anything is written")
def case_output_is_baseline(tmp):
    original, baseline = prepare(tmp)
    before_src, before_base = sha256(original), sha256(baseline)
    code, log = run(original, "--clean", "--baseline", baseline, "-o", baseline)
    text = open(log_for(original), encoding="utf-8").read()
    return (code == 2 and "protected baseline file" in text
            and "Final verification: PASS" not in text
            and sha256(original) == before_src
            and sha256(baseline) == before_base), "exit %s" % code


@case("40. a relative path resolving to the source is refused")
def case_relative_source(tmp):
    original, baseline = prepare(tmp)
    alias = os.path.join(tmp, "sub", "..", os.path.basename(original))
    os.makedirs(os.path.join(tmp, "sub"), exist_ok=True)
    before = sha256(original)
    code, log = run(original, "--clean", "--baseline", baseline, "-o", alias)
    return code == 2 and sha256(original) == before, "exit %s" % code


@case("41. a relative path resolving to the baseline is refused")
def case_relative_baseline(tmp):
    original, baseline = prepare(tmp)
    alias = os.path.join(tmp, "sub", "..", os.path.basename(baseline))
    os.makedirs(os.path.join(tmp, "sub"), exist_ok=True)
    before = sha256(baseline)
    code, log = run(original, "--clean", "--baseline", baseline, "-o", alias)
    return code == 2 and sha256(baseline) == before, "exit %s" % code


def _symlink(target, link):
    try:
        os.symlink(target, link)
        return True
    except (OSError, NotImplementedError, AttributeError):
        return False


@case("42. a symlink pointing at the source is refused, where symlinks work")
def case_symlink_source(tmp):
    original, baseline = prepare(tmp)
    link = os.path.join(tmp, "link_to_source.xlsx")
    if not _symlink(original, link):
        return True, "symlinks unsupported on this platform, case not applicable"
    before = sha256(original)
    code, log = run(original, "--clean", "--baseline", baseline, "-o", link)
    return code == 2 and sha256(original) == before, "exit %s" % code


@case("43. a symlink pointing at the baseline is refused, where symlinks work")
def case_symlink_baseline(tmp):
    original, baseline = prepare(tmp)
    link = os.path.join(tmp, "link_to_baseline.xlsx")
    if not _symlink(baseline, link):
        return True, "symlinks unsupported on this platform, case not applicable"
    before = sha256(baseline)
    code, log = run(original, "--clean", "--baseline", baseline, "-o", link)
    return code == 2 and sha256(baseline) == before, "exit %s" % code


def _hardlink(target, link):
    try:
        os.link(target, link)
        return True
    except (OSError, NotImplementedError, AttributeError):
        return False


@case("44. a hard link to the source is refused, where hard links work")
def case_hardlink_source(tmp):
    original, baseline = prepare(tmp)
    link = os.path.join(tmp, "hardlink_source.xlsx")
    if not _hardlink(original, link):
        return True, "hard links unsupported on this platform, case not applicable"
    before = sha256(original)
    code, log = run(original, "--clean", "--baseline", baseline, "-o", link)
    return code == 2 and sha256(original) == before, "exit %s" % code


@case("45. a hard link to the baseline is refused, where hard links work")
def case_hardlink_baseline(tmp):
    original, baseline = prepare(tmp)
    link = os.path.join(tmp, "hardlink_baseline.xlsx")
    if not _hardlink(baseline, link):
        return True, "hard links unsupported on this platform, case not applicable"
    before = sha256(baseline)
    code, log = run(original, "--clean", "--baseline", baseline, "-o", link)
    return code == 2 and sha256(baseline) == before, "exit %s" % code


@case("46. a separate candidate path is still allowed")
def case_separate_output(tmp):
    original, baseline, out, cert, code = certified(tmp)
    return code == 0 and os.path.exists(out) and not traces_in(out), "exit %s" % code


@case("47. a candidate named after the source but a different file is allowed")
def case_lookalike_name(tmp):
    original, baseline = prepare(tmp)
    out = os.path.splitext(original)[0] + "_clean.xlsx"
    code, log = run(original, "--clean", "--baseline", baseline, "-o", out)
    same = os.path.exists(out) and os.path.samefile(out, original)
    return code == 0 and not same, "exit %s, same object %s" % (code, same)


@case("48. the default output path is allowed and is a separate file")
def case_default_output(tmp):
    original, baseline = prepare(tmp)
    code, log = run(original, "--clean", "--baseline", baseline)
    out = os.path.splitext(original)[0] + "_clean.xlsx"
    return code == 0 and os.path.exists(out), "exit %s" % code


@case("49. a refused overwrite leaves both protected files byte-identical")
def case_refused_no_mutation(tmp):
    original, baseline = prepare(tmp)
    before_src, before_base = sha256(original), sha256(baseline)
    run(original, "--clean", "--baseline", baseline, "-o", original)
    run(original, "--clean", "--baseline", baseline, "-o", baseline)
    return (sha256(original) == before_src and sha256(baseline) == before_base), \
        "source and baseline hashes after two refused attempts"


def detect(path):
    """The script's own detector, called directly."""
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
    import metadata_hygiene
    return metadata_hygiene.detect_package_type(path)


def docx_parts():
    from test_annotations import docx_with_comment
    return docx_with_comment()


def pptx_parts():
    """A minimal but structurally valid PowerPoint package."""
    return {
        "[Content_Types].xml":
            ('<?xml version="1.0"?><Types xmlns="%s">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
             'relationships+xml"/>'
             '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.'
             'openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
             '</Types>' % CT).encode(),
        "_rels/.rels":
            ('<?xml version="1.0"?><Relationships xmlns="%s">'
             '<Relationship Id="rId1" Type="%s/officeDocument" Target="ppt/presentation.xml"/>'
             '</Relationships>' % (PKG, OFF)).encode(),
        "ppt/presentation.xml":
            ('<?xml version="1.0"?><p:presentation xmlns:p="http://schemas.openxmlformats.org/'
             'presentationml/2006/main"/>').encode(),
    }


def certify(tmp, parts, ext):
    """Certify a package of the given type. Returns the pieces of the run."""
    original = os.path.join(tmp, "original" + ext)
    baseline = os.path.join(tmp, "baseline" + ext)
    write_zip(original, parts)
    shutil.copy(original, baseline)
    out = os.path.join(tmp, "candidate" + ext)
    code, log = run(original, "--clean", "--baseline", baseline, "-o", out)
    return original, baseline, out, log_for(original), code


@case("50. an XLSX source cannot be cleaned to a non-XLSX destination")
def case_xlsx_wrong_ext(tmp):
    original, baseline = prepare(tmp)
    before_src, before_base = sha256(original), sha256(baseline)
    results = {}
    for ext in (".md", ".docx", ".pptx", ".txt"):
        code, log = run(original, "--clean", "--baseline", baseline,
                        "-o", os.path.join(tmp, "candidate" + ext))
        results[ext] = code
        if os.path.exists(os.path.join(tmp, "candidate" + ext)):
            return False, "a candidate was written for %s" % ext
    text = open(log_for(original), encoding="utf-8").read()
    return (all(c == 2 for c in results.values())
            and "requires a .xlsx output candidate" in text
            and "Final verification: PASS" not in text
            and sha256(original) == before_src
            and sha256(baseline) == before_base), str(results)


@case("51. a DOCX source cannot be cleaned to a non-DOCX destination")
def case_docx_wrong_ext(tmp):
    original, baseline, out, cert, _ = certify(tmp, docx_parts(), ".docx")
    for ext in (".xlsx", ".pptx", ".txt"):
        code, log = run(original, "--clean", "--baseline", baseline,
                        "-o", os.path.join(tmp, "wrong" + ext))
        if code != 2 or os.path.exists(os.path.join(tmp, "wrong" + ext)):
            return False, "%s was accepted" % ext
    return True, "all rejected"


@case("52. a PPTX source cannot be cleaned to a non-PPTX destination")
def case_pptx_wrong_ext(tmp):
    original = os.path.join(tmp, "original.pptx")
    baseline = os.path.join(tmp, "baseline.pptx")
    write_zip(original, pptx_parts())
    shutil.copy(original, baseline)
    for ext in (".docx", ".xlsx", ".bin"):
        code, log = run(original, "--clean", "--baseline", baseline,
                        "-o", os.path.join(tmp, "wrong" + ext))
        if code != 2 or os.path.exists(os.path.join(tmp, "wrong" + ext)):
            return False, "%s was accepted" % ext
    return True, "all rejected"


@case("53. same-type candidates are still produced for xlsx, docx and pptx")
def case_same_type_ok(tmp):
    x = certify(os.path.join(tmp), contaminated(), ".xlsx")
    if x[4] != 0 or not os.path.exists(x[2]):
        return False, "xlsx exit %s" % x[4]
    d = tempfile.mkdtemp(dir=tmp)
    dd = certify(d, docx_parts(), ".docx")
    if dd[4] != 0 or not os.path.exists(dd[2]):
        return False, "docx exit %s" % dd[4]
    p = tempfile.mkdtemp(dir=tmp)
    pp = certify(p, pptx_parts(), ".pptx")
    if pp[4] != 0 or not os.path.exists(pp[2]):
        return False, "pptx exit %s" % pp[4]
    return True, "all three produced a candidate"


@case("54. the default output keeps the source extension")
def case_default_keeps_ext(tmp):
    for parts, ext in ((contaminated(), ".xlsx"), (docx_parts(), ".docx"),
                       (pptx_parts(), ".pptx")):
        d = tempfile.mkdtemp(dir=tmp)
        original = os.path.join(d, "original" + ext)
        baseline = os.path.join(d, "baseline" + ext)
        write_zip(original, parts)
        shutil.copy(original, baseline)
        code, log = run(original, "--clean", "--baseline", baseline)
        expected = os.path.join(d, "original_clean" + ext)
        if code != 0 or not os.path.exists(expected):
            return False, "%s exit %s" % (ext, code)
    return True, "all three defaults correct"


@case("55. an XLSX renamed to .md still requires a baseline")
def case_renamed_needs_baseline(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    renamed = os.path.join(tmp, "candidate.md")
    shutil.copy(out, renamed)
    code, log = run(renamed, "--recertify", "--certificate", cert)
    text = open(log_for(renamed), encoding="utf-8").read()
    return (code == 2 and "mandatory baseline" in text
            and "Final verification: PASS" not in text), "exit %s" % code


@case("56. an XLSX renamed to .md still requires a certificate")
def case_renamed_needs_certificate(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    renamed = os.path.join(tmp, "candidate.md")
    shutil.copy(out, renamed)
    code, log = run(renamed, "--recertify", "--baseline", baseline)
    text = open(log_for(renamed), encoding="utf-8").read()
    return (code == 2 and "certification record" in text
            and "Final verification: PASS" not in text), "exit %s" % code


@case("57. an XLSX renamed to .md recertifies against the genuine baseline")
def case_renamed_genuine(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    renamed = os.path.join(tmp, "candidate.md")
    shutil.copy(out, renamed)
    unchanged = sha256(renamed) == sha256(out)
    code, log = run(renamed, "--recertify", "--certificate", cert, "--baseline", baseline)
    text = open(log_for(renamed), encoding="utf-8").read()
    return (code == 0 and unchanged
            and "Package type read from the file content: xlsx" in text), "exit %s" % code


@case("58. a renamed XLSX cannot be its own baseline, nor a copy of itself")
def case_renamed_self_baseline(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    renamed = os.path.join(tmp, "candidate.md")
    shutil.copy(out, renamed)
    copy = os.path.join(tmp, "candidate_copy.md")
    shutil.copy(renamed, copy)
    a, _ = run(renamed, "--recertify", "--certificate", cert, "--baseline", renamed)
    b, _ = run(renamed, "--recertify", "--certificate", cert, "--baseline", copy)
    return a == 2 and b == 2, "self %s, copy %s" % (a, b)


@case("59. a renamed XLSX passes against a renamed byte-identical genuine baseline")
def case_renamed_both(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    renamed = os.path.join(tmp, "candidate.md")
    shutil.copy(out, renamed)
    base_renamed = os.path.join(tmp, "baseline_under_another_name.dat")
    shutil.copy(baseline, base_renamed)
    code, log = run(renamed, "--recertify", "--certificate", cert, "--baseline", base_renamed)
    return code == 0, "exit %s" % code


@case("60. a DOCX renamed to .bin and a PPTX renamed to .tmp still require a baseline")
def case_renamed_docx_pptx(tmp):
    d = tempfile.mkdtemp(dir=tmp)
    original, baseline, out, cert, code = certify(d, docx_parts(), ".docx")
    if code != 0:
        return False, "docx certify exit %s" % code
    rd = os.path.join(d, "candidate.bin")
    shutil.copy(out, rd)
    a, _ = run(rd, "--recertify", "--certificate", cert)
    p = tempfile.mkdtemp(dir=tmp)
    original, baseline, out, cert, code = certify(p, pptx_parts(), ".pptx")
    if code != 0:
        return False, "pptx certify exit %s" % code
    rp = os.path.join(p, "candidate.tmp")
    shutil.copy(out, rp)
    b, _ = run(rp, "--recertify", "--certificate", cert)
    return a == 2 and b == 2, "docx %s, pptx %s" % (a, b)


@case("61. the detector reads the package type from content, not the name")
def case_detector(tmp):
    checks = {}
    x = os.path.join(tmp, "actually_xlsx.md")
    write_zip(x, contaminated())
    checks["xlsx named .md"] = detect(x) == "xlsx"
    d = os.path.join(tmp, "actually_docx.dat")
    write_zip(d, docx_parts())
    checks["docx named .dat"] = detect(d) == "docx"
    p = os.path.join(tmp, "actually_pptx.zip")
    write_zip(p, pptx_parts())
    checks["pptx named .zip"] = detect(p) == "pptx"
    t = os.path.join(tmp, "not_really.xlsx")
    open(t, "w", encoding="utf-8").write("ordinary text, not a package\n")
    checks["text named .xlsx"] = detect(t) == "other"
    b = os.path.join(tmp, "broken.xlsx")
    open(b, "wb").write(b"PK\x03\x04 truncated rubbish")
    checks["malformed zip named .xlsx"] = detect(b) == "invalid"
    failed = [k for k, v in checks.items() if not v]
    return not failed, "; ".join(failed) or "all five classified correctly"


@case("62. a text file named .xlsx is never certified as an Office package")
def case_text_named_xlsx(tmp):
    original, baseline, out, cert, _ = certified(tmp)
    fake = os.path.join(tmp, "fake.xlsx")
    open(fake, "w", encoding="utf-8").write("ordinary text, not a package\n")
    code, log = run(fake, "--recertify", "--certificate", cert, "--baseline", baseline)
    return code == 2, "exit %s" % code


def renamed_source(tmp, parts, ext, wrong_ext):
    """A contaminated package written under a misleading extension."""
    src = os.path.join(tmp, "renamed" + wrong_ext)
    baseline = os.path.join(tmp, "baseline" + ext)
    write_zip(src, parts)
    shutil.copy(src, baseline)
    return src, baseline


@case("63. a contaminated XLSX renamed .md is scanned as a workbook")
def case_renamed_scan_xlsx(tmp):
    src, baseline = renamed_source(tmp, contaminated(), ".xlsx", ".md")
    code, log = run(src)
    text = open(log_for(src), encoding="utf-8").read()
    return (code == 2
            and "Package type read from the file content: xlsx" in text
            and "plain text" not in text
            and "Office web extension carrying tool name: claude" in text
            and "absolute working path record absPath" in text), "exit %s" % code


@case("64. a renamed XLSX cleaned without a correct Office output fails")
def case_renamed_clean_wrong_output(tmp):
    src, baseline = renamed_source(tmp, contaminated(), ".xlsx", ".md")
    before = sha256(src)
    code, log = run(src, "--clean", "--baseline", baseline)
    text = open(log_for(src), encoding="utf-8").read()
    wrote = os.path.exists(os.path.join(tmp, "renamed_clean.md"))
    return (code == 2 and not wrote
            and "requires a .xlsx output candidate" in text
            and "Final verification: PASS" not in text
            and sha256(src) == before), "exit %s, wrote %s" % (code, wrote)


@case("65. a renamed XLSX with a correct .xlsx output is cleaned as a workbook")
def case_renamed_clean_correct_output(tmp):
    src, baseline = renamed_source(tmp, contaminated(), ".xlsx", ".md")
    out = os.path.join(tmp, "candidate.xlsx")
    code, log = run(src, "--clean", "--baseline", baseline, "-o", out)
    return (code == 0 and os.path.exists(out) and not traces_in(out)), "exit %s" % code


@case("66. a DOCX renamed .bin is scanned as a Word package")
def case_renamed_scan_docx(tmp):
    src, baseline = renamed_source(tmp, docx_parts(), ".docx", ".bin")
    code, log = run(src)
    text = open(log_for(src), encoding="utf-8").read()
    return ("Package type read from the file content: docx" in text
            and "plain text" not in text
            and "Office Open XML package" in text), "exit %s" % code


@case("67. a PPTX renamed .tmp is scanned as a PowerPoint package")
def case_renamed_scan_pptx(tmp):
    src, baseline = renamed_source(tmp, pptx_parts(), ".pptx", ".tmp")
    code, log = run(src)
    text = open(log_for(src), encoding="utf-8").read()
    return ("Package type read from the file content: pptx" in text
            and "plain text" not in text
            and "Office Open XML package" in text), "exit %s" % code


@case("68. a genuine text file named .xlsx is not treated as a workbook")
def case_text_named_xlsx_scan(tmp):
    path = os.path.join(tmp, "fake.xlsx")
    open(path, "w", encoding="utf-8").write("ordinary text, not a package\n")
    code, log = run(path)
    return code == 2 and "Office Open XML package" not in log, "exit %s" % code


@case("69. a malformed zip named .xlsx fails closed")
def case_malformed_named_xlsx(tmp):
    path = os.path.join(tmp, "broken.xlsx")
    open(path, "wb").write(b"PK\x03\x04 truncated rubbish")
    code, log = run(path)
    a, _ = run(path, "--clean", "--baseline", path)
    return code == 2 and a == 2, "scan %s, clean %s" % (code, a)


@case("70. a genuine .md text file is still handled as text")
def case_real_text_unchanged(tmp):
    path = os.path.join(tmp, "note.md")
    open(path, "w", encoding="utf-8").write("A note that mentions Claude in its subject.\n")
    code, log = run(path)
    text = open(log_for(path), encoding="utf-8").read()
    return code == 0 and "plain text" in text, "exit %s" % code


@case("71. correctly named xlsx, docx and pptx behave as before")
def case_correct_names_unchanged(tmp):
    for parts, ext in ((contaminated(), ".xlsx"), (docx_parts(), ".docx"),
                       (pptx_parts(), ".pptx")):
        d = tempfile.mkdtemp(dir=tmp)
        original = os.path.join(d, "original" + ext)
        baseline = os.path.join(d, "baseline" + ext)
        write_zip(original, parts)
        shutil.copy(original, baseline)
        scan, _ = run(original)
        code, _ = run(original, "--clean", "--baseline", baseline)
        if code != 0 or not os.path.exists(os.path.join(d, "original_clean" + ext)):
            return False, "%s clean exit %s" % (ext, code)
        text = open(log_for(original), encoding="utf-8").read()
        if "Office Open XML package" not in text:
            return False, "%s was not handled as an Office package" % ext
    return True, "all three unchanged"


@case("72. a renamed Office source still cannot overwrite its source or baseline")
def case_renamed_overwrite_protection(tmp):
    src, baseline = renamed_source(tmp, contaminated(), ".xlsx", ".md")
    before_src, before_base = sha256(src), sha256(baseline)
    a, _ = run(src, "--clean", "--baseline", baseline, "-o", src)
    b, _ = run(src, "--clean", "--baseline", baseline, "-o", baseline)
    return (a == 2 and b == 2
            and sha256(src) == before_src
            and sha256(baseline) == before_base), "source %s, baseline %s" % (a, b)


# ------------------------------------------------- Rev30, Grammarly metadata

CUSTOM_NS = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
VT_NS = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
CORE_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC_NS = "http://purl.org/dc/elements/1.1/"

GRAMMARLY_ID = "acb4194c-c9b3-4e83-b7e6-2af8d924da62"
CONTENT_TYPE_ID = "0x010100AB12CD34EF56"


def add_part(parts, name, blob, rel_type, content_type):
    """Attach a docProps part the way a real package carries it: the part, its
    package relationship and its content-type override."""
    parts = dict(parts)
    parts[name] = blob
    rid = "rId" + name.split("/")[-1].split(".")[0]
    parts["_rels/.rels"] = parts["_rels/.rels"].decode().replace(
        "</Relationships>",
        '<Relationship Id="%s" Type="%s/%s" Target="%s"/></Relationships>'
        % (rid, OFF, rel_type, name)).encode()
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].decode().replace(
        "</Types>",
        '<Override PartName="/%s" ContentType="%s"/></Types>' % (name, content_type)).encode()
    return parts


def with_custom_props(parts, props):
    """docProps/custom.xml carrying the named properties, in package order."""
    body = "".join(
        '<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="%d" name="%s">'
        '<vt:lpwstr>%s</vt:lpwstr></property>' % (i + 2, name, value)
        for i, (name, value) in enumerate(props))
    blob = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="%s" xmlns:vt="%s">%s</Properties>'
            % (CUSTOM_NS, VT_NS, body)).encode()
    return add_part(parts, "docProps/custom.xml", blob, "custom-properties",
                    "application/vnd.openxmlformats-officedocument.custom-properties+xml")


def with_core_props(parts, creator="A. Preparer", modified_by="B. Reviewer"):
    blob = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="%s" xmlns:dc="%s">'
            '<dc:creator>%s</dc:creator><cp:lastModifiedBy>%s</cp:lastModifiedBy>'
            '</cp:coreProperties>' % (CORE_NS, DC_NS, creator, modified_by)).encode()
    return add_part(parts, "docProps/core.xml", blob, "metadata/core-properties",
                    "application/vnd.openxmlformats-package.core-properties+xml")


def grammarly_package(base_parts, extra_props=(), core=True):
    props = [("ContentTypeId", CONTENT_TYPE_ID),
             ("GrammarlyDocumentId", GRAMMARLY_ID),
             ("Category", "Reports")]
    props.extend(extra_props)
    parts = with_custom_props(base_parts, props)
    return with_core_props(parts) if core else parts


def custom_xml(path):
    return read_zip(path).get("docProps/custom.xml", b"").decode("utf-8", "replace")


def grammarly_case(tmp, base_parts, ext):
    """Scan then clean. Returns (scan exit, scan log, clean exit, candidate)."""
    original = os.path.join(tmp, "original" + ext)
    baseline = os.path.join(tmp, "baseline" + ext)
    write_zip(original, grammarly_package(base_parts))
    shutil.copy(original, baseline)
    scan_code, _ = run(original)
    scan_log = open(log_for(original), encoding="utf-8").read()
    out = os.path.join(tmp, "candidate" + ext)
    clean_code, _ = run(original, "--clean", "--baseline", baseline, "-o", out)
    return scan_code, scan_log, clean_code, out


@case("73. GrammarlyDocumentId in a .docx is detected, then removed, and the run passes")
def case_grammarly_docx(tmp):
    scan_code, scan_log, code, out = grammarly_case(tmp, docx_parts(), ".docx")
    seen = "GrammarlyDocumentId" in scan_log
    props = custom_xml(out)
    return (seen and scan_code == 2 and code == 0
            and "GrammarlyDocumentId" not in props and GRAMMARLY_ID not in props
            and "ContentTypeId" in props and CONTENT_TYPE_ID in props
            and "Category" in props), \
        "scan %s seen %s, clean %s, props %s" % (scan_code, seen, code, props[:200])


@case("74. GrammarlyDocumentId in an .xlsx is detected, then removed, and the run passes")
def case_grammarly_xlsx(tmp):
    scan_code, scan_log, code, out = grammarly_case(tmp, xlsx_with_comment(), ".xlsx")
    props = custom_xml(out)
    return ("GrammarlyDocumentId" in scan_log and scan_code == 2 and code == 0
            and "GrammarlyDocumentId" not in props and GRAMMARLY_ID not in props
            and "ContentTypeId" in props), "scan %s, clean %s, props %s" % (
        scan_code, code, props[:200])


@case("75. GrammarlyDocumentId in a .pptx is detected, then removed, and the run passes")
def case_grammarly_pptx(tmp):
    scan_code, scan_log, code, out = grammarly_case(tmp, pptx_parts(), ".pptx")
    props = custom_xml(out)
    return ("GrammarlyDocumentId" in scan_log and scan_code == 2 and code == 0
            and "GrammarlyDocumentId" not in props and GRAMMARLY_ID not in props
            and "ContentTypeId" in props), "scan %s, clean %s, props %s" % (
        scan_code, code, props[:200])


@case("76. the Grammarly rule leaves author and lastModifiedBy exactly as found")
def case_grammarly_author_untouched(tmp):
    _, _, code, out = grammarly_case(tmp, docx_parts(), ".docx")
    core = read_zip(out).get("docProps/core.xml", b"").decode("utf-8", "replace")
    return (code == 0 and "A. Preparer" in core and "B. Reviewer" in core), \
        "exit %s, core %s" % (code, core[:200])


@case("77. a file with no Grammarly metadata is unaffected by the new rule")
def case_no_grammarly_untouched(tmp):
    original = os.path.join(tmp, "original.docx")
    baseline = os.path.join(tmp, "baseline.docx")
    parts = with_core_props(with_custom_props(
        docx_parts(), [("ContentTypeId", CONTENT_TYPE_ID), ("Category", "Reports")]))
    write_zip(original, parts)
    shutil.copy(original, baseline)
    out = os.path.join(tmp, "candidate.docx")
    code, _ = run(original, "--clean", "--baseline", baseline, "-o", out)
    before, after = read_zip(original), read_zip(out)
    same = (before["docProps/custom.xml"] == after.get("docProps/custom.xml")
            and before["_rels/.rels"] == after.get("_rels/.rels")
            and before["[Content_Types].xml"] == after.get("[Content_Types].xml"))
    return code == 0 and same, "exit %s, unchanged %s" % (code, same)


@case("78. the Grammarly cleanup is idempotent")
def case_grammarly_idempotent(tmp):
    _, _, code, first = grammarly_case(tmp, docx_parts(), ".docx")
    second_baseline = os.path.join(tmp, "second_baseline.docx")
    shutil.copy(first, second_baseline)
    second = os.path.join(tmp, "second.docx")
    code2, _ = run(first, "--clean", "--baseline", second_baseline, "-o", second)
    same = read_zip(first) == read_zip(second)
    return code == 0 and code2 == 0 and same, \
        "first %s, second %s, identical %s" % (code, code2, same)


@case("79. Claude and Grammarly integration keys are both removed in one run")
def case_grammarly_with_claude(tmp):
    original = os.path.join(tmp, "original.xlsx")
    baseline = os.path.join(tmp, "baseline.xlsx")
    parts = grammarly_package(contaminated(), [("claude.fileId", "abc123")])
    write_zip(original, parts)
    shutil.copy(original, baseline)
    out = os.path.join(tmp, "candidate.xlsx")
    code, _ = run(original, "--clean", "--baseline", baseline, "-o", out)
    props = custom_xml(out)
    return (code == 0 and not traces_in(out)
            and "claude.fileId" not in props and "GrammarlyDocumentId" not in props
            and "ContentTypeId" in props), \
        "exit %s, traces %s, props %s" % (code, traces_in(out), props[:200])


@case("80. another Grammarly-named property is reported and kept, never removed (Rev33)")
def case_grammarly_other_property_reported(tmp):
    # Rev33 supersedes the Rev31 rule that removed any property naming the tool:
    # only a confirmed key such as GrammarlyDocumentId is removed.
    original = os.path.join(tmp, "original.docx")
    baseline = os.path.join(tmp, "baseline.docx")
    parts = with_core_props(with_custom_props(
        docx_parts(), [("ContentTypeId", CONTENT_TYPE_ID),
                       ("GrammarlySessionRef", "session-77")]))
    write_zip(original, parts)
    shutil.copy(original, baseline)
    out = os.path.join(tmp, "candidate.docx")
    code, _ = run(original, "--clean", "--baseline", baseline, "-o", out)
    kept = (not os.path.exists(out)) or "GrammarlySessionRef" in custom_xml(out)
    log = open(log_for(original), encoding="utf-8").read()
    return (code == 2 and kept and "GrammarlySessionRef" in custom_xml(original)
            and "not removed automatically" in log
            and "do not establish generative AI use" in log), \
        "exit %s, kept %s" % (code, kept)


@case("81. Grammarly named in visible content is reported, never edited, and does not fail")
def case_grammarly_in_content(tmp):
    original = os.path.join(tmp, "original.xlsx")
    baseline = os.path.join(tmp, "baseline.xlsx")
    parts = dict(xlsx_with_comment())
    parts["xl/worksheets/sheet1.xml"] = parts["xl/worksheets/sheet1.xml"].decode().replace(
        '<c r="A1"><v>1</v></c>',
        '<c r="A1" t="inlineStr"><is><t>Grammarly rollout</t></is></c>').encode()
    write_zip(original, parts)
    shutil.copy(original, baseline)
    out = os.path.join(tmp, "candidate.xlsx")
    code, _ = run(original, "--clean", "--baseline", baseline, "-o", out)
    kept = b"Grammarly rollout" in read_zip(out).get("xl/worksheets/sheet1.xml", b"")
    return code == 0 and kept, "exit %s, content kept %s" % (code, kept)


# ------------------------------------------------- Rev31, Grammarly and QuillBot

WE_NS = "http://schemas.microsoft.com/office/webextensions/webextension/2010/11"
WETP_NS = "http://schemas.microsoft.com/office/webextensions/taskpanes/2010/11"
WE_REL = "http://schemas.microsoft.com/office/2011/relationships/webextension"
WETP_REL = "http://schemas.microsoft.com/office/2011/relationships/webextensiontaskpanes"


def with_store_addin(parts, store_id, prefix="word"):
    """A web extension identified only by its Office Store reference id, the way
    Word persists an add-in task pane: no tool name anywhere in the part."""
    parts = dict(parts)
    parts[prefix + "/webextensions/webextension1.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<we:webextension xmlns:we="%s" id="{3F2A6C1E-0000-4000-8000-000000000001}">'
        '<we:reference id="%s" version="1.0.0.0" store="en-US" storeType="OMEX"/>'
        '<we:alternateReferences/><we:properties/><we:bindings/>'
        '</we:webextension>' % (WE_NS, store_id)).encode()
    parts[prefix + "/webextensions/taskpanes.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<wetp:taskpanes xmlns:wetp="%s" xmlns:r="%s">'
        '<wetp:taskpane dockstate="right" visibility="0" width="350" row="0">'
        '<wetp:webextensionref r:id="rId1"/></wetp:taskpane></wetp:taskpanes>'
        % (WETP_NS, OFF)).encode()
    parts[prefix + "/webextensions/_rels/taskpanes.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="%s"><Relationship Id="rId1" Type="%s" '
        'Target="webextension1.xml"/></Relationships>' % (PKG, WE_REL)).encode()
    parts["_rels/.rels"] = parts["_rels/.rels"].decode().replace(
        "</Relationships>",
        '<Relationship Id="rIdTp" Type="%s" Target="%s/webextensions/taskpanes.xml"/>'
        "</Relationships>" % (WETP_REL, prefix)).encode()
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].decode().replace(
        "</Types>",
        '<Override PartName="/%s/webextensions/taskpanes.xml" ContentType="application/'
        'vnd.ms-office.webextensiontaskpanes+xml"/>'
        '<Override PartName="/%s/webextensions/webextension1.xml" ContentType="application/'
        'vnd.ms-office.webextension+xml"/></Types>' % (prefix, prefix)).encode()
    return parts


def addin_case(tmp, store_id):
    original = os.path.join(tmp, "original.docx")
    baseline = os.path.join(tmp, "baseline.docx")
    write_zip(original, with_store_addin(docx_parts(), store_id))
    shutil.copy(original, baseline)
    scan_code, _ = run(original)
    scan_log = open(log_for(original), encoding="utf-8").read()
    out = os.path.join(tmp, "candidate.docx")
    code, _ = run(original, "--clean", "--baseline", baseline, "-o", out)
    return scan_code, scan_log, code, out


def no_webext_left(path):
    z = read_zip(path)
    names = " ".join(z)
    rels = z.get("_rels/.rels", b"").decode()
    ct = z.get("[Content_Types].xml", b"").decode()
    return ("webextension" not in names.lower() and "webextension" not in rels.lower()
            and "webextension" not in ct.lower())


@case("82. a QuillBot-named custom property is reported and kept (Rev33)")
def case_quillbot_property(tmp):
    original = os.path.join(tmp, "original.docx")
    baseline = os.path.join(tmp, "baseline.docx")
    parts = with_core_props(with_custom_props(
        docx_parts(), [("ContentTypeId", CONTENT_TYPE_ID),
                       ("QuillBotDocId", "qb-5521"), ("Category", "Reports")]))
    write_zip(original, parts)
    shutil.copy(original, baseline)
    scan_code, _ = run(original)
    out = os.path.join(tmp, "candidate.docx")
    code, _ = run(original, "--clean", "--baseline", baseline, "-o", out)
    kept = (not os.path.exists(out)) or ("QuillBotDocId" in custom_xml(out)
                                         and "qb-5521" in custom_xml(out))
    log = open(log_for(original), encoding="utf-8").read()
    return (scan_code == 2 and code == 2 and kept and "QuillBotDocId" in log
            and "not removed automatically" in log), \
        "scan %s, clean %s, kept %s" % (scan_code, code, kept)


@case("83. a property whose value only names QuillBot is reported and kept (Rev33)")
def case_quillbot_value(tmp):
    original = os.path.join(tmp, "original.xlsx")
    baseline = os.path.join(tmp, "baseline.xlsx")
    parts = with_custom_props(xlsx_with_comment(),
                              [("ContentTypeId", CONTENT_TYPE_ID),
                               ("EditorTool", "QuillBot Paraphraser")])
    write_zip(original, parts)
    shutil.copy(original, baseline)
    out = os.path.join(tmp, "candidate.xlsx")
    code, _ = run(original, "--clean", "--baseline", baseline, "-o", out)
    kept = (not os.path.exists(out)) or "QuillBot Paraphraser" in custom_xml(out)
    return code == 2 and kept, "exit %s, kept %s" % (code, kept)


@case("84. the Grammarly for Word add-in, named only by store id WA200001011, is removed")
def case_grammarly_addin_store_id(tmp):
    scan_code, scan_log, code, out = addin_case(tmp, "wa200001011")
    return (scan_code == 2 and "Grammarly for Microsoft Word" in scan_log
            and code == 0 and no_webext_left(out)), \
        "scan %s, clean %s, gone %s" % (scan_code, code, no_webext_left(out))


@case("85. the QuillBot add-in, named only by store id WA200000368, is removed")
def case_quillbot_addin_store_id(tmp):
    scan_code, scan_log, code, out = addin_case(tmp, "WA200000368")
    return (scan_code == 2 and "QuillBot (Office Store WA200000368)" in scan_log
            and code == 0 and no_webext_left(out)
            and "do not establish generative AI use" in scan_log), \
        "scan %s, clean %s, gone %s" % (scan_code, code, no_webext_left(out))


@case("86. an unrelated add-in store id is preserved untouched")
def case_other_addin_kept(tmp):
    _, scan_log, code, out = addin_case(tmp, "wa104379501")
    kept = "word/webextensions/webextension1.xml" in read_zip(out)
    preserved = "Office web extension, no marker, preserved" in scan_log
    return (code == 0 and kept and preserved
            and "writing-assistant add-in" not in scan_log), \
        "clean %s, kept %s, preserved %s" % (code, kept, preserved)


@case("87. a store id appearing only as a substring is not matched")
def case_store_id_substring(tmp):
    _, scan_log, code, out = addin_case(tmp, "wa2000010119")
    kept = "word/webextensions/webextension1.xml" in read_zip(out)
    preserved = "Office web extension, no marker, preserved" in scan_log
    return (code == 0 and kept and preserved
            and "writing-assistant add-in" not in scan_log), \
        "clean %s, kept %s, preserved %s" % (code, kept, preserved)


@case("88. QuillBot in a descriptive core field is reported, never removed, and fails")
def case_quillbot_title_reported(tmp):
    original = os.path.join(tmp, "original.docx")
    baseline = os.path.join(tmp, "baseline.docx")
    parts = with_core_props(docx_parts())
    parts["docProps/core.xml"] = parts["docProps/core.xml"].decode().replace(
        "</cp:coreProperties>",
        "<dc:title>QuillBot licence review</dc:title></cp:coreProperties>").encode()
    write_zip(original, parts)
    shutil.copy(original, baseline)
    out = os.path.join(tmp, "candidate.docx")
    code, _ = run(original, "--clean", "--baseline", baseline, "-o", out)
    core = read_zip(out).get("docProps/core.xml", b"").decode() if os.path.exists(out) else ""
    kept = "QuillBot licence review" in core or not os.path.exists(out)
    return code == 2 and kept, "exit %s, title kept %s" % (code, kept)


@case("89. browser-extension markup in a text file is reported and the file is untouched")
def case_extension_residue_text(tmp):
    src = os.path.join(tmp, "draft.md")
    body = ('<body data-new-gr-c-s-check-loaded="14.1" data-gr-ext-installed="">'
            '<p>Progress text</p><quillbot-extension-portal></quillbot-extension-portal>'
            '</body>\n')
    with open(src, "w", encoding="utf-8") as f:
        f.write(body)
    before = sha256(src)
    code, _ = run(src)
    log = open(log_for(src), encoding="utf-8").read()
    return (code == 0 and sha256(src) == before
            and "data-new-gr-c-s-check-loaded" in log
            and "data-gr-ext-installed" in log
            and "quillbot-extension-portal" in log
            and "do not establish generative AI use" in log), \
        "exit %s, log %s" % (code, log[:300])


@case("90. QuillBot named in visible content is kept and does not fail")
def case_quillbot_in_content(tmp):
    original = os.path.join(tmp, "original.xlsx")
    baseline = os.path.join(tmp, "baseline.xlsx")
    parts = dict(xlsx_with_comment())
    parts["xl/worksheets/sheet1.xml"] = parts["xl/worksheets/sheet1.xml"].decode().replace(
        '<c r="A1"><v>1</v></c>',
        '<c r="A1" t="inlineStr"><is><t>QuillBot licence</t></is></c>').encode()
    write_zip(original, parts)
    shutil.copy(original, baseline)
    out = os.path.join(tmp, "candidate.xlsx")
    code, _ = run(original, "--clean", "--baseline", baseline, "-o", out)
    kept = b"QuillBot licence" in read_zip(out).get("xl/worksheets/sheet1.xml", b"")
    return code == 0 and kept, "exit %s, content kept %s" % (code, kept)


@case("91. confirmed Grammarly and QuillBot residue is removed together, idempotently")
def case_both_idempotent(tmp):
    # Confirmed residue only: the GrammarlyDocumentId key and the QuillBot add-in
    # identified by its store id. An ambiguous property is covered by 92 to 96.
    original = os.path.join(tmp, "original.docx")
    baseline = os.path.join(tmp, "baseline.docx")
    parts = with_store_addin(grammarly_package(docx_parts()), "wa200000368")
    write_zip(original, parts)
    shutil.copy(original, baseline)
    first = os.path.join(tmp, "first.docx")
    code, _ = run(original, "--clean", "--baseline", baseline, "-o", first)
    b2 = os.path.join(tmp, "b2.docx")
    shutil.copy(first, b2)
    second = os.path.join(tmp, "second.docx")
    code2, _ = run(first, "--clean", "--baseline", b2, "-o", second)
    props = custom_xml(first)
    ok = (code == 0 and code2 == 0 and read_zip(first) == read_zip(second)
          and no_webext_left(first) and "Grammarly" not in props
          and "ContentTypeId" in props)
    return ok, "first %s, second %s, props %s" % (code, code2, props[:200])


# ------------------------------------------------- Rev33, ambiguous properties

def ambiguous_case(tmp, base_parts, ext, props, extra=()):
    original = os.path.join(tmp, "original" + ext)
    baseline = os.path.join(tmp, "baseline" + ext)
    write_zip(original, with_custom_props(base_parts, props))
    shutil.copy(original, baseline)
    out = os.path.join(tmp, "candidate" + ext)
    code, output = run(original, "--clean", "--baseline", baseline, "-o", out, *extra)
    log = open(log_for(original), encoding="utf-8").read()
    return original, out, code, log, output


@case("92. ClientName = QuillBot is kept and reported in .docx, .xlsx and .pptx")
def case_clientname_all_formats(tmp):
    results = {}
    for ext, parts in ((".docx", docx_parts()), (".xlsx", xlsx_with_comment()),
                       (".pptx", pptx_parts())):
        sub = os.path.join(tmp, ext[1:])
        os.mkdir(sub)
        original, out, code, log, output = ambiguous_case(
            sub, parts, ext, [("ClientName", "QuillBot")])
        kept_src = "QuillBot" in custom_xml(original)
        kept_out = (not os.path.exists(out)) or "QuillBot" in custom_xml(out)
        results[ext] = (code == 2 and kept_src and kept_out and "ClientName" in log
                        and "PASS" not in output.split("hygiene result:")[-1][:10])
    return all(results.values()), repr(results)


@case("93. a descriptive property mentioning Grammarly is kept and reported")
def case_descriptive_grammarly(tmp):
    original, out, code, log, _ = ambiguous_case(
        tmp, docx_parts(), ".docx", [("Description", "Grammarly licence renewal file")])
    kept = (not os.path.exists(out)) or "Grammarly licence renewal file" in custom_xml(out)
    return code == 2 and kept and "Description" in log, "exit %s kept %s" % (code, kept)


@case("94. an exact --accept decision lets the run pass and keeps the field")
def case_accept_clientname(tmp):
    original, out, code, log, output = ambiguous_case(
        tmp, docx_parts(), ".docx", [("ClientName", "QuillBot")],
        ("--accept", "docProps/custom.xml|ClientName|QuillBot|A. Reviewer|"
                     "client name, not tool metadata"))
    kept = os.path.exists(out) and "QuillBot" in custom_xml(out)
    return (code == 0 and kept and "A. Reviewer" in log
            and "client name, not tool metadata" in log), \
        "exit %s kept %s: %s" % (code, kept, output[-200:])


@case("95. an acceptance for a different value does not clear the field")
def case_accept_wrong_value(tmp):
    original, out, code, log, _ = ambiguous_case(
        tmp, docx_parts(), ".docx", [("ClientName", "QuillBot")],
        ("--accept", "docProps/custom.xml|ClientName|QuillBot Inc|A. Reviewer|reason"))
    kept = (not os.path.exists(out)) or "QuillBot" in custom_xml(out)
    return code == 2 and kept, "exit %s kept %s" % (code, kept)


@case("96. a name that only contains the integration key is not treated as the key")
def case_key_substring(tmp):
    original, out, code, log, _ = ambiguous_case(
        tmp, docx_parts(), ".docx", [("GrammarlyDocumentIdOld", "x-1"),
                                     ("XGrammarlyDocumentId", "x-2")])
    kept = (not os.path.exists(out)) or ("GrammarlyDocumentIdOld" in custom_xml(out)
                                         and "XGrammarlyDocumentId" in custom_xml(out))
    return code == 2 and kept, "exit %s kept %s" % (code, kept)


@case("97. an accepted field survives a repeated clean unchanged")
def case_accept_idempotent(tmp):
    accept = ("--accept", "docProps/custom.xml|ClientName|QuillBot|A. Reviewer|client")
    original, first, code, _, _ = ambiguous_case(
        tmp, docx_parts(), ".docx", [("ClientName", "QuillBot")], accept)
    b2 = os.path.join(tmp, "b2.docx")
    shutil.copy(first, b2)
    second = os.path.join(tmp, "second.docx")
    code2, _ = run(first, "--clean", "--baseline", b2, "-o", second, *accept)
    return (code == 0 and code2 == 0 and read_zip(first) == read_zip(second)
            and "QuillBot" in custom_xml(second)), "first %s second %s" % (code, code2)



@case("98. recertification applies the same rule: the accepted field passes, unaccepted fails")
def case_recertify_ambiguous(tmp):
    accept = ("--accept", "docProps/custom.xml|ClientName|QuillBot|A. Reviewer|client")
    original, cand, code, _, _ = ambiguous_case(
        tmp, docx_parts(), ".docx", [("ClientName", "QuillBot")], accept)
    baseline = os.path.join(tmp, "baseline.docx")
    cert = log_for(original)
    ok_code, _ = run(cand, "--recertify", "--certificate", cert, "--baseline", baseline,
                     "--log", os.path.join(tmp, "r1.md"), *accept)
    bad_code, _ = run(cand, "--recertify", "--certificate", cert, "--baseline", baseline,
                      "--log", os.path.join(tmp, "r2.md"))
    return code == 0 and ok_code == 0 and bad_code == 2, \
        "clean %s, recertify accepted %s, unaccepted %s" % (code, ok_code, bad_code)


def main():
    if not os.path.exists(SCRIPT):
        print("cannot find %s" % SCRIPT)
        return 1
    failures = 0
    for name, fn in CASES:
        tmp = tempfile.mkdtemp(prefix="deliverytest_")
        try:
            ok, detail = fn(tmp)
        except Exception as e:
            ok, detail = False, "raised %s" % e
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print("%s  %s%s" % ("pass" if ok else "FAIL", name,
                            "" if ok else "  [%s]" % detail))
        failures += 0 if ok else 1
    print("\n%d case(s) run, %d failure(s)" % (len(CASES), failures))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
