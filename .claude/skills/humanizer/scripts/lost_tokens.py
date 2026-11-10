"""List numbers, dates, IDs, references and amounts present in ORIGINAL but
missing from REVISED. Standard library only. Reads .docx/.xlsx/.pptx body
parts and plain text files.

    python3 -I lost_tokens.py ORIGINAL REVISED

Each item printed is either a cut a pattern justified or an error to restore.
It does not see a changed operator (shall to should) or a changed unnumbered
defined term; read the diff_text.py output for those.
"""
import html
import re
import sys
import zipfile

BODY = re.compile(r"(word/(document|header\d*|footer\d*|footnotes|endnotes|comments)"
                  r"|ppt/(slides/slide|notesSlides/notesSlide)\d+"
                  r"|xl/(sharedStrings|worksheets/sheet\d+)|charts/chart\d+)\.xml$")
TOKEN = re.compile(r"[$€£]?[A-Za-z]*\d(?:[\w/:%-]|[.,](?=\w))*")
# Generation artifacts are stripped before tokenizing so the digits inside a
# removed citation token are not reported as lost numbers.
ART = re.compile(r":?contentReference\[oaicite:\d+\]\{index=\d+\}|\[?oaicite:\d+\]?"
                 r"|\[?oai_citation(?:_attribution)?:\d+[^\]\s]{0,60}\]?"
                 r"|\{\"attribution\":\s*\{\"attributableIndex\":\s*\"[^\"\r\n]{0,40}\"\}\}"
                 r"|【\d+(?::\d+)?†[^】\r\n]{1,120}】"
                 r"|(?<![A-Za-z0-9])(?:cite)?turn\d+(?:search|news|view|fetch|image|file)\d+(?![A-Za-z0-9])"
                 r"|[&?]?utm_source=(?:chatgpt\.com|openai)(?![A-Za-z0-9.-])|[\ue200-\ue2ff]")


def _text(xml):
    xml = re.sub(r'<c\b[^>]*\bt="s"[^>]*>.*?</c>|<w:(delText|instrText)\b[^>]*>.*?</w:\1>',
                 "", xml, flags=re.S)
    xml = re.sub(r"</(w:p|a:p|si|c:v|c:pt|row)>", "\n", re.sub(r"</c>", "\t", xml))
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def body(path):
    if not zipfile.is_zipfile(path):
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            return f.read()
    with zipfile.ZipFile(path) as z:
        return "\n".join(_text(z.read(n).decode("utf-8-sig", "replace"))
                         for n in z.namelist() if BODY.search(n))


def lost(original, revised):
    a, b = ART.sub("", body(original)), ART.sub("", body(revised))
    return sorted(set(TOKEN.findall(a)) - set(TOKEN.findall(b)))


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    items = lost(sys.argv[1], sys.argv[2])
    print("Numbers/IDs/dates missing from revised:", ", ".join(items) if items else "none")
    return 1 if items else 0


def _selfcheck():
    assert ART.sub("", "x contentReference[oaicite:2]{index=2} y") == "x  y"
    assert ART.sub("", "a turn0search3 b 【4†source】 c oaicite:4") == "a  b  c "
    assert ART.sub("", "u?rev=3&utm_source=chatgpt.com#s4") == "u?rev=3#s4"
    assert TOKEN.findall("15-May-26 EGC-LTR-0142 0.15% $1,200") == ["15-May-26", "0142", "0.15%", "$1,200"]


if __name__ == "__main__":
    _selfcheck()
    sys.exit(main())
