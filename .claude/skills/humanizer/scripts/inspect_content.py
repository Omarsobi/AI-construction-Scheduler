#!/usr/bin/env python3
"""Report-only pre-delivery inspection of an Office package (AI Fix Rev36).

Two inspections, both read-only:

  1. Embedded image metadata. Every image part in the package is read for
     location, device, identity, software, timestamps and free text, with
     the standard library. Blocks read: JPEG EXIF, XMP, IPTC and comments;
     PNG eXIf, XMP and text chunks; TIFF first-directory EXIF, GPS and XMP
     (tag 700); WebP EXIF and XMP. Blocks recognized but not read (JPEG
     extended XMP, TIFF IPTC tag 33723, TIFF Photoshop resources tag 34377,
     further TIFF image directories, bytes after a WebP container) make the
     inspection incomplete for that image. Any other image or media format
     is reported as not inspected, never as clean.

  2. Revisions and hidden content. Word: tracked insertions, deletions, moves
     and formatting changes, hidden text, hidden drawing objects, styles that
     hide text, and revision tracking switched on. Excel: hidden and very
     hidden sheets, hidden rows and columns, shared-workbook revision logs.
     PowerPoint: hidden slides, hidden shapes and speaker notes.

Nothing is removed, accepted, rejected, revealed or rewritten. A finding is
reported for a decision by the document owner, and it does not by itself
indicate AI use. Report-only findings do not change the hygiene PASS or FAIL
result of metadata_hygiene.py, which calls this module and writes the
findings into its log.

Standalone use, which writes nothing:

    python inspect_content.py file.docx

Every image carries one status: review finding, metadata present, no relevant
metadata found, format not inspected, or inspection incomplete. Completeness
is recorded separately, so an image with findings whose metadata was only
partly read keeps its findings and is still counted as not fully inspected. A
parser that returns nothing is only reported as "no relevant metadata found"
where the format was fully walked.

Standard library only.
"""

import os
import re
import struct
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
import xml.etree.ElementTree as ET
import zipfile
import zlib

# ---------------------------------------------------------------- categories

LOCATION, IDENTITY, DEVICE, SERIAL, SOFTWARE, TIMESTAMP, TEXT = (
    "location", "identity", "device", "unique identifier", "software",
    "timestamp", "free text")

# Categories that can disclose something material on their own. The rest are
# ordinary technical metadata: present, reported, not a concern by themselves.
MATERIAL = {LOCATION, IDENTITY, SERIAL, TEXT}

WHY = {
    LOCATION: "may disclose where the photograph was taken, such as a site location",
    IDENTITY: "names a person or rights holder",
    SERIAL: "uniquely identifies a device or image",
    TEXT: "free text whose content cannot be assessed automatically",
    DEVICE: "ordinary device information",
    SOFTWARE: "ordinary software information; not an indication of AI use",
    TIMESTAMP: ("capture or edit time; may be legitimate project evidence and is "
                "preserved"),
}

EXIF_IFD0 = {
    0x010E: (TEXT, "ImageDescription"), 0x010F: (DEVICE, "Make"),
    0x0110: (DEVICE, "Model"), 0x0131: (SOFTWARE, "Software"),
    0x0132: (TIMESTAMP, "DateTime"), 0x013B: (IDENTITY, "Artist"),
    0x013C: (SERIAL, "HostComputer"), 0x8298: (IDENTITY, "Copyright"),
    0x000B: (SOFTWARE, "ProcessingSoftware"), 0x9C9B: (TEXT, "XPTitle"),
    0x9C9C: (TEXT, "XPComment"), 0x9C9D: (IDENTITY, "XPAuthor"),
    0x9C9E: (TEXT, "XPKeywords"), 0x9C9F: (TEXT, "XPSubject"),
}
EXIF_SUB = {
    0x9003: (TIMESTAMP, "DateTimeOriginal"), 0x9004: (TIMESTAMP, "DateTimeDigitized"),
    0x9286: (TEXT, "UserComment"), 0xA430: (IDENTITY, "CameraOwnerName"),
    0xA431: (SERIAL, "BodySerialNumber"), 0xA433: (DEVICE, "LensMake"),
    0xA434: (DEVICE, "LensModel"), 0xA435: (SERIAL, "LensSerialNumber"),
    0xA420: (SERIAL, "ImageUniqueID"),
}
GPS_TAGS = {
    0x0001: "GPSLatitudeRef", 0x0002: "GPSLatitude", 0x0003: "GPSLongitudeRef",
    0x0004: "GPSLongitude", 0x0005: "GPSAltitudeRef", 0x0006: "GPSAltitude",
    0x0007: "GPSTimeStamp", 0x001D: "GPSDateStamp",
}

IPTC = {
    80: (IDENTITY, "By-line"), 85: (IDENTITY, "By-line Title"),
    110: (IDENTITY, "Credit"), 116: (IDENTITY, "Copyright Notice"),
    118: (IDENTITY, "Contact"), 120: (TEXT, "Caption"), 25: (TEXT, "Keywords"),
    105: (TEXT, "Headline"), 55: (TIMESTAMP, "Date Created"),
    60: (TIMESTAMP, "Time Created"), 90: (LOCATION, "City"),
    92: (LOCATION, "Sub-location"), 95: (LOCATION, "Province-State"),
    100: (LOCATION, "Country Code"), 101: (LOCATION, "Country"),
    115: (IDENTITY, "Source"),
}

NS_EXIF = "http://ns.adobe.com/exif/1.0/"
NS_EXIFEX = "http://cipa.jp/exif/1.0/"
NS_AUX = "http://ns.adobe.com/exif/1.0/aux/"
NS_TIFF = "http://ns.adobe.com/tiff/1.0/"
NS_XMP = "http://ns.adobe.com/xap/1.0/"
NS_DC = "http://purl.org/dc/elements/1.1/"
NS_PS = "http://ns.adobe.com/photoshop/1.0/"
NS_IPTCCORE = "http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/"
NS_RIGHTS = "http://ns.adobe.com/xap/1.0/rights/"
NS_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

XMP_MAP = {
    (NS_EXIF, "GPSLatitude"): LOCATION, (NS_EXIF, "GPSLongitude"): LOCATION,
    (NS_EXIF, "GPSAltitude"): LOCATION,
    (NS_EXIF, "DateTimeOriginal"): TIMESTAMP, (NS_EXIF, "DateTimeDigitized"): TIMESTAMP,
    (NS_EXIF, "UserComment"): TEXT,
    (NS_EXIFEX, "BodySerialNumber"): SERIAL, (NS_EXIFEX, "LensSerialNumber"): SERIAL,
    (NS_EXIFEX, "CameraOwnerName"): IDENTITY, (NS_AUX, "SerialNumber"): SERIAL,
    (NS_AUX, "LensSerialNumber"): SERIAL, (NS_AUX, "OwnerName"): IDENTITY,
    (NS_TIFF, "Make"): DEVICE, (NS_TIFF, "Model"): DEVICE,
    (NS_TIFF, "Artist"): IDENTITY, (NS_TIFF, "Copyright"): IDENTITY,
    (NS_TIFF, "Software"): SOFTWARE, (NS_TIFF, "DateTime"): TIMESTAMP,
    (NS_TIFF, "ImageDescription"): TEXT,
    (NS_XMP, "CreatorTool"): SOFTWARE, (NS_XMP, "CreateDate"): TIMESTAMP,
    (NS_XMP, "ModifyDate"): TIMESTAMP, (NS_XMP, "MetadataDate"): TIMESTAMP,
    (NS_DC, "creator"): IDENTITY, (NS_DC, "rights"): IDENTITY,
    (NS_DC, "title"): TEXT, (NS_DC, "description"): TEXT, (NS_DC, "subject"): TEXT,
    (NS_PS, "City"): LOCATION, (NS_PS, "State"): LOCATION, (NS_PS, "Country"): LOCATION,
    (NS_PS, "AuthorsPosition"): IDENTITY, (NS_PS, "Credit"): IDENTITY,
    (NS_PS, "DateCreated"): TIMESTAMP, (NS_PS, "Headline"): TEXT,
    (NS_IPTCCORE, "Location"): LOCATION, (NS_IPTCCORE, "CountryCode"): LOCATION,
    (NS_IPTCCORE, "CreatorContactInfo"): IDENTITY,
    (NS_RIGHTS, "Owner"): IDENTITY,
}

PNG_TEXT = {
    "author": IDENTITY, "copyright": IDENTITY, "software": SOFTWARE,
    "creation time": TIMESTAMP, "description": TEXT, "comment": TEXT,
    "title": TEXT, "source": DEVICE, "disclaimer": TEXT, "warning": TEXT,
}


class Incomplete(Exception):
    """The format was recognized but could not be walked to its end."""


class Coordinates:
    """A GPS position in signed decimal degrees (south and west negative).
    Either axis may be missing. The report only ever shows it rounded."""

    def __init__(self, lat=None, lon=None):
        self.lat, self.lon = lat, lon

    def rounded(self):
        if self.lat is not None and self.lon is not None:
            return "%.2f, %.2f (rounded)" % (self.lat, self.lon)
        return "%.2f (rounded)" % (self.lat if self.lat is not None else self.lon)

    def __repr__(self):
        return "Coordinates(%s)" % self.rounded()


class Withheld:
    """A value whose presence is reported but which could not be interpreted
    safely, so it is not shown at all."""

    def __init__(self, reason):
        self.reason = reason

    def __repr__(self):
        return "Withheld(%s)" % self.reason


# XMP GPS forms (Exif-in-XMP): "DDD,MM,SSk" or "DDD,MM[.mm]k", k = N, S, E or W.
XMP_COORD = re.compile(r"^(\d{1,3}),(\d{1,2})(?:(\.\d+)|,(\d{1,2}(?:\.\d+)?))?([NSEW])$")


def xmp_coordinate(value, axis):
    """Signed decimal degrees from an XMP GPS value, or Withheld. axis is
    "lat" or "lon"; the direction letter must belong to that axis."""
    m = XMP_COORD.match("".join(str(value).split()).upper())
    if not m:
        return Withheld("coordinate format not recognized")
    deg, mins, frac, secs, k = m.groups()
    if (axis == "lat" and k not in "NS") or (axis == "lon" and k not in "EW"):
        return Withheld("direction does not match the coordinate")
    minutes = float(mins + (frac or ""))
    seconds = float(secs) if secs is not None else 0.0
    if minutes >= 60 or seconds >= 60:
        return Withheld("minutes or seconds out of range")
    d = int(deg) + minutes / 60 + seconds / 3600
    if d > (90 if axis == "lat" else 180):
        return Withheld("coordinate out of range")
    return Coordinates(lat=-d if k == "S" else d) if axis == "lat" \
        else Coordinates(lon=-d if k == "W" else d)


# ---------------------------------------------------------------- helpers

def safe_value(category, value):
    """What the report shows. Serial numbers are shortened, and long values
    are cut at 60 characters: the finding needs to be recognizable, and the
    log should not become a second copy of the sensitive value.

    Coordinate handling applies only to fields the metadata schema defines as
    GPS coordinates (the EXIF GPS directory, XMP exif:GPSLatitude and
    exif:GPSLongitude). Their parsers pass a Coordinates value, shown only
    rounded, or a Withheld value, never shown raw. Every other location field
    (city, state, country, location, sub-location and the like) is free text
    and is shown as text, whatever numbers or punctuation it contains; it is
    never read as a coordinate (Rev36)."""
    if isinstance(value, Coordinates):
        return value.rounded()
    if isinstance(value, Withheld):
        return "value withheld (%s)" % value.reason
    v = " ".join(str(value).split())
    if category == SERIAL and len(v) > 4:
        return "ending ...%s" % v[-4:]
    return v if len(v) <= 60 else v[:57] + "..."


def classify_image(items, status):
    if status in ("not inspected", "incomplete"):
        return status
    if any(cat in MATERIAL for cat, _, _ in items):
        return "review"
    return "present" if items else "none"


# ---------------------------------------------------------------- TIFF / EXIF

TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}


def _ifd(data, off, bo):
    if off < 0 or off + 2 > len(data):
        raise Incomplete("IFD offset outside the EXIF block")
    n = struct.unpack(bo + "H", data[off:off + 2])[0]
    if off + 2 + 12 * n > len(data):
        raise Incomplete("IFD runs past the end of the EXIF block")
    out = {}
    for i in range(n):
        e = off + 2 + 12 * i
        tag, typ, count = struct.unpack(bo + "HHI", data[e:e + 8])
        size = TYPE_SIZE.get(typ)
        if size is None:
            continue
        total = size * count
        if total <= 4:
            raw = data[e + 8:e + 8 + total]
        else:
            vo = struct.unpack(bo + "I", data[e + 8:e + 12])[0]
            if vo + total > len(data):
                raise Incomplete("tag 0x%04X points outside the EXIF block" % tag)
            raw = data[vo:vo + total]
        out[tag] = (typ, count, raw)
    return out


def _decode(typ, count, raw, bo, tag=0):
    if tag in (0x9C9B, 0x9C9C, 0x9C9D, 0x9C9E, 0x9C9F):
        return raw.decode("utf-16-le", "replace").rstrip("\x00")
    if tag == 0x9286 and len(raw) >= 8:
        body = raw[8:]
        enc = "utf-16-le" if raw[:8].startswith(b"UNICODE") else "latin-1"
        return body.decode(enc, "replace").strip("\x00 ")
    if typ == 2 or typ == 7:
        return raw.split(b"\x00")[0].decode("utf-8", "replace").strip()
    if typ in (3, 4, 9):
        fmt = {3: "H", 4: "I", 9: "i"}[typ]
        vals = struct.unpack(bo + fmt * count, raw)
        return vals[0] if count == 1 else vals
    if typ in (5, 10):
        fmt = "II" if typ == 5 else "ii"
        vals = struct.unpack(bo + fmt * count, raw)
        return tuple(vals[i] / vals[i + 1] if vals[i + 1] else 0.0
                     for i in range(0, len(vals), 2))
    return raw


# First-directory TIFF tags that carry metadata blocks this module does not
# read. Their presence makes the inspection of that image incomplete.
TIFF_UNREAD = {33723: "IPTC in TIFF tag 33723 (not parsed)",
               34377: "Photoshop resources in TIFF tag 34377 (not parsed)"}


def parse_tiff(data, items=None, sources=None):
    """Metadata items from a TIFF structure (an EXIF block or a TIFF image),
    appended to items as they are read so that a later failure keeps them.
    Reads the first directory, its EXIF and GPS sub-directories and XMP in
    tag 700; records blocks it recognizes but does not read in sources."""
    items = [] if items is None else items
    sources = [] if sources is None else sources
    if len(data) < 8 or data[:2] not in (b"II", b"MM"):
        raise Incomplete("TIFF header not recognized")
    bo = "<" if data[:2] == b"II" else ">"
    if struct.unpack(bo + "H", data[2:4])[0] != 42:
        raise Incomplete("TIFF magic number missing")
    ifd0 = _ifd(data, struct.unpack(bo + "I", data[4:8])[0], bo)
    for tag, (cat, name) in EXIF_IFD0.items():
        if tag in ifd0:
            v = _decode(*ifd0[tag], bo=bo, tag=tag)
            if v not in ("", None, b""):
                items.append((cat, name, v))
    if 0x8769 in ifd0:
        sub = _ifd(data, _decode(*ifd0[0x8769], bo=bo), bo)
        for tag, (cat, name) in EXIF_SUB.items():
            if tag in sub:
                v = _decode(*sub[tag], bo=bo, tag=tag)
                if v not in ("", None, b""):
                    items.append((cat, name, v))
    if 0x8825 in ifd0:
        gps = _ifd(data, _decode(*ifd0[0x8825], bo=bo), bo)
        g = {GPS_TAGS[t]: _decode(*gps[t], bo=bo) for t in gps if t in GPS_TAGS}
        if "GPSLatitude" in g and "GPSLongitude" in g:
            def deg(v, ref, neg):
                d = v[0] + v[1] / 60 + v[2] / 3600 if isinstance(v, tuple) and len(v) == 3 \
                    else float(v[0] if isinstance(v, tuple) else v)
                return -d if str(ref).upper().startswith(neg) else d
            try:
                pos = Coordinates(deg(g["GPSLatitude"], g.get("GPSLatitudeRef", "N"), "S"),
                                  deg(g["GPSLongitude"], g.get("GPSLongitudeRef", "E"), "W"))
            except (TypeError, ValueError, IndexError):
                pos = Withheld("GPS coordinate could not be interpreted")
            items.append((LOCATION, "GPS position", pos))
        elif g:
            items.append((LOCATION, "GPS data", ", ".join(sorted(g))))
        if "GPSDateStamp" in g:
            items.append((TIMESTAMP, "GPSDateStamp", g["GPSDateStamp"]))
    if 700 in ifd0:
        parse_xmp(ifd0[700][2], items)
        sources.append("XMP (TIFF tag 700)")
    for tag, label in TIFF_UNREAD.items():
        if tag in ifd0:
            sources.append(label)
    return items


def inspect_tiff(b, items, sources):
    """A TIFF image: its first directory is read by parse_tiff. Further image
    directories (pages) are recognized but not read."""
    parse_tiff(b, items, sources)
    sources.insert(0, "EXIF")
    bo = "<" if b[:2] == b"II" else ">"
    off = struct.unpack(bo + "I", b[4:8])[0]
    n = struct.unpack(bo + "H", b[off:off + 2])[0]
    nxt = b[off + 2 + 12 * n:off + 6 + 12 * n]
    if len(nxt) < 4:
        raise Incomplete("TIFF first directory has no next-directory pointer")
    if struct.unpack(bo + "I", nxt)[0]:
        sources.append("further TIFF image directories (not parsed)")


# ---------------------------------------------------------------- XMP / IPTC

XMP_GPS = {"GPSLatitude": "lat", "GPSLongitude": "lon"}


def parse_xmp(blob, items=None):
    items = [] if items is None else items
    m = re.search(rb"<x:xmpmeta.*?</x:xmpmeta>|<rdf:RDF.*?</rdf:RDF>", blob, re.S)
    if not m:
        raise Incomplete("XMP packet not found in the XMP segment")
    try:
        root = ET.fromstring(m.group(0))
    except ET.ParseError as e:
        raise Incomplete("XMP packet will not parse (%s)" % e)

    def qname(tag):
        return tuple(tag[1:].split("}", 1)) if tag.startswith("{") else ("", tag)

    def value_of(q, text):
        # GPS coordinates are parsed with their direction, or withheld
        if q[0] == NS_EXIF and q[1] in XMP_GPS:
            return xmp_coordinate(text, XMP_GPS[q[1]])
        return text

    for el in root.iter():
        for key, value in el.attrib.items():
            cat = XMP_MAP.get(qname(key))
            if cat and value.strip():
                items.append((cat, qname(key)[1], value_of(qname(key), value.strip())))
        cat = XMP_MAP.get(qname(el.tag))
        if cat:
            text = " ".join(t.strip() for t in el.itertext() if t.strip())
            if text:
                items.append((cat, qname(el.tag)[1], value_of(qname(el.tag), text)))
    return items


def parse_iptc(seg):
    """IPTC IIM records inside a Photoshop APP13 segment."""
    items = []
    i = seg.find(b"8BIM")
    found = False
    while 0 <= i < len(seg) - 12:
        rid = struct.unpack(">H", seg[i + 4:i + 6])[0]
        nlen = seg[i + 6]
        p = i + 7 + nlen
        if (nlen + 1) % 2:
            p += 1
        if p + 4 > len(seg):
            raise Incomplete("Photoshop resource block truncated")
        size = struct.unpack(">I", seg[p:p + 4])[0]
        data = seg[p + 4:p + 4 + size]
        if len(data) < size:
            raise Incomplete("IPTC resource truncated")
        if rid == 0x0404:
            found = True
            j = 0
            while j + 5 <= len(data) and data[j] == 0x1C:
                rec, ds, ln = data[j + 1], data[j + 2], struct.unpack(">H", data[j + 3:j + 5])[0]
                val = data[j + 5:j + 5 + ln]
                if rec == 2 and ds in IPTC:
                    cat, name = IPTC[ds]
                    txt = val.decode("utf-8", "replace").strip()
                    if txt:
                        items.append((cat, "IPTC " + name, txt))
                j += 5 + ln
        i = seg.find(b"8BIM", p + 4 + size + (size % 2))
    return items, found


# ---------------------------------------------------------------- formats

# Each inspector appends to the items and sources lists it is given, so that
# what was read before a failure is kept. A source ending "(not parsed)" is a
# block that was recognized but not read.

def inspect_jpeg(b, items, sources):
    i = 2
    while i < len(b):
        if b[i] != 0xFF:
            raise Incomplete("JPEG marker expected at byte %d" % i)
        while i < len(b) and b[i] == 0xFF:
            i += 1
        if i >= len(b):
            raise Incomplete("JPEG ended inside a marker")
        marker = b[i]
        i += 1
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            continue
        if marker in (0xD9, 0xDA):
            return
        if i + 2 > len(b):
            raise Incomplete("JPEG segment length missing")
        ln = struct.unpack(">H", b[i:i + 2])[0]
        seg = b[i + 2:i + ln]
        if ln < 2 or len(seg) < ln - 2:
            raise Incomplete("JPEG segment runs past the end of the image")
        if marker == 0xE1 and seg.startswith(b"Exif\x00\x00"):
            parse_tiff(seg[6:], items, sources); sources.append("EXIF")
        elif marker == 0xE1 and seg.startswith(b"http://ns.adobe.com/xap/1.0/\x00"):
            parse_xmp(seg, items); sources.append("XMP")
        elif marker == 0xE1 and seg.startswith(b"http://ns.adobe.com/xmp/extension/\x00"):
            if "extended XMP (not parsed)" not in sources:
                sources.append("extended XMP (not parsed)")
        elif marker == 0xED and seg.startswith(b"Photoshop 3.0\x00"):
            found, ok = parse_iptc(seg)
            items += found
            if ok:
                sources.append("IPTC")
        elif marker == 0xFE:
            txt = seg.decode("utf-8", "replace").strip("\x00 ")
            if txt:
                items.append((TEXT, "JPEG comment", txt)); sources.append("COM")
        i += ln
    raise Incomplete("JPEG ended before the image data")


def inspect_png(b, items, sources):
    i = 8
    while i + 8 <= len(b):
        ln = struct.unpack(">I", b[i:i + 4])[0]
        typ = b[i + 4:i + 8]
        data = b[i + 8:i + 8 + ln]
        if len(data) < ln or i + 12 + ln > len(b):
            raise Incomplete("PNG chunk %r runs past the end of the image" % typ)
        if typ == b"eXIf":
            parse_tiff(data, items, sources); sources.append("EXIF")
        elif typ in (b"tEXt", b"zTXt", b"iTXt"):
            key, _, rest = data.partition(b"\x00")
            k = key.decode("latin-1", "replace")
            try:
                if typ == b"zTXt":
                    txt = zlib.decompress(rest[1:]).decode("latin-1", "replace")
                elif typ == b"iTXt":
                    flag = rest[0]
                    rest = rest[2:]
                    _, _, rest = rest.partition(b"\x00")
                    _, _, rest = rest.partition(b"\x00")
                    txt = (zlib.decompress(rest) if flag else rest).decode("utf-8", "replace")
                else:
                    txt = rest.decode("latin-1", "replace")
            except (zlib.error, IndexError) as e:
                raise Incomplete("PNG text chunk %s will not decode (%s)" % (k, e))
            if k == "XML:com.adobe.xmp":
                parse_xmp(txt.encode("utf-8"), items); sources.append("XMP")
            elif txt.strip():
                cat = PNG_TEXT.get(k.lower(), TEXT)
                items.append((cat, "PNG " + k, txt.strip())); sources.append("text")
        elif typ == b"IEND":
            return
        i += 12 + ln
    raise Incomplete("PNG ended before its IEND chunk")


def inspect_webp(b, items, sources):
    """RIFF container: the declared size bounds the walk, and every chunk
    header, payload and padding byte must lie inside it and inside the bytes
    actually present."""
    if len(b) < 12:
        raise Incomplete("WebP header truncated")
    end = 8 + struct.unpack("<I", b[4:8])[0]
    short = ("; the container declares %d bytes but %d are present" % (end, len(b))
             if end > len(b) else "")
    limit = min(end, len(b))
    if end < 12:
        raise Incomplete("WebP container size %d is smaller than its header" % end)
    i = 12
    while i < limit:
        if i + 8 > limit:
            raise Incomplete("WebP chunk header at byte %d is incomplete%s" % (i, short))
        typ = b[i:i + 4]
        ln = struct.unpack("<I", b[i + 4:i + 8])[0]
        if i + 8 + ln > limit:
            raise Incomplete("WebP chunk %r at byte %d runs past the end of the %s%s"
                             % (typ, i, "available data" if short else "container", short))
        if ln % 2 and i + 9 + ln > limit:
            raise Incomplete("WebP chunk %r at byte %d is missing its padding byte%s"
                             % (typ, i, short))
        data = b[i + 8:i + 8 + ln]
        if typ == b"EXIF":
            parse_tiff(data[6:] if data.startswith(b"Exif\x00\x00") else data, items, sources)
            sources.append("EXIF")
        elif typ == b"XMP ":
            parse_xmp(data, items); sources.append("XMP")
        i += 8 + ln + (ln % 2)
    if short:
        raise Incomplete("WebP data ends at byte %d%s" % (len(b), short))
    if len(b) > end:
        sources.append("%d byte(s) after the WebP container (not parsed)" % (len(b) - end))


def sniff(b):
    if b[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if b[:4] in (b"II*\x00", b"MM\x00*"):
        return "TIFF"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "WebP"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "GIF"
    if b[:2] == b"BM":
        return "BMP"
    if b[40:44] == b" EMF":
        return "EMF"
    if b[:4] == b"\xd7\xcd\xc6\x9a" or b[:4] == b"\x01\x00\x09\x00":
        return "WMF"
    if b[4:8] == b"ftyp":
        return "HEIF/AVIF or MP4 family"
    head = b[:200].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in b[:1000].lower()):
        return "SVG"
    return None


INSPECTORS = {"JPEG": inspect_jpeg, "PNG": inspect_png, "WebP": inspect_webp,
              "TIFF": inspect_tiff}

MEDIA_PART = re.compile(r"(^|/)media/|(^|/)thumbnail\.[a-z0-9]+$", re.I)


def image_parts(parts):
    out = []
    for name in sorted(parts):
        if name.endswith("/") or name.lower().endswith((".xml", ".rels")):
            continue
        data = parts[name]
        if MEDIA_PART.search(name) or sniff(data) in INSPECTORS:
            out.append(name)
    return out


def inspect_images(parts):
    """One record per image or media part: part, format, status, items, note
    and complete. status says what was found; complete says whether all of
    the image's metadata was read. They are independent: an image can carry
    a review finding and still be incomplete."""
    results = []
    for name in image_parts(parts):
        data = parts[name]
        fmt = sniff(data)
        rec = {"part": name, "format": fmt or "unrecognized", "items": [], "note": "",
               "complete": False}
        if fmt not in INSPECTORS:
            rec["status"] = "not inspected"
            rec["note"] = ("%s format is not parsed by this inspection, so its metadata was "
                           "not read" % (fmt or "unrecognized"))
            results.append(rec)
            continue
        items, sources, error = [], [], None
        try:
            INSPECTORS[fmt](data, items, sources)
        except Incomplete as e:
            error = str(e)
        except (struct.error, IndexError, ValueError) as e:
            # the exception text can carry a raw metadata value, so only its type is shown
            error = "the %s structure could not be read (%s)" % (fmt, type(e).__name__)
        read = [s for s in sources if not s.endswith("(not parsed)")]
        unread = [s[:-len(" (not parsed)")] for s in sources if s.endswith("(not parsed)")]
        notes = []
        if error:
            notes.append("inspection could not be completed: %s" % error)
            if read:
                notes.append("read before the failure: " + ", ".join(read))
        elif read:
            notes.append("metadata blocks read: " + ", ".join(read))
        elif not unread:
            notes.append("no EXIF, IPTC or XMP block present")
        if unread:
            notes.append("present but not read: " + ", ".join(unread))
        rec["items"] = items
        rec["note"] = "; ".join(notes)
        rec["complete"] = not error and not unread
        rec["status"] = classify_image(items, "ok")
        if not rec["complete"] and rec["status"] == "none":
            rec["status"] = "incomplete"
        results.append(rec)
    return results


def fully_inspected(rec):
    return rec.get("complete", rec["status"] not in ("not inspected", "incomplete"))


# ---------------------------------------------------------------- revisions and hidden content

W_NS = {"http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "http://purl.oclc.org/ooxml/wordprocessingml/main"}
WP_NS = {"http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
         "http://purl.oclc.org/ooxml/drawingml/wordprocessingDrawing"}
SS_NS = {"http://schemas.openxmlformats.org/spreadsheetml/2006/main",
         "http://purl.oclc.org/ooxml/spreadsheetml/main"}
P_NS = {"http://schemas.openxmlformats.org/presentationml/2006/main",
        "http://purl.oclc.org/ooxml/presentationml/main"}
A_NS = {"http://schemas.openxmlformats.org/drawingml/2006/main",
        "http://purl.oclc.org/ooxml/drawingml/main"}

WORKING, UNINTENDED, UNCLASSIFIED = (
    "working-state information", "potentially unintended issued content",
    "cannot be conclusively classified")

TEXT_REVISIONS = ("ins", "del", "moveFrom", "moveTo", "cellIns", "cellDel")
FORMAT_REVISIONS = ("rPrChange", "pPrChange", "sectPrChange", "tblPrChange",
                    "trPrChange", "tcPrChange", "tblGridChange", "numberingChange",
                    "cellMerge")

WORD_TEXT_PART = re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")


def split(tag):
    if isinstance(tag, str) and tag.startswith("{"):
        uri, local = tag[1:].split("}", 1)
        return uri, local
    return "", tag if isinstance(tag, str) else ""


def is_el(el, local, uris):
    uri, name = split(el.tag)
    return name == local and uri in uris


def wattr(el, local):
    for k, v in el.attrib.items():
        uri, name = split(k)
        if name == local and (uri in W_NS or uri == ""):
            return v
    return None


def on(el):
    v = wattr(el, "val")
    return v is None or v.lower() not in ("0", "false", "off")


def excerpt(el, local_names=("t", "delText")):
    txt = "".join(e.text or "" for e in el.iter()
                  if split(e.tag)[1] in local_names and split(e.tag)[0] in W_NS)
    txt = " ".join(txt.split())
    return txt if len(txt) <= 60 else txt[:57] + "..."


def word_findings(parts, problems):
    out = []
    shown_runs = 0          # runs whose own properties switch hiding off
    for name in sorted(parts):
        if not WORD_TEXT_PART.match(name):
            continue
        try:
            root = ET.fromstring(parts[name])
        except ET.ParseError as e:
            problems.append("%s will not parse (%s); it was not inspected" % (name, e))
            continue
        para_index = {}
        for i, p in enumerate((el for el in root.iter() if is_el(el, "p", W_NS)), 1):
            for d in p.iter():
                para_index[d] = i      # a nested text-box paragraph overwrites its parent
        revisions, authors, formatting = [], set(), 0
        for el in root.iter():
            uri, local = split(el.tag)
            if uri not in W_NS:
                continue
            if local in TEXT_REVISIONS:
                a = wattr(el, "author")
                if a:
                    authors.add(a)
                revisions.append((local, para_index.get(el), excerpt(el)))
            elif local in FORMAT_REVISIONS:
                formatting += 1
                a = wattr(el, "author")
                if a:
                    authors.add(a)
        for kind, para, text in revisions:
            label = {"ins": "tracked insertion", "del": "tracked deletion",
                     "moveFrom": "tracked move (from)", "moveTo": "tracked move (to)",
                     "cellIns": "tracked table cell insertion",
                     "cellDel": "tracked table cell deletion"}[kind]
            out.append((label, "%s paragraph %s" % (name, para or "?"),
                        WORKING, "the owner accepts or rejects it before issue",
                        text))
        if formatting:
            out.append(("tracked formatting changes (%d)" % formatting, name, WORKING,
                        "the owner accepts or rejects them before issue", ""))
        if authors:
            out.append(("revision authors recorded: " + ", ".join(sorted(authors)), name,
                        WORKING, "these names travel with the file until the revisions are "
                                 "resolved", ""))
        # hidden text: run properties only, never the old properties inside a change record
        for r in root.iter():
            if not is_el(r, "r", W_NS):
                continue
            for rpr in r:
                if not is_el(rpr, "rPr", W_NS):
                    continue
                for v in rpr:
                    if is_el(v, "vanish", W_NS) and on(v):
                        out.append(("hidden text", "%s paragraph %s"
                                    % (name, para_index.get(r, "?")), UNINTENDED,
                                    "the owner reviews it and decides whether it is deleted, "
                                    "shown or kept", excerpt(r)))
                    elif is_el(v, "vanish", W_NS):
                        shown_runs += 1
                # ai-language-fix Rev3: white text. Report only. The run's own
                # shading or highlight is read; paragraph, cell and page
                # backgrounds are not, so the owner checks the background.
                vals = {}
                for v in rpr:
                    for key in ("color", "shd", "highlight"):
                        if is_el(v, key, W_NS):
                            vals[key] = {k.rsplit("}", 1)[-1]: (a or "").upper()
                                         for k, a in v.attrib.items()}
                white = vals.get("color", {}).get("val") == "FFFFFF"
                dark_fill = vals.get("shd", {}).get("fill", "AUTO") not in ("AUTO", "FFFFFF", "")
                lit = vals.get("highlight", {}).get("val", "NONE") not in ("NONE", "WHITE", "")
                if white and not dark_fill and not lit and excerpt(r).strip():
                    out.append(("white text, possibly invisible on a white background",
                                "%s paragraph %s" % (name, para_index.get(r, "?")), UNINTENDED,
                                "the owner checks the background and decides whether it is "
                                "deleted, shown or kept", excerpt(r)))
        for d in root.iter():
            if is_el(d, "docPr", WP_NS) and (d.get("hidden") or "").lower() in ("1", "true"):
                out.append(("hidden drawing object: %s" % (d.get("name") or d.get("id") or "?"),
                            "%s paragraph %s" % (name, para_index.get(d, "?")), UNINTENDED,
                            "the owner reviews the object and decides", ""))
    if "word/styles.xml" in parts:
        try:
            root = ET.fromstring(parts["word/styles.xml"])
            # document defaults: text that sets nothing else inherits them
            default_hidden = any(
                is_el(v, "vanish", W_NS) and on(v)
                for dd in root if is_el(dd, "docDefaults", W_NS)
                for rd in dd if is_el(rd, "rPrDefault", W_NS)
                for rpr in rd if is_el(rpr, "rPr", W_NS)
                for v in rpr)
            if default_hidden:
                shown_styles = sorted(
                    wattr(st, "styleId") or "?" for st in root.iter()
                    if is_el(st, "style", W_NS)
                    and any(is_el(rpr, "rPr", W_NS) and any(is_el(v, "vanish", W_NS)
                                                            and not on(v) for v in rpr)
                            for rpr in st))
                out.append((
                    "document default formatting hides text (w:docDefaults/w:rPrDefault/"
                    "w:rPr/w:vanish)", "word/styles.xml", UNCLASSIFIED,
                    "the owner checks which text inherits this default and is therefore "
                    "hidden; explicit settings that switch hiding off were found in %d "
                    "style(s)%s and %d run(s); which text is actually hidden was not resolved"
                    % (len(shown_styles), (" (%s)" % ", ".join(shown_styles[:10])
                                           + (" ..." if len(shown_styles) > 10 else ""))
                       if shown_styles else "", shown_runs), ""))
            for st in root.iter():
                if not is_el(st, "style", W_NS):
                    continue
                for rpr in st:
                    if is_el(rpr, "rPr", W_NS) and any(is_el(v, "vanish", W_NS) and on(v)
                                                       for v in rpr):
                        out.append(("style hides its text: %s" % (wattr(st, "styleId") or "?"),
                                    "word/styles.xml", UNCLASSIFIED,
                                    "the owner checks whether any text uses this style", ""))
        except ET.ParseError as e:
            problems.append("word/styles.xml will not parse (%s); styles were not inspected" % e)
    if "word/settings.xml" in parts:
        try:
            root = ET.fromstring(parts["word/settings.xml"])
            if any(is_el(e, "trackRevisions", W_NS) and on(e) for e in root.iter()):
                out.append(("revision tracking is switched on", "word/settings.xml", WORKING,
                            "the owner switches it off before issue if new edits should not "
                            "be tracked", ""))
        except ET.ParseError as e:
            problems.append("word/settings.xml will not parse (%s); settings were not "
                            "inspected" % e)
    return out


def excel_findings(parts, problems):
    out = []
    if "xl/workbook.xml" in parts:
        try:
            root = ET.fromstring(parts["xl/workbook.xml"])
            for s in root.iter():
                if is_el(s, "sheet", SS_NS):
                    state = s.get("state") or "visible"
                    if state == "hidden":
                        out.append(("hidden sheet: %s" % s.get("name"), "xl/workbook.xml",
                                    UNCLASSIFIED, "the owner confirms whether the sheet "
                                    "belongs in the issued workbook", ""))
                    elif state == "veryHidden":
                        out.append(("very hidden sheet: %s" % s.get("name"), "xl/workbook.xml",
                                    UNINTENDED, "the owner reviews the sheet; it cannot be "
                                    "unhidden from the Excel interface", ""))
        except ET.ParseError as e:
            problems.append("xl/workbook.xml will not parse (%s); sheets were not inspected" % e)
    for name in sorted(parts):
        if re.match(r"^xl/worksheets/[^/]+\.xml$", name):
            try:
                root = ET.fromstring(parts[name])
            except ET.ParseError as e:
                problems.append("%s will not parse (%s); it was not inspected" % (name, e))
                continue
            rows = [r.get("r") for r in root.iter() if is_el(r, "row", SS_NS)
                    and (r.get("hidden") or "").lower() in ("1", "true")]
            cols = ["%s-%s" % (c.get("min"), c.get("max")) for c in root.iter()
                    if is_el(c, "col", SS_NS) and (c.get("hidden") or "").lower() in ("1", "true")]
            if rows:
                out.append(("hidden rows (%d): %s" % (len(rows), ", ".join(rows[:10])
                                                      + (" ..." if len(rows) > 10 else "")),
                            name, UNCLASSIFIED, "the owner confirms the hidden rows hold "
                            "nothing that should not be issued", ""))
            if cols:
                out.append(("hidden columns (%d): column ranges %s" % (len(cols), ", ".join(cols[:10])),
                            name, UNCLASSIFIED, "the owner confirms the hidden columns hold "
                            "nothing that should not be issued", ""))
    revs = [n for n in parts if n.startswith("xl/revisions/") and not n.endswith("/")]
    if revs:
        out.append(("shared-workbook revision history (%d part(s))" % len(revs), "xl/revisions/",
                    WORKING, "the owner decides whether the change history is issued", ""))
    return out


def powerpoint_findings(parts, problems):
    out = []
    for name in sorted(parts):
        if re.match(r"^ppt/slides/slide\d+\.xml$", name):
            try:
                root = ET.fromstring(parts[name])
            except ET.ParseError as e:
                problems.append("%s will not parse (%s); it was not inspected" % (name, e))
                continue
            if (root.get("show") or "").lower() in ("0", "false"):
                out.append(("hidden slide", name, UNINTENDED,
                            "the owner decides whether the slide belongs in the issued deck", ""))
            for c in root.iter():
                if split(c.tag)[1] == "cNvPr" and split(c.tag)[0] in P_NS | A_NS \
                        and (c.get("hidden") or "").lower() in ("1", "true"):
                    out.append(("hidden shape: %s" % (c.get("name") or c.get("id") or "?"),
                                name, UNINTENDED, "the owner reviews the shape and decides", ""))
        elif re.match(r"^ppt/notesSlides/notesSlide\d+\.xml$", name):
            try:
                root = ET.fromstring(parts[name])
            except ET.ParseError as e:
                problems.append("%s will not parse (%s); it was not inspected" % (name, e))
                continue
            texts = [t.text for t in root.iter() if is_el(t, "t", A_NS) and t.text
                     and t.text.strip() and not t.text.strip().isdigit()]
            if texts:
                out.append(("speaker notes", name, UNCLASSIFIED,
                            "the owner confirms the notes may travel with the deck",
                            " ".join(" ".join(texts).split())[:57]))
    return out


def inspect_revisions(parts, ptype):
    """(findings, problems). Each finding: (type, location, classification,
    recommended review action, excerpt)."""
    problems = []
    if ptype == "docx":
        return word_findings(parts, problems), problems
    if ptype == "xlsx":
        return excel_findings(parts, problems), problems
    if ptype == "pptx":
        return powerpoint_findings(parts, problems), problems
    return [], ["%s is not an Office package this inspection supports" % ptype]


# ---------------------------------------------------------------- report

STATUS_LABEL = {
    "review": "review finding", "present": "metadata present, no material concern by itself",
    "none": "inspected, no relevant metadata found", "not inspected": "format not inspected",
    "incomplete": "inspection incomplete",
}


def report_lines(images, revisions, problems, comments_present=False):
    lines = ["", "## Pre-delivery review findings (report only)", "",
             "Nothing in this section was removed, accepted, rejected, revealed or changed. "
             "Each item is for the document owner to decide; removal or any other change needs "
             "an explicit instruction. None of these findings is evidence of AI use, and they "
             "do not change the hygiene result above.", "",
             "### Embedded image metadata", ""]
    if not images:
        lines.append("- no image or media parts in the package")
    for rec in images:
        label = STATUS_LABEL[rec["status"]]
        if rec["status"] in ("review", "present") and not fully_inspected(rec):
            label += "; inspection incomplete"
        lines.append("- %s (%s): %s. %s" % (rec["part"], rec["format"], label, rec["note"]))
        for cat, field, value in rec["items"]:
            flag = "REVIEW" if cat in MATERIAL else "present"
            lines.append("    - [%s] %s, %s = %s; %s" % (flag, cat, field,
                                                         safe_value(cat, value), WHY[cat]))
    counts = {}
    for rec in images:
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1
    partial = [r for r in images if not fully_inspected(r)]
    with_findings = sum(1 for r in partial if r["status"] in ("review", "present"))
    lines += ["", "Images: %d part(s); review findings %d, metadata present %d, none found %d, "
              "not inspected %d, incomplete %d. Not fully inspected: %d, of which %d also "
              "have findings listed above."
              % (len(images), counts.get("review", 0), counts.get("present", 0),
                 counts.get("none", 0), counts.get("not inspected", 0),
                 counts.get("incomplete", 0), len(partial), with_findings)]
    lines += ["", "### Revisions and hidden content", ""]
    for kind, loc, cls, action, text in revisions:
        lines.append("- %s at %s: %s. Recommended review: %s.%s"
                     % (kind, loc, cls, action, (' Text: "%s"' % text) if text else ""))
    if comments_present:
        lines.append("- comments are present; they are governed by the annotation rule and "
                     "listed under Comments above")
    for p in problems:
        lines.append("- INSPECTION INCOMPLETE: %s" % p)
    if not revisions and not problems and not comments_present:
        lines.append("- inspected, none found")
    return lines


def summary(images, revisions, problems):
    review = sum(1 for r in images if r["status"] == "review")
    partial = sum(1 for r in images if not fully_inspected(r))
    return ("review findings (report only): %d image(s) needing review, %d image(s) not fully "
            "inspected, %d revision or hidden-content finding(s)%s"
            % (review, partial, len(revisions),
               ", inspection incomplete" if problems else ""))


def main():
    if len(sys.argv) != 2:
        print("usage: python inspect_content.py FILE.docx|FILE.xlsx|FILE.pptx")
        return 2
    path = sys.argv[1]
    try:
        with zipfile.ZipFile(path) as z:
            parts = {n: z.read(n) for n in z.namelist()}
    except (zipfile.BadZipFile, OSError) as e:
        print("cannot open %s as an Office package: %s" % (path, e))
        return 2
    ptype = ("docx" if "word/document.xml" in parts else "xlsx" if "xl/workbook.xml" in parts
             else "pptx" if "ppt/presentation.xml" in parts else "unknown")
    images = inspect_images(parts)
    revisions, problems = inspect_revisions(parts, ptype)
    print("\n".join(report_lines(images, revisions, problems)))
    print(summary(images, revisions, problems))
    return 0


if __name__ == "__main__":
    sys.exit(main())
