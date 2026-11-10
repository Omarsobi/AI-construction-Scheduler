#!/usr/bin/env python3
"""Grammarly and QuillBot handling in Word documents, Fix Language scope.

Identifiable integration residue is removed: the GrammarlyDocumentId key and a
web extension identified by either tool's name or its Office Store id. Any
other property naming either tool is reported, never removed. Visible text,
unrelated add-ins and provenance are left alone, and the existing safeguards
for signatures, baselines and routing still apply.

Fixtures are generated here. No project document is used or shipped.

    python tests/test_writing_assistants.py

Exit status 0 when every case passes, 1 otherwise.
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "metadata_hygiene.py")

from test_annotations import OFF, PKG, docx_with_comment, read_zip, write_zip  # noqa: E402


def xlsx_parts():
    """A minimal but structurally valid workbook (carried from Fix Language's
    test_delivery.py, which is not part of ai-language-fix)."""
    SS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    CT = "http://schemas.openxmlformats.org/package/2006/content-types"
    return {
        "[Content_Types].xml":
            ('<?xml version="1.0"?><Types xmlns="%s">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
             'relationships+xml"/>'
             '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.'
             'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
             '</Types>' % CT).encode(),
        "_rels/.rels":
            ('<?xml version="1.0"?><Relationships xmlns="%s">'
             '<Relationship Id="rId1" Type="%s/officeDocument" Target="xl/workbook.xml"/>'
             '</Relationships>' % (PKG, OFF)).encode(),
        "xl/workbook.xml":
            ('<?xml version="1.0"?><workbook xmlns="%s"><sheets/></workbook>' % SS).encode(),
    }


CUSTOM_NS = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
VT_NS = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
CORE_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC_NS = "http://purl.org/dc/elements/1.1/"
WE_NS = "http://schemas.microsoft.com/office/webextensions/webextension/2010/11"
WETP_NS = "http://schemas.microsoft.com/office/webextensions/taskpanes/2010/11"
WE_REL = "http://schemas.microsoft.com/office/2011/relationships/webextension"
WETP_REL = "http://schemas.microsoft.com/office/2011/relationships/webextensiontaskpanes"
GRAMMARLY_ID = "acb4194c-c9b3-4e83-b7e6-2af8d924da62"
CT_ID = "0x010100AB12CD34EF56"

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def run(*args):
    p = subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    return p.returncode, p.stdout + p.stderr


def log_for(path):
    return os.path.splitext(path)[0] + "_metahygiene.md"


def add_part(parts, name, blob, rel_type, content_type):
    parts = dict(parts)
    parts[name] = blob
    rid = "rId" + name.split("/")[-1].split(".")[0]
    parts["_rels/.rels"] = parts["_rels/.rels"].decode().replace(
        "</Relationships>", '<Relationship Id="%s" Type="%s/%s" Target="%s"/></Relationships>'
        % (rid, OFF, rel_type, name)).encode()
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].decode().replace(
        "</Types>", '<Override PartName="/%s" ContentType="%s"/></Types>'
        % (name, content_type)).encode()
    return parts


def with_props(parts, props):
    body = "".join('<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="%d" '
                   'name="%s"><vt:lpwstr>%s</vt:lpwstr></property>' % (i + 2, n, v)
                   for i, (n, v) in enumerate(props))
    blob = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="%s" '
            'xmlns:vt="%s">%s</Properties>' % (CUSTOM_NS, VT_NS, body)).encode()
    return add_part(parts, "docProps/custom.xml", blob, "custom-properties",
                    "application/vnd.openxmlformats-officedocument.custom-properties+xml")


def with_core(parts):
    blob = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="%s" xmlns:dc="%s"><dc:creator>A. Preparer'
            '</dc:creator><cp:lastModifiedBy>B. Reviewer</cp:lastModifiedBy>'
            '<cp:revision>7</cp:revision></cp:coreProperties>' % (CORE_NS, DC_NS)).encode()
    return add_part(parts, "docProps/core.xml", blob, "metadata/core-properties",
                    "application/vnd.openxmlformats-package.core-properties+xml")


def with_addin(parts, store_id, extra=""):
    """An add-in task pane as Word persists it: the store id, and nothing else
    naming the tool unless extra says so."""
    parts = dict(parts)
    parts["word/webextensions/webextension1.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><we:webextension '
        'xmlns:we="%s" id="{3F2A6C1E-0000-4000-8000-000000000001}"><we:reference id="%s" '
        'version="1.0.0.0" store="en-US" storeType="OMEX"/><we:alternateReferences/>'
        '<we:properties>%s</we:properties><we:bindings/></we:webextension>'
        % (WE_NS, store_id, extra)).encode()
    parts["word/webextensions/taskpanes.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><wetp:taskpanes '
        'xmlns:wetp="%s" xmlns:r="%s"><wetp:taskpane dockstate="right" visibility="0" '
        'width="350" row="0"><wetp:webextensionref r:id="rId1"/></wetp:taskpane>'
        '</wetp:taskpanes>' % (WETP_NS, OFF)).encode()
    parts["word/webextensions/_rels/taskpanes.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="%s">'
        '<Relationship Id="rId1" Type="%s" Target="webextension1.xml"/></Relationships>'
        % (PKG, WE_REL)).encode()
    parts["_rels/.rels"] = parts["_rels/.rels"].decode().replace(
        "</Relationships>", '<Relationship Id="rIdTp" Type="%s" '
        'Target="word/webextensions/taskpanes.xml"/></Relationships>' % WETP_REL).encode()
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].decode().replace(
        "</Types>", '<Override PartName="/word/webextensions/taskpanes.xml" '
        'ContentType="application/vnd.ms-office.webextensiontaskpanes+xml"/>'
        '<Override PartName="/word/webextensions/webextension1.xml" '
        'ContentType="application/vnd.ms-office.webextension+xml"/></Types>').encode()
    return parts


def clean(tmp, parts, name="original.docx"):
    src = os.path.join(tmp, name)
    base = os.path.join(tmp, "baseline" + os.path.splitext(name)[1])
    write_zip(src, parts)
    shutil.copy(src, base)
    scan_code, _ = run(src)
    out = os.path.join(tmp, "candidate" + os.path.splitext(name)[1])
    code, output = run(src, "--clean", "--baseline", base, "-o", out)
    log = open(log_for(src), encoding="utf-8").read() if os.path.exists(log_for(src)) else ""
    return scan_code, code, out, log, output


def custom(path):
    return read_zip(path).get("docProps/custom.xml", b"").decode("utf-8", "replace")


def no_webext(path):
    z = read_zip(path)
    joined = (" ".join(z) + z.get("_rels/.rels", b"").decode()
              + z.get("[Content_Types].xml", b"").decode()).lower()
    return "webextension" not in joined


@case("G1. GrammarlyDocumentId is removed, other properties keep their values, and the run passes")
def g1(tmp):
    parts = with_core(with_props(docx_with_comment(), [("ContentTypeId", CT_ID),
                                                       ("GrammarlyDocumentId", GRAMMARLY_ID),
                                                       ("Category", "Reports")]))
    scan, code, out, log, _ = clean(tmp, parts)
    props = custom(out)
    return (scan == 2 and code == 0 and "GrammarlyDocumentId" not in props
            and GRAMMARLY_ID not in props and CT_ID in props and "Reports" in props
            and "do not establish generative AI use" in log), "scan %s clean %s" % (scan, code)


@case("G2. the Grammarly for Word add-in, named only by store id, is removed with its task pane")
def g2(tmp):
    scan, code, out, log, _ = clean(tmp, with_addin(docx_with_comment(), "wa200001011"))
    return (scan == 2 and code == 0 and no_webext(out)
            and "Grammarly for Microsoft Word" in log), "scan %s clean %s" % (scan, code)


@case("G3. the QuillBot add-in, named only by store id, is removed")
def g3(tmp):
    scan, code, out, log, _ = clean(tmp, with_addin(docx_with_comment(), "WA200000368"))
    return (scan == 2 and code == 0 and no_webext(out)
            and "QuillBot (Office Store WA200000368)" in log), "scan %s clean %s" % (scan, code)


@case("G4. an extension whose own content names QuillBot is removed")
def g4(tmp):
    parts = with_addin(docx_with_comment(), "wa999999999",
                       '<we:property name="service" value="https://quillbot.com/addin"/>')
    scan, code, out, _, _ = clean(tmp, parts)
    return scan == 2 and code == 0 and no_webext(out), "scan %s clean %s" % (scan, code)


@case("G5. an unrelated add-in, and a store id that only contains a listed id, are preserved")
def g5(tmp):
    results = []
    for sid in ("wa104379501", "wa2000010119"):
        sub = os.path.join(tmp, sid)
        os.mkdir(sub)
        _, code, out, log, _ = clean(sub, with_addin(docx_with_comment(), sid))
        results.append(code == 0 and "word/webextensions/webextension1.xml" in read_zip(out)
                       and "writing-assistant add-in" not in log)
    return all(results), repr(results)


@case("G6. a QuillBot-named property is reported for review, kept, and fails pending a decision")
def g6(tmp):
    parts = with_props(docx_with_comment(), [("ContentTypeId", CT_ID),
                                             ("QuillBotDocId", "qb-5521")])
    _, code, out, log, _ = clean(tmp, parts)
    kept = os.path.exists(out) and "QuillBotDocId" in custom(out)
    source_kept = "QuillBotDocId" in custom(os.path.join(tmp, "original.docx"))
    return (code == 2 and source_kept and (kept or not os.path.exists(out))
            and "QuillBotDocId" in log and "not removed automatically" in log), \
        "exit %s kept %s" % (code, kept)


@case("G7. a property whose value only mentions Grammarly is reported, never removed")
def g7(tmp):
    parts = with_props(docx_with_comment(), [("Vendor", "Grammarly Inc licence renewal")])
    _, code, out, log, _ = clean(tmp, parts)
    kept = (not os.path.exists(out)) or "Grammarly Inc licence renewal" in custom(out)
    return code == 2 and kept and "Vendor" in log, "exit %s kept %s" % (code, kept)


@case("G8. visible text naming either company is left unchanged and does not fail the run")
def g8(tmp):
    parts = docx_with_comment(body_text="Grammarly and QuillBot licences were renewed.")
    _, code, out, _, _ = clean(tmp, parts)
    before = read_zip(os.path.join(tmp, "original.docx"))["word/document.xml"]
    after = read_zip(out).get("word/document.xml")
    return code == 0 and before == after, "exit %s same %s" % (code, before == after)


@case("G9. authorship and revision metadata are preserved when residue is removed")
def g9(tmp):
    parts = with_addin(with_core(with_props(docx_with_comment(),
                                            [("GrammarlyDocumentId", GRAMMARLY_ID)])),
                       "wa200001011")
    _, code, out, _, _ = clean(tmp, parts)
    before = read_zip(os.path.join(tmp, "original.docx"))["docProps/core.xml"]
    return code == 0 and read_zip(out).get("docProps/core.xml") == before, "exit %s" % code


@case("G10. a second cleanup of the candidate changes nothing")
def g10(tmp):
    parts = with_addin(with_props(docx_with_comment(), [("ContentTypeId", CT_ID),
                                                        ("GrammarlyDocumentId", GRAMMARLY_ID)]),
                       "wa200000368")
    _, code, first, _, _ = clean(tmp, parts)
    b2 = os.path.join(tmp, "b2.docx")
    shutil.copy(first, b2)
    second = os.path.join(tmp, "second.docx")
    code2, _ = run(first, "--clean", "--baseline", b2, "-o", second)
    return (code == 0 and code2 == 0 and read_zip(first) == read_zip(second)), \
        "first %s second %s" % (code, code2)


@case("G11. a signed package carrying Grammarly residue is still refused, not cleaned")
def g11(tmp):
    parts = with_props(docx_with_comment(), [("GrammarlyDocumentId", GRAMMARLY_ID)])
    parts["_xmlsignatures/sig1.xml"] = b'<?xml version="1.0"?><Signature/>'
    _, code, out, _, output = clean(tmp, parts)
    return code == 2 and not os.path.exists(out), "exit %s: %s" % (code, output[-200:])


@case("G12. a workbook carrying Grammarly residue is cleaned by the shared script "
      "(ai-language-fix Rev1; Fix Language refused it)")
def g12(tmp):
    parts = with_props(xlsx_parts(), [("GrammarlyDocumentId", GRAMMARLY_ID)])
    _, code, out, _, _ = clean(tmp, parts, "book.xlsx")
    ok = code == 0 and os.path.exists(out) and "GrammarlyDocumentId" not in custom(out)
    return ok, "exit %s" % code


@case("G13. ClientName = QuillBot is kept and reported; an exact --accept lets the run pass")
def g13(tmp):
    a = os.path.join(tmp, "a"); b = os.path.join(tmp, "b")
    os.mkdir(a); os.mkdir(b)
    parts = with_props(docx_with_comment(), [("ClientName", "QuillBot")])
    _, code, out, log, _ = clean(a, parts)
    kept = (not os.path.exists(out)) or "QuillBot" in custom(out)
    src = os.path.join(b, "original.docx"); base = os.path.join(b, "baseline.docx")
    write_zip(src, parts); shutil.copy(src, base)
    out2 = os.path.join(b, "candidate.docx")
    code2, _ = run(src, "--clean", "--baseline", base, "-o", out2, "--accept",
                   "docProps/custom.xml|ClientName|QuillBot|A. Reviewer|client name")
    return (code == 2 and kept and "ClientName" in log and code2 == 0
            and "QuillBot" in custom(out2)), "exits %s %s" % (code, code2)


def main():
    if not os.path.exists(SCRIPT):
        print("cannot find %s" % SCRIPT)
        return 1
    failures = 0
    for name, fn in CASES:
        tmp = tempfile.mkdtemp(prefix="watest_")
        try:
            ok, detail = fn(tmp)
        except Exception as e:
            ok, detail = False, "raised %s" % e
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print("%s  %s%s" % ("pass" if ok else "FAIL", name, "" if ok else "  [%s]" % detail))
        failures += 0 if ok else 1
    print("\n%d case(s) run, %d failure(s)" % (len(CASES), failures))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
