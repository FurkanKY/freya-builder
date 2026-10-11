"""A case folder's documents as plain text, whatever their format, without crashing on any file.

collect(paths, work_dir) reads folders, single files and zips. Word, Excel and PowerPoint files are read with zipfile and
ElementTree, PDFs with pdftotext, and legacy office formats are first converted by LibreOffice inside work_dir.
"""
import base64
import hashlib
import html
import math
import os
import posixpath
import re
import shutil
import signal
import subprocess
import tempfile
import unicodedata
import zipfile
import zlib
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from decimal import Decimal
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

IMAGE_KINDS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tif", "tiff", "heic", "ico"}
# LibreOffice turns these into a format read below.
LEGACY = {"doc": "docx", "dot": "docx", "rtf": "docx", "odt": "docx", "xls": "xlsx", "xlsb": "xlsx", "ods": "xlsx",
          "ppt": "pptx", "pps": "pptx", "odp": "pptx", "odg": "pdf", "vsd": "pdf", "vsdx": "pdf"}
OOXML_TARGET = {"docx": "docx", "docm": "docx", "dotx": "docx", "xlsx": "xlsx", "xlsm": "xlsx", "pptx": "pptx",
                "pptm": "pptx", "ppsx": "pptx"}
JUNK = {".ds_store", "thumbs.db", "desktop.ini", "__macosx"}
MAX_FILE_BYTES = 50 * 2**20
ZIP_MAX_BYTES = 300 * 2**20
ZIP_MAX_MEMBERS = 5000
MAX_DEPTH = 3
TIMEOUT = 120
REL_NS = ("http://schemas.openxmlformats.org/officeDocument/2006/relationships",
          "http://purl.oclc.org/ooxml/officeDocument/relationships")


class Skip(Exception):
    """A file left out of the documents; the message is the reason."""


def collect(paths, work_dir):
    """(documents, skipped) from folders, files and zips: BRIEF.md first, README.md second, then by path."""
    if isinstance(paths, (str, os.PathLike)):
        paths = [paths]
    collector = _Collector(Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="documents-")))
    for path in paths:
        try:
            collector.add(Path(path))
        except Exception as exc:  # one bad input must not lose the others
            collector.skip(str(path), f"could not read: {type(exc).__name__}: {exc}")
    return collector.finish()


def convert(path, kind, work_dir):
    """The text of one file by its extension; raises Skip when it has none to give."""
    path = Path(path)
    if kind in OOXML_TARGET:
        if not zipfile.is_zipfile(path):  # an old binary file saved with a new extension
            return legacy_office(path, kind, work_dir, OOXML_TARGET[kind])
        return CONVERTERS[OOXML_TARGET[kind]](path)
    if kind == "pdf":
        return pdf_text(path)
    if kind in LEGACY:
        return legacy_office(path, kind, work_dir, LEGACY[kind])
    if kind in IMAGE_KINDS and kind != "png":
        raise Skip("image")
    data = path.read_bytes()
    if kind == "png":
        embedded = _png_drawio(data)
        if not embedded:
            raise Skip("image")
        return "[PNG image with an embedded draw.io diagram]\n\n" + drawio_text(embedded)
    # Everything else (md, txt, csv, json, yaml, xml, mmd, puml, unknown extensions) is read as text.
    if _binary(data):
        raise Skip(f"binary file, not text (.{kind or 'no extension'})")
    text = decode(data)
    if kind in ("html", "htm"):
        return re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", "", text, flags=re.I | re.S)
    if kind == "drawio" or (kind == "xml" and text.lstrip().startswith(("<mxfile", "<mxGraphModel"))):
        return drawio_text(text)
    if kind == "svg":
        return svg_text(text)
    return text


def _binary(data):
    return b"\x00" in data[:4096] and not data.startswith((b"\xff\xfe", b"\xfe\xff"))


def decode(data):
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    # utf-8-sig reads plain utf-8 too; cp1254 is Turkish Windows.
    for encoding in ("utf-8-sig", "cp1254"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1")


def normalize(text):
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = "\n".join(line.rstrip() for line in text.lstrip("\ufeff").split("\n"))
    return re.sub(r"\n{4,}", "\n\n\n", text).strip("\n")


class _Collector:
    def __init__(self, work_dir):
        self.work_dir = work_dir
        self.found, self.skipped = [], []
        self.zip_bytes = 0

    def skip(self, path, reason):
        self.skipped.append({"path": path, "reason": reason})

    def add(self, path):
        if not path.exists():
            self.skip(str(path), "not found")
        elif path.is_dir():
            self.walk(path, "", False, 0)
        elif path.suffix.lower() == ".zip":
            root = self.unzip(path, path.name)
            if root:
                self.walk(_single_folder(root), "", False, 1)
        else:
            self.file(path, path.name, False, 0)

    def walk(self, root, prefix, archived, depth):
        for folder, dirs, files in os.walk(root):
            rel = Path(folder).relative_to(root).as_posix()
            base = prefix + ("" if rel == "." else rel + "/")
            keep = []
            for name in sorted(dirs):
                if _junk(name):
                    self.skip(base + name + "/", "hidden or system folder")
                elif os.path.islink(os.path.join(folder, name)):
                    self.skip(base + name + "/", "symbolic link")
                elif Path(folder, name).resolve() == self.work_dir.resolve():
                    continue  # our own extractions, read through their archives
                else:
                    keep.append(name)
            dirs[:] = keep
            for name in sorted(files):
                full = Path(folder) / name
                if _junk(name):
                    self.skip(base + name, "hidden or system file")
                elif full.is_symlink():
                    self.skip(base + name, "symbolic link")
                elif not full.is_file():
                    self.skip(base + name, "not a regular file")
                else:
                    self.file(full, base + name, archived, depth)

    def file(self, path, rel, archived, depth):
        kind = path.suffix.lower().lstrip(".")
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                raise Skip(f"larger than {MAX_FILE_BYTES // 2**20} MB")
            if kind == "zip":
                if depth >= MAX_DEPTH:
                    raise Skip("archive nested too deep")
                root = self.unzip(path, rel)
                if root:
                    self.walk(root, rel + "/", True, depth + 1)
                return
            if kind == "eml":
                data = path.read_bytes()
                if _binary(data):
                    raise Skip("binary file, not text (.eml)")
                text, attachments = eml_text(data)
                self.keep(rel, kind, text, archived)
                for name, payload in attachments:
                    self.attachment(rel, name, payload, depth)
                return
            text = convert(path, kind, self.work_dir)
        except Skip as exc:
            return self.skip(rel, str(exc))
        except Exception as exc:  # a broken file must not stop the others
            return self.skip(rel, f"could not read the {kind or 'file'}: {type(exc).__name__}: {exc}")
        self.keep(rel, kind, text, archived)

    def keep(self, rel, kind, text, archived):
        text = normalize(text)
        if not text.strip():
            return self.skip(rel, "no text")
        self.found.append({"path": rel, "kind": kind, "text": text, "archived": archived,
                           "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})

    def attachment(self, rel, name, payload, depth):
        where = f"{rel}/{name}"
        if depth >= MAX_DEPTH:
            return self.skip(where, "attachment nested too deep")
        folder = Path(tempfile.mkdtemp(prefix="mail-", dir=_mkdir(self.work_dir / "attachments")))
        target = folder / name
        target.write_bytes(payload)
        self.file(target, where, True, depth + 1)

    def unzip(self, path, rel):
        """Extract a zip into a new folder under work_dir, refusing unsafe members; the folder or None."""
        try:
            archive = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as exc:
            self.skip(rel, f"not a readable zip: {exc}")
            return None
        folder = Path(tempfile.mkdtemp(prefix=_slug(path.stem) + "-", dir=_mkdir(self.work_dir / "unzipped")))
        with archive:
            infos = archive.infolist()
            if len(infos) > ZIP_MAX_MEMBERS:
                self.skip(rel, f"more than {ZIP_MAX_MEMBERS} files in the archive")
                return None
            reported = set()
            for info in infos:
                name = _member_name(info)
                where = f"{rel}/{name}"
                parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
                if name.endswith(("/", "\\")):
                    continue
                if name.startswith(("/", "\\")) or re.match(r"[A-Za-z]:", name) or ".." in parts or not parts:
                    self.skip(where, "unsafe path in the archive, not extracted")
                    continue
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    self.skip(where, "symbolic link in the archive, not extracted")
                    continue
                junk = next((i for i, part in enumerate(parts) if _junk(part)), None)
                if junk is not None:
                    top = "/".join(parts[:junk + 1]) + ("/" if junk < len(parts) - 1 else "")
                    if top not in reported:
                        reported.add(top)
                        self.skip(f"{rel}/{top}", "hidden or system " + ("folder" if top.endswith("/") else "file"))
                    continue
                if info.flag_bits & 0x1:
                    self.skip(where, "encrypted in the archive")
                    continue
                limit = min(MAX_FILE_BYTES, ZIP_MAX_BYTES - self.zip_bytes)
                target = folder.joinpath(*parts)
                if not _inside(target, folder):
                    self.skip(where, "unsafe path in the archive, not extracted")
                    continue
                try:
                    if info.file_size > limit:
                        raise Skip("too large to extract (size cap)")
                    with archive.open(info) as source:
                        data = source.read(limit + 1)
                    if len(data) > limit:  # the header lied about the size
                        raise Skip("too large to extract (size cap)")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    self.zip_bytes += len(data)
                except Exception as exc:
                    self.skip(where, str(exc) if isinstance(exc, Skip) else f"could not extract: {exc}")
        return folder

    def finish(self):
        # Identical texts are kept once: the copy outside any archive, else the first in reading order.
        kept, first = [], {}
        for doc in sorted(self.found, key=lambda d: (d["archived"], _order_key(d["path"]))):
            if doc["sha256"] in first:
                self.skip(doc["path"], f"same text as {first[doc['sha256']]}")
            else:
                first[doc["sha256"]] = doc["path"]
                kept.append(doc)
        kept.sort(key=lambda d: _order_key(d["path"]))
        documents, seen = [], {}
        for doc in kept:
            path = doc["path"]
            seen[path] = seen.get(path, 0) + 1
            if seen[path] > 1:  # the same relative path from two inputs
                path = f"{path} ({seen[path]})"
            documents.append({"path": path, "kind": doc["kind"], "text": doc["text"], "sha256": doc["sha256"]})
        return documents, self.skipped


def _order_key(path):
    name = path.rsplit("/", 1)[-1].lower()
    rank = {"brief.md": 0, "readme.md": 1}.get(name, 2)
    parts = re.split(r"(\d+)", path)
    natural = [int(p) if i % 2 else p.casefold() for i, p in enumerate(parts)]
    return rank, path.count("/") if rank < 2 else 0, natural, path


def _junk(name):
    return name.startswith((".", "~$")) or name.lower() in JUNK


def _mkdir(path):
    path.mkdir(parents=True, exist_ok=True)
    return path


def _slug(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text)[:40].strip("-.") or "archive"


def _inside(target, folder):
    try:
        target.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def _single_folder(root):
    """A zip that wraps everything in one folder is read from inside that folder."""
    entries = [e for e in root.iterdir() if not _junk(e.name)]
    return entries[0] if len(entries) == 1 and entries[0].is_dir() and not entries[0].is_symlink() else root


def _member_name(info):
    """Zips made without the UTF-8 flag store names in the maker's code page (macOS UTF-8, Turkish Windows cp857)."""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        raw = info.filename.encode("cp437")
    except UnicodeEncodeError:
        return info.filename
    for encoding in ("utf-8", "cp857"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return info.filename


def _tail(data):
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data or "")
    return " ".join(text.split())[-300:] or "no message"


# --- XML helpers -----------------------------------------------------------------------------------------------------

def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _children(el):
    return list(el) if el is not None else []


def _kids(el, *names):
    return [c for c in _children(el) if _local(c.tag) in names]


def _kid(el, name):
    return next((c for c in _children(el) if _local(c.tag) == name), None)


def _attr(el, name, default=None):
    if el is not None:
        for key, value in el.attrib.items():
            if _local(key) == name:
                return value
    return default


def _rid(el, name="id"):
    for ns in REL_NS:
        value = el.get(f"{{{ns}}}{name}") if el is not None else None
        if value:
            return value
    return None


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class _Package:
    """An OOXML zip: parts by case-insensitive name and their relationships."""

    def __init__(self, path):
        self.zip = zipfile.ZipFile(path)
        self.parts = {info.filename.lower(): info for info in self.zip.infolist()}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.zip.close()

    def xml(self, name):
        info = self.parts.get(name.lower()) if name else None
        if info is None:
            return None
        if info.file_size > 4 * MAX_FILE_BYTES:
            raise Skip(f"part {name} is too large")
        return ET.fromstring(self.zip.read(info))

    def rels(self, part):
        folder, base = posixpath.split(part)
        found = {}
        for rel in _children(self.xml(posixpath.join(folder, "_rels", base + ".rels"))):
            target = rel.get("Target") or ""
            if rel.get("TargetMode") == "External":
                continue
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
            found[rel.get("Id")] = (rel.get("Type") or "", target)
        return found

    def main(self, default):
        return next((t for kind, t in self.rels("").values() if kind.endswith("/officeDocument")), default)


def _related(rels, kind, default=None):
    return next((target for rel, target in rels.values() if rel.endswith("/" + kind)), default)


def _pipe_table(rows, keep_empty=False):
    rows = [[" ".join(str(c).replace("\n", " / ").replace("|", "\\|").split()) for c in row] for row in rows]
    rows = [row for row in rows if keep_empty or any(row)]
    width = max((len(row) for row in rows), default=0)
    if width == 1:
        return "\n".join(row[0] for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    lines = ["| " + " | ".join(row) + " |" for row in rows]
    if lines:
        lines.insert(1, "|" + "---|" * width)
    return "\n".join(lines)


def _diagram_texts(root):
    """The node texts of a SmartArt data part."""
    texts = []
    for pt in (root.iter() if root is not None else []):
        if _local(pt.tag) != "pt" or _attr(pt, "type", "node") not in ("node", "asst"):
            continue
        body = _kid(pt, "t")
        paras = ["".join(t.text or "" for t in p.iter() if _local(t.tag) == "t")
                 for p in (body.iter() if body is not None else []) if _local(p.tag) == "p"]
        text = " ".join(" ".join(paras).split())
        if text:
            texts.append(text)
    return texts


# --- Word ------------------------------------------------------------------------------------------------------------

NOTE_TYPES = ("separator", "continuationSeparator", "continuationNotice")
RUN_SKIP = {"pPr", "rPr", "sdtPr", "sdtEndPr", "del", "delText", "moveFrom", "instrText", "Fallback", "fldChar", "sym"}
BLOCK_CONTAINERS = {"sdt", "sdtContent", "customXml", "ins", "moveTo", "smartTag", "AlternateContent", "Choice"}


def docx_text(path):
    with _Package(path) as pkg:
        return _Word(pkg).text()


class _Word:
    def __init__(self, pkg):
        self.pkg = pkg
        self.part = pkg.main("word/document.xml")
        self.rels = self.pkg.rels(self.part)
        self.styles = _word_styles(self.pkg.xml(_related(self.rels, "styles", "word/styles.xml")))
        self.abstract, self.nums = _word_numbering(self.pkg.xml(_related(self.rels, "numbering", "word/numbering.xml")))
        self.counters, self.started, self.pending = {}, set(), []

    def text(self):
        document = self.pkg.xml(self.part)
        if document is None:
            raise Skip("not a Word document")
        sections = [_render(self.blocks(_kid(document, "body")))]
        notes = []
        for kind, mark in (("footnotes", "^"), ("endnotes", "^e")):
            for note in _children(self.pkg.xml(_related(self.rels, kind, f"word/{kind}.xml"))):
                text = " ".join(_flat(self.blocks(note))) if _attr(note, "type") not in NOTE_TYPES else ""
                if text:
                    notes.append(f"[{mark}{_attr(note, 'id')}]: {text}")
        if notes:
            sections.append("## Footnotes\n\n" + "\n".join(notes))
        comments = []
        for comment in _children(self.pkg.xml(_related(self.rels, "comments", "word/comments.xml"))):
            text = " / ".join(_flat(self.blocks(comment)))
            if text:
                comments.append(f"- [comment {_attr(comment, 'id')}] {_attr(comment, 'author') or 'unknown'}: {text}")
        if comments:
            sections.append("## Comments\n\n" + "\n".join(comments))
        extra = []
        for target in sorted(t for kind, t in self.rels.values() if kind.endswith(("/header", "/footer"))):
            text = _render(self.blocks(self.pkg.xml(target)))
            # A page number or a logo alone is not worth a section.
            if re.search(r"[^\W\d_]", re.sub(r"\[image[^\]]*\]", "", text)) and text not in extra:
                extra.append(text)
        if extra:
            sections.append("## Headers and footers\n\n" + "\n\n".join(extra))
        return "\n\n".join(s for s in sections if s)

    def blocks(self, container):
        """(kind, prefix, text) in document order; a table's text is its rows."""
        out = []
        for el in _children(container):
            name = _local(el.tag)
            if name == "p":
                block = self.paragraph(el)
                if block:
                    out.append(block)
            elif name == "tbl":
                out.append(("table", "", self.table(el)))
            elif name in BLOCK_CONTAINERS:
                out += self.blocks(el)
            out += [("box", "[text box] ", text) for text in self.pending]
            self.pending = []
        return out

    def paragraph(self, p):
        ppr = _kid(p, "pPr")
        style = _attr(_kid(ppr, "pStyle"), "val")
        label, ilvl = self.list_label(ppr, style) or (None, 0)  # counted even when the paragraph is empty, as Word does
        text = "".join(self.runs(p)).strip()
        if not text:
            return None
        level = self.heading_level(ppr, style)
        if level:
            return "h", "#" * level + " " + (label + " " if label and label != "-" else ""), text
        if label:
            return "li", "  " * ilvl + ("- " if label == "-" else label + " "), text
        return "p", "", text

    def runs(self, el):
        for child in el:
            name = _local(child.tag)
            if name in RUN_SKIP:
                continue
            if name == "t":
                yield child.text or ""
            elif name in ("tab", "ptab"):
                yield "\t"
            elif name in ("br", "cr"):
                yield "\n"
            elif name == "noBreakHyphen":
                yield "-"
            elif name == "txbxContent":
                self.box(child)
            elif name == "footnoteReference":
                yield f"[^{_attr(child, 'id')}]"
            elif name == "endnoteReference":
                yield f"[^e{_attr(child, 'id')}]"
            elif name == "commentReference":
                yield f"[comment {_attr(child, 'id')}]"
            elif name == "object":
                yield "[embedded object]"
            elif name == "relIds":
                texts = _diagram_texts(self.pkg.xml(self.rels.get(_rid(child, "dm"), ("", None))[1]))
                yield f" [diagram: {' / '.join(texts)}] " if texts else ""
            elif name == "drawing":
                if any(_local(e.tag) == "pic" for e in child.iter()):
                    doc_pr = next((e for e in child.iter() if _local(e.tag) == "docPr"), None)
                    alt = (_attr(doc_pr, "descr") or _attr(doc_pr, "title") or "").strip()
                    yield f"[image: {alt}]" if alt else "[image]"
                yield from self.runs(child)
            else:
                yield from self.runs(child)

    def box(self, content):
        """A text box's text, shown after its paragraph. Word stores most boxes twice, as DrawingML and as a VML
        mc:Fallback; the fallback is never read, so each box comes once."""
        saved, self.pending = self.pending, []
        text = " / ".join(_flat(self.blocks(content)))
        self.pending = saved
        if text:
            self.pending.append(text)

    def table(self, tbl):
        rows, above = [], {}
        for tr in _kids(tbl, "tr"):
            row, current = [], {}
            row += [""] * _int(_attr(_kid(_kid(tr, "trPr"), "gridBefore"), "val"), 0)
            for tc in _row_cells(tr):
                tcpr = _kid(tc, "tcPr")
                span = max(1, _int(_attr(_kid(tcpr, "gridSpan"), "val"), 1))
                merge = _kid(tcpr, "vMerge")
                # A vertically merged cell repeats the text above so each row reads alone.
                if merge is not None and _attr(merge, "val") != "restart":
                    text = above.get(len(row), "")
                else:
                    text = " / ".join(_flat(self.blocks(tc)))
                current[len(row)] = text
                row += [text] + [""] * (span - 1)
            rows.append(row)
            above = current
        return rows

    def heading_level(self, ppr, style):
        own = _int(_attr(_kid(ppr, "outlineLvl"), "val"), None)
        if own is not None:
            return own + 1 if own < 6 else 0
        for _ in range(10):
            if not style:
                break
            info = self.styles.get(style, {})
            level = _heading_name(info.get("name")) or _heading_name(style)
            if level:
                return level
            if info.get("outline") is not None:
                return info["outline"] + 1 if info["outline"] < 6 else 0
            style = info.get("based")
        return 0

    def list_label(self, ppr, style):
        """('-' or the number Word shows, level) for a list paragraph, else None."""
        numpr = _kid(ppr, "numPr")
        num_id, ilvl = _attr(_kid(numpr, "numId"), "val"), _attr(_kid(numpr, "ilvl"), "val")
        sid = style
        for _ in range(10):
            if num_id is not None or not sid:
                break
            info = self.styles.get(sid, {})
            if info.get("num"):
                num_id, ilvl = info["num"][0], ilvl if ilvl is not None else info["num"][1]
            sid = info.get("based")
        if not num_id or num_id == "0":
            return None
        abstract_id, starts, overrides = self.nums.get(num_id, (None, {}, {}))
        levels = {**self.abstract.get(abstract_id, {}), **overrides}
        if ilvl is None:
            ilvl = next((i for i, lvl in levels.items() if style and lvl["style"] == style), 0)
        ilvl = _int(ilvl, 0)
        counters = self.counters.setdefault(abstract_id or "num " + num_id, {})
        if num_id not in self.started:
            self.started.add(num_id)
            counters.update({i: start - 1 for i, start in starts.items()})
        level = levels.get(ilvl, {"fmt": "bullet", "text": None, "start": 1, "legal": False, "style": None})
        counters[ilvl] = counters.get(ilvl, level["start"] - 1) + 1
        for deeper in [i for i in counters if i > ilvl]:
            del counters[deeper]
        if level["fmt"] == "bullet" or not level["text"]:
            return "-", ilvl

        def number(match):
            i = int(match.group(1)) - 1
            lvl = levels.get(i, {"fmt": "decimal", "start": 1})
            return _format_number(counters.get(i, lvl["start"]), "decimal" if level["legal"] else lvl["fmt"])
        return re.sub(r"%([1-9])", number, level["text"]).strip() or "-", ilvl


def _row_cells(tr):
    for child in tr:
        name = _local(child.tag)
        if name == "tc":
            yield child
        elif name in ("sdt", "sdtContent", "customXml"):
            yield from _row_cells(child)


def _word_styles(root):
    styles = {}
    for style in _kids(root, "style"):
        ppr = _kid(style, "pPr")
        numpr = _kid(ppr, "numPr")
        styles[_attr(style, "styleId")] = {
            "name": _attr(_kid(style, "name"), "val", ""),
            "based": _attr(_kid(style, "basedOn"), "val"),
            "outline": _int(_attr(_kid(ppr, "outlineLvl"), "val"), None),
            "num": (_attr(_kid(numpr, "numId"), "val"), _attr(_kid(numpr, "ilvl"), "val")) if numpr is not None else None,
        }
    return styles


def _word_level(lvl):
    return {"fmt": _attr(_kid(lvl, "numFmt"), "val", "decimal"), "text": _attr(_kid(lvl, "lvlText"), "val"),
            "start": _int(_attr(_kid(lvl, "start"), "val"), 1), "legal": _kid(lvl, "isLgl") is not None,
            "style": _attr(_kid(lvl, "pStyle"), "val")}


def _word_numbering(root):
    abstract, nums = {}, {}
    for el in _children(root):
        name = _local(el.tag)
        if name == "abstractNum":
            abstract[_attr(el, "abstractNumId")] = {_int(_attr(lvl, "ilvl"), 0): _word_level(lvl)
                                                    for lvl in _kids(el, "lvl")}
        elif name == "num":
            starts, overrides = {}, {}
            for override in _kids(el, "lvlOverride"):
                ilvl = _int(_attr(override, "ilvl"), 0)
                start = _kid(override, "startOverride")
                if start is not None:
                    starts[ilvl] = _int(_attr(start, "val"), 1)
                if _kid(override, "lvl") is not None:
                    overrides[ilvl] = _word_level(_kid(override, "lvl"))
            nums[_attr(el, "numId")] = (_attr(_kid(el, "abstractNumId"), "val"), starts, overrides)
    return abstract, nums


def _heading_name(name):
    name = (name or "").strip().lower().replace("\u0307", "").translate(str.maketrans("ışğ", "isg"))
    match = re.fullmatch(r"(?:heading|baslik|balk)\s*([1-6])", name)
    if match:
        return int(match.group(1))
    return 1 if name in ("title", "baslik", "konubal", "konu basligi") else 0


def _format_number(n, fmt):
    if fmt in ("lowerLetter", "upperLetter") and n > 0:
        letters = chr(ord("a") + (n - 1) % 26) * ((n - 1) // 26 + 1)
        return letters.upper() if fmt == "upperLetter" else letters
    if fmt in ("lowerRoman", "upperRoman") and 0 < n < 4000:
        roman = ""
        for value, letters in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"),
                               (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
            count, n = divmod(n, value)
            roman += letters * count
        return roman if fmt == "upperRoman" else roman.lower()
    if fmt == "decimalZero":
        return f"{n:02d}"
    return "" if fmt == "none" else str(n)


def _flat(blocks):
    """Blocks as single lines, for a table cell, a note or a text box."""
    out = []
    for kind, prefix, text in blocks:
        if kind == "table":
            out += ["; ".join(c for c in row if c) for row in text]
        elif kind == "li" and prefix.strip() != "-" or kind == "box":
            out.append(prefix.strip() + " " + text)
        else:
            out.append(text)
    return [line for line in out if line.strip()]


def _render(blocks):
    out, previous = [], None
    for kind, prefix, text in blocks:
        if kind == "table":
            text = _pipe_table(text)
        if not text:
            continue
        if out:
            out.append("\n" if kind == previous and kind in ("li", "box") else "\n\n")
        out.append(prefix + text)
        previous = kind
    return "".join(out)


# --- Excel -----------------------------------------------------------------------------------------------------------

# Built-in number formats that matter for reading: percentages, dates and times.
BUILTIN_FORMATS = {9: "0%", 10: "0.00%", 14: "yyyy-mm-dd", 15: "d-mmm-yy", 16: "d-mmm", 17: "mmm-yy", 18: "h:mm AM/PM",
                   19: "h:mm:ss AM/PM", 20: "h:mm", 21: "h:mm:ss", 22: "yyyy-mm-dd h:mm", 45: "mm:ss", 46: "[h]:mm:ss",
                   47: "mmss.0"}


def xlsx_text(path):
    with _Package(path) as pkg:
        return _workbook_text(pkg)


def _workbook_text(pkg):
    part = pkg.main("xl/workbook.xml")
    book = pkg.xml(part)
    if book is None:
        raise Skip("not an Excel workbook")
    rels = pkg.rels(part)
    date1904 = str(_attr(_kid(book, "workbookPr"), "date1904", "0")).lower() in ("1", "true")
    strings = [_string_item(si) for si in _kids(pkg.xml(_related(rels, "sharedStrings", "xl/sharedStrings.xml")), "si")]
    formats = _cell_formats(pkg.xml(_related(rels, "styles", "xl/styles.xml")))
    out = []
    for n, sheet in enumerate(_kids(_kid(book, "sheets"), "sheet"), 1):
        title = f"## Sheet: {_attr(sheet, 'name', f'Sheet{n}')}"
        if _attr(sheet, "state") in ("hidden", "veryHidden"):
            title += " (hidden)"
        kind, target = rels.get(_rid(sheet), ("/worksheet", f"xl/worksheets/sheet{n}.xml"))
        root = pkg.xml(target) if kind.endswith("/worksheet") else None
        if root is None:
            out.append(title + "\n\n(no cells: chart or missing sheet)")
            continue
        rows = _sheet_rows(root, strings, formats, date1904)
        block = title + "\n\n" + (_pipe_table(rows, keep_empty=True) if rows else "(empty)")
        notes = _sheet_comments(pkg, target)
        if notes:
            block += "\n\nCell comments:\n" + "\n".join(notes)
        out.append(block)
    return "\n\n".join(out)


def _string_item(si):
    """A shared or inline string: its own text or its runs, without phonetic hints."""
    parts = []
    for child in _children(si):
        name = _local(child.tag)
        if name == "t":
            parts.append(child.text or "")
        elif name == "r":
            parts += [t.text or "" for t in child if _local(t.tag) == "t"]
    return "".join(parts)


def _cell_formats(root):
    """Per cellXfs index: what its number format means for reading (see _format_kind)."""
    custom = {_int(_attr(f, "numFmtId"), -1): _attr(f, "formatCode", "") for f in _kids(_kid(root, "numFmts"), "numFmt")}
    formats = []
    for xf in _kids(_kid(root, "cellXfs"), "xf"):
        number = _int(_attr(xf, "numFmtId"), 0)
        code = custom.get(number, BUILTIN_FORMATS.get(number))
        formats.append(_format_kind(code) if code else None)
    return formats


def _format_kind(code):
    """('date', has_date, has_time, seconds, elapsed), ('percent',), ('pad', width) or None for a format code."""
    kept, elapsed, i = [], False, 0
    while i < len(code):
        ch = code[i]
        if ch == '"':
            end = code.find('"', i + 1)
            i = len(code) if end < 0 else end + 1
        elif ch in "\\_*":
            i += 2
        elif ch == "[":
            end = code.find("]", i)
            end = len(code) if end < 0 else end
            if re.fullmatch(r"[hms]+", code[i + 1:end], re.I):
                elapsed = True
                kept.append(code[i + 1:end])
            i = end + 1
        elif ch == ";":
            break
        else:
            kept.append(ch)
            i += 1
    text = "".join(kept).lower()
    has_time = elapsed or "h" in text or "s" in text
    has_date = "d" in text or "y" in text or ("m" in text and not has_time)
    if has_date or has_time:
        return "date", has_date, has_time, "s" in text, elapsed
    if "%" in text:
        return ("percent",)
    if re.fullmatch(r"0{2,}", text.strip()):
        return "pad", len(text.strip())
    return None


def _sheet_rows(root, strings, formats, date1904):
    cells, r = {}, 0
    for row in _kids(_kid(root, "sheetData"), "row"):
        r = _int(_attr(row, "r"), r + 1)
        c = 0
        for cell in _kids(row, "c"):
            match = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", _attr(cell, "r") or "")
            if match:
                c = 0
                for letter in match.group(1).upper():
                    c = c * 26 + ord(letter) - 64
            else:
                c += 1
            value = _cell_value(cell, strings, formats, date1904)
            if value != "":
                cells[(r, c)] = value
    # A vertically merged range repeats its value down its first column.
    for merge in _kids(_kid(root, "mergeCells"), "mergeCell"):
        ends = re.findall(r"([A-Za-z]{1,3})(\d+)", _attr(merge, "ref") or "")
        if len(ends) == 2:
            col = 0
            for letter in ends[0][0].upper():
                col = col * 26 + ord(letter) - 64
            top, bottom = int(ends[0][1]), int(ends[1][1])
            if (top, col) in cells:
                for rr in range(top + 1, bottom + 1):
                    cells.setdefault((rr, col), cells[(top, col)])
    if not cells:
        return []
    rows_used = range(min(k[0] for k in cells), max(k[0] for k in cells) + 1)
    columns = sorted({k[1] for k in cells})  # empty columns carry nothing
    rows, blank = [], False
    for rr in rows_used:
        row = [cells.get((rr, cc), "") for cc in columns]
        if any(row) or not blank:  # runs of empty rows inside the range collapse to one
            rows.append(row)
        blank = not any(row)
    return rows


def _cell_value(cell, strings, formats, date1904):
    kind = _attr(cell, "t", "n")
    v = _kid(cell, "v")
    v = v.text if v is not None and v.text is not None else None
    if kind == "inlineStr":
        return _string_item(_kid(cell, "is")) if _kid(cell, "is") is not None else (v or "")
    if v is None:
        formula = _kid(cell, "f")
        return "=" + formula.text if formula is not None and formula.text else ""
    if kind == "s":
        index = _int(v, -1)
        return strings[index] if 0 <= index < len(strings) else ""
    if kind == "b":
        return "TRUE" if v.strip().lower() in ("1", "true") else "FALSE"
    if kind == "d":
        return re.sub(r"T00:00:00(\.0+)?Z?$", "", v).replace("T", " ")
    if kind in ("str", "e"):
        return v
    style = _int(_attr(cell, "s"), 0)
    return _number(v, formats[style] if 0 <= style < len(formats) else None, date1904)


def _number(value, fmt, date1904):
    try:
        x = float(value)
    except ValueError:
        return value
    if not math.isfinite(x):
        return value
    if fmt and fmt[0] == "date":
        text = _excel_date(x, fmt, date1904)
        if text:
            return text
    if fmt and fmt[0] == "percent":
        return _plain(x * 100) + "%"
    if fmt and fmt[0] == "pad" and x.is_integer() and x >= 0:
        return str(int(x)).zfill(fmt[1])
    return _plain(x)


def _plain(x):
    """A number as Excel shows it at most: 15 significant digits, no exponent, integers without .0."""
    if x.is_integer() and abs(x) < 1e15:
        return str(int(x))
    text = format(x, ".15g")
    return format(Decimal(text), "f") if "e" in text else text


def _excel_date(x, fmt, date1904):
    _, has_date, has_time, seconds, elapsed = fmt
    if x < 0:
        return None
    days, secs = divmod(round(x * 86400), 86400)
    parts = []
    try:
        if has_date:
            if date1904:
                parts.append((date(1904, 1, 1) + timedelta(days=days)).isoformat())
            elif days == 60:  # Excel's 1900 leap-year bug: serial 60 is the day that never was
                parts.append("1900-02-29")
            else:
                parts.append((date(1899, 12, 31 if days < 60 else 30) + timedelta(days=days)).isoformat())
    except OverflowError:
        return None
    if has_time:
        hours, rest = divmod(secs, 3600)
        if elapsed and not has_date:
            hours += days * 24
        parts.append(f"{hours:02d}:{rest // 60:02d}" + (f":{rest % 60:02d}" if seconds else ""))
    return " ".join(parts)


def _sheet_comments(pkg, sheet_part):
    root = pkg.xml(_related(pkg.rels(sheet_part), "comments"))
    notes = []
    for comment in (root.iter() if root is not None else []):
        if _local(comment.tag) == "comment":
            text = " ".join(_string_item(_kid(comment, "text")).split()) if _kid(comment, "text") is not None else ""
            if text:
                notes.append(f"- {_attr(comment, 'ref')}: {text}")
    return notes


# --- PowerPoint ------------------------------------------------------------------------------------------------------

NOTES_SKIP = {"sldImg", "sldNum", "hdr", "ftr", "dt"}


def pptx_text(path):
    with _Package(path) as pkg:
        return _presentation_text(pkg)


def _presentation_text(pkg):
    part = pkg.main("ppt/presentation.xml")
    rels = pkg.rels(part)
    ids = [_rid(s) for s in _kids(_kid(pkg.xml(part), "sldIdLst"), "sldId")]
    slides = [rels[i][1] for i in ids if i in rels]
    if not slides:
        found = [n for n in pkg.zip.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
        slides = sorted(found, key=lambda n: int(re.sub(r"\D", "", n)))
    out = []
    for n, slide in enumerate(slides, 1):
        slide_rels = pkg.rels(slide)
        block = f"## Slide {n}"
        lines = _slide_lines(pkg.xml(slide), pkg, slide_rels, False)
        if lines:
            block += "\n\n" + "\n".join(lines)
        notes_part = _related(slide_rels, "notesSlide")
        notes = _slide_lines(pkg.xml(notes_part), pkg, pkg.rels(notes_part), True) if notes_part else []
        if notes:
            block += "\n\nNotes:\n" + "\n".join(notes)
        out.append(block)
    return "\n\n".join(out)


def _slide_lines(root, pkg, rels, notes):
    lines = []

    def para(p):
        return "".join((e.text or "") if _local(e.tag) == "t" else "\n" for e in p.iter() if _local(e.tag) in ("t", "br"))

    def walk(el):
        for child in _children(el):
            name = _local(child.tag)
            if name == "Fallback":
                continue
            if name == "sp" and notes:
                ph = next((e for e in child.iter() if _local(e.tag) == "ph"), None)
                if _attr(ph, "type") in NOTES_SKIP:
                    continue
            if name == "tbl":
                rows, above = [], {}
                for tr in _kids(child, "tr"):
                    row = []
                    for col, tc in enumerate(_kids(tr, "tc")):
                        text = " / ".join(t for t in (para(p).strip() for p in tc.iter() if _local(p.tag) == "p") if t)
                        if _attr(tc, "vMerge") in ("1", "true"):
                            text = above.get(col, "")
                        elif _attr(tc, "hMerge") in ("1", "true"):
                            text = ""
                        row.append(text)
                    rows.append(row)
                    above = dict(enumerate(row))
                lines.append(_pipe_table(rows))
            elif name == "p":
                text = para(child).strip()
                if text:
                    lines.append(text)
            elif name == "relIds":
                texts = _diagram_texts(pkg.xml(rels.get(_rid(child, "dm"), ("", None))[1]))
                if texts:
                    lines.append("[diagram] " + " / ".join(texts))
            else:
                walk(child)
    walk(root)
    return [line for line in lines if line]


# --- PDF, legacy office, drawings, mail ------------------------------------------------------------------------------

def pdf_text(path):
    try:
        result = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(Path(path).resolve()), "-"],
                                capture_output=True, timeout=TIMEOUT)
    except FileNotFoundError:
        raise Skip("pdftotext is not installed")
    except subprocess.TimeoutExpired:
        raise Skip(f"pdftotext took longer than {TIMEOUT} s")
    if result.returncode != 0:
        raise Skip("pdftotext failed: " + _tail(result.stderr))
    pages = result.stdout.decode("utf-8", "replace").split("\f")
    if len(pages) > 1 and not pages[-1].strip():
        pages.pop()
    if sum(ch.isalnum() for page in pages for ch in page) < max(20, 5 * len(pages)):
        raise Skip("PDF has almost no text (a scanned PDF?)")
    if len(pages) == 1:
        return pages[0]
    return "\n\n".join(f"[page {n}]\n{page}" for n, page in enumerate(pages, 1))


def _libreoffice():
    for name in ("libreoffice", "soffice"):
        if shutil.which(name):
            return shutil.which(name)
    return "/snap/bin/libreoffice" if os.path.exists("/snap/bin/libreoffice") else None


def legacy_office(path, kind, work_dir, target):
    """Convert with LibreOffice into a folder under work_dir, then read the result. The snap LibreOffice cannot
    see /tmp, so the source is copied next to the output."""
    binary = _libreoffice()
    if not binary:
        raise Skip(f"LibreOffice is not installed (needed for .{kind})")
    folder = Path(tempfile.mkdtemp(prefix="convert-", dir=_mkdir(Path(work_dir) / "converted"))).resolve()
    source = folder / f"source.{kind}"
    shutil.copyfile(path, source)
    out = _mkdir(folder / "out")
    command = [binary, f"-env:UserInstallation={(folder / 'profile').as_uri()}", "--headless", "--norestore",
               "--convert-to", target, "--outdir", str(out), str(source)]
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    except OSError as exc:
        raise Skip(f"LibreOffice could not start: {exc}")
    try:
        stdout, stderr = process.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        raise Skip(f"LibreOffice took longer than {TIMEOUT} s")
    result = out / f"source.{target}"
    if not result.exists():
        hint = " (the snap LibreOffice cannot see /tmp; use a work_dir under home)" if str(folder).startswith("/tmp") else ""
        raise Skip(f"LibreOffice could not convert the .{kind}{hint}: {_tail(stderr or stdout)}")
    return CONVERTERS[target](result)


def _drawio_label(value):
    value = re.sub(r"<br\s*/?>|</(div|p|li)>", " / ", html.unescape(value), flags=re.I)
    value = html.unescape(re.sub(r"<[^>]+>", " ", value))
    return " ".join(value.split()).strip(" /")


def _inflate(text):
    data = base64.b64decode(text)
    try:
        data = zlib.decompress(data, -15)
    except zlib.error:
        pass
    return unquote(data.decode("utf-8"))


def drawio_text(raw):
    """A draw.io file: its boxes and arrows as lines, then the XML with compressed pages opened and labels readable."""
    def open_page(match):
        try:
            return f"{match.group(1)}\n{_inflate(match.group(2))}\n{match.group(3)}"
        except (ValueError, UnicodeDecodeError):
            return match.group(0)
    xml_text = re.sub(r"(<diagram\b[^>]*>)\s*([A-Za-z0-9+/=\s]+?)\s*(</diagram>)", open_page, raw)
    xml_text = re.sub(r'\b(value|label|tooltip)="([^"]*)"', lambda m: f'{m.group(1)}="{_drawio_label(m.group(2))}"',
                      xml_text)
    summary = []
    try:
        root = ET.fromstring(raw)
        pages = [(_attr(root, "name") or "Page 1", root)] if _local(root.tag) == "mxGraphModel" else []
        for n, diagram in enumerate(_kids(root, "diagram"), 1):
            model = _kid(diagram, "mxGraphModel")
            if model is None and (diagram.text or "").strip():
                model = ET.fromstring(_inflate(diagram.text.strip()))
            pages.append((_attr(diagram, "name") or f"Page {n}", model))
        for name, model in pages:
            summary.append(_drawio_summary(name, model))
    except Exception:  # the XML below still carries the labels
        summary = []
    head = "[draw.io diagram]\n\n" + "\n\n".join(s for s in summary if s)
    return head + "\n\n## XML\n\n" + xml_text


def _drawio_summary(name, model):
    cells = {}
    for el in (model.iter() if model is not None else []):
        tag = _local(el.tag)
        if tag in ("UserObject", "object"):
            inner = _kid(el, "mxCell")
            cells[el.get("id")] = {**(inner.attrib if inner is not None else {}), "value": el.get("label", "")}
        elif tag == "mxCell" and el.get("id") and el.get("id") not in cells:
            cells[el.get("id")] = dict(el.attrib)
    labels = {cid: _drawio_label(cell.get("value") or "") for cid, cell in cells.items()}
    edges = {cid for cid, cell in cells.items() if cell.get("edge") == "1"}
    boxes = [labels[cid] for cid, cell in cells.items()
             if cell.get("vertex") == "1" and labels[cid] and cell.get("parent") not in edges]
    arrows = []
    for cid in edges:
        cell = cells[cid]
        text = " / ".join(x for x in [labels[cid]] + [labels[k] for k, c in cells.items() if c.get("parent") == cid] if x)
        source, target = labels.get(cell.get("source")) or "?", labels.get(cell.get("target")) or "?"
        arrows.append(f"- {source} -> {target}" + (f" [{text}]" if text else ""))
    if not boxes and not arrows:
        return ""
    lines = [f"## Page: {name}", "", "Boxes:"] + [f"- {b}" for b in boxes]
    return "\n".join(lines + (["", "Arrows:"] + sorted(arrows) if arrows else []))


def svg_text(raw):
    note = "[SVG drawing: only its text labels are given, not its shapes or arrows]"
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        found = re.findall(r"<text\b[^>]*>(.*?)</text>", raw, re.S)
        return note + "\n\n" + "\n".join(" ".join(html.unescape(re.sub(r"<[^>]+>", " ", t)).split()) for t in found)
    lines = []

    def walk(el):
        for child in el:
            if _local(child.tag) in ("text", "title", "desc", "foreignObject"):
                text = " ".join(" ".join(child.itertext()).split())
                if not text or text == "Text is not SVG - cannot display" or (lines and lines[-1] == text):
                    continue
                if text.endswith("...") and lines and lines[-1].startswith(text[:-3]):  # draw.io's shortened copy
                    continue
                lines.append(text)
            else:
                walk(child)
    walk(root)
    text = note + "\n\n" + "\n".join(lines)
    content = root.get("content") or ""
    if content.lstrip().startswith(("<mxfile", "<mxGraphModel")):
        text += "\n\n" + drawio_text(content)
    return text


def _png_drawio(data):
    """The draw.io XML a PNG export carries in its text chunks, if any."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    pos = 8
    try:
        while pos + 8 <= len(data):
            length, kind = int.from_bytes(data[pos:pos + 4], "big"), data[pos + 4:pos + 8]
            body = data[pos + 8:pos + 8 + length]
            pos += 12 + length
            key, _, rest = body.partition(b"\0")
            if key != b"mxfile" or kind not in (b"tEXt", b"zTXt", b"iTXt"):
                if kind == b"IEND":
                    break
                continue
            if kind == b"tEXt":
                return unquote(rest.decode("latin-1"))
            if kind == b"zTXt":
                return unquote(zlib.decompress(rest[1:]).decode("latin-1"))
            flag, rest = rest[0], rest[2:]
            rest = rest.partition(b"\0")[2].partition(b"\0")[2]
            return unquote((zlib.decompress(rest) if flag else rest).decode("utf-8"))
    except (zlib.error, IndexError, UnicodeDecodeError):
        return None
    return None


class _HtmlText(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.hidden += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.hidden = max(0, self.hidden - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data.replace("\n", " "))


def html_to_text(markup):
    parser = _HtmlText()
    parser.feed(markup)
    parser.close()
    return "\n".join(" ".join(line.split()) for line in "".join(parser.parts).split("\n"))


def eml_text(data):
    """A mail's headers and body, and its attachments as (file name, bytes)."""
    try:
        message = BytesParser(policy=policy.default).parsebytes(data)
        lines = [f"{name}: {message[name]}" for name in ("From", "To", "Cc", "Date", "Subject") if message[name]]
        body, text = message.get_body(preferencelist=("plain", "html")), ""
        if body is not None:
            try:
                text = body.get_content()
            except (LookupError, ValueError):
                text = decode(body.get_payload(decode=True) or b"")
            if body.get_content_subtype() == "html":
                text = html_to_text(text)
        attachments = []
        for n, part in enumerate(message.iter_attachments(), 1):
            name = Path((part.get_filename() or "").replace("\\", "/")).name
            payload = part.get_payload(decode=True)
            if payload is None and part.get_content_type() == "message/rfc822":
                payload, name = part.get_payload(0).as_bytes(), name or f"attachment-{n}.eml"
            if not name or _junk(name) or name == "..":
                name = f"attachment-{n}" + Path(name).suffix
            if payload:
                attachments.append((name, payload))
        if attachments:
            lines.append("Attachments: " + ", ".join(name for name, _ in attachments))
        return "\n".join(lines) + "\n\n" + text, attachments
    except Exception:  # not a parsable mail: its raw text is still worth reading
        return decode(data), []


CONVERTERS = {"docx": docx_text, "xlsx": xlsx_text, "pptx": pptx_text, "pdf": pdf_text}
