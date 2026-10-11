import base64
import shutil
import zipfile
import zlib
from email.message import EmailMessage
from urllib.parse import quote

import pytest

import builder.documents as documents
from builder.documents import collect, normalize

R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
MC = 'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'


def make_zip(path, parts):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return path


def rels(*items):
    body = "".join(f'<Relationship Id="{i}" Type="{R}/{kind}" Target="{target}"/>' for i, kind, target in items)
    return f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{body}</Relationships>'


def para(text, style=None, num=None):
    props = (f'<w:pStyle w:val="{style}"/>' if style else "") + (
        f'<w:numPr><w:ilvl w:val="{num[1]}"/><w:numId w:val="{num[0]}"/></w:numPr>' if num else "")
    return f'<w:p><w:pPr>{props}</w:pPr><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def cell(text, extra=""):
    return f"<w:tc><w:tcPr>{extra}</w:tcPr>{text}</w:tc>"


def make_docx(path):
    box = '<w:txbxContent><w:p><w:r><w:t>Kutu metni</w:t></w:r></w:p></w:txbxContent>'
    body = "".join([
        para("Kart Borcu Yapılandırma", "Heading1"),
        para("Kurallar", "Balk2"),
        '<w:p><w:r><w:t>Müşteri</w:t><w:tab/><w:t>ödeme</w:t><w:br/><w:t>ikinci satır</w:t>'
        '<w:footnoteReference w:id="1"/></w:r></w:p>',
        '<w:p><w:r><w:t xml:space="preserve">Kalan </w:t></w:r><w:del><w:r><w:delText>silinen</w:delText></w:r></w:del>'
        '<w:ins><w:r><w:t>eklenen</w:t></w:r></w:ins><w:r><w:commentReference w:id="0"/></w:r></w:p>',
        para("Madde bir", num=(1, 0)),
        para("Birinci", num=(2, 0)),
        para("Alt", num=(2, 1)),
        para("İkinci", num=(2, 0)),
        para("Numarasız liste", num=(9, 0)),
        "<w:tbl>"
        "<w:tr>" + cell(para("Segment")) + cell(para("Oran")) + cell(para("Not")) + "</w:tr>"
        "<w:tr>" + cell(para("Bireysel"), '<w:vMerge w:val="restart"/>') + cell(para("3,5%")) + cell(para("a") + para("b")) + "</w:tr>"
        "<w:tr>" + cell(para(""), "<w:vMerge/>") + cell(para("Tek"), '<w:gridSpan w:val="2"/>') + "</w:tr>"
        "</w:tbl>",
        f'<w:p><w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing>{box}</w:drawing></mc:Choice>'
        f'<mc:Fallback><w:pict>{box}</w:pict></mc:Fallback></mc:AlternateContent></w:r></w:p>',
        "<w:sectPr/>",
    ])
    styles = (f'<w:styles {W}><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
              '<w:style w:type="paragraph" w:styleId="Balk2"><w:name w:val="heading 2"/></w:style></w:styles>')
    numbering = (f'<w:numbering {W}>'
                 '<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/></w:lvl></w:abstractNum>'
                 '<w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>'
                 '<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/><w:lvlText w:val="%2)"/></w:lvl></w:abstractNum>'
                 '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num><w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>'
                 '</w:numbering>')
    footnotes = (f'<w:footnotes {W}><w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
                 f'<w:footnote w:id="1">{para("Dipnot metni")}</w:footnote></w:footnotes>')
    comments = f'<w:comments {W}><w:comment w:id="0" w:author="Ayşe">{para("Kontrol et")}</w:comment></w:comments>'
    return make_zip(path, {
        "_rels/.rels": rels(("rId1", "officeDocument", "word/document.xml")),
        "word/document.xml": f"<w:document {W} {MC}><w:body>{body}</w:body></w:document>",
        "word/_rels/document.xml.rels": rels(("rId1", "styles", "styles.xml"), ("rId2", "numbering", "numbering.xml"),
                                             ("rId3", "footnotes", "footnotes.xml"), ("rId4", "comments", "comments.xml")),
        "word/styles.xml": styles, "word/numbering.xml": numbering, "word/footnotes.xml": footnotes,
        "word/comments.xml": comments,
    })


def c(ref, value=None, kind=None, style=None, inline=None, formula=None):
    attrs = f' r="{ref}"' + (f' t="{kind}"' if kind else "") + (f' s="{style}"' if style is not None else "")
    inner = (f"<f>{formula}</f>" if formula else "") + (f"<v>{value}</v>" if value is not None else "")
    if inline is not None:
        inner = f"<is><t>{inline}</t></is>"
    return f"<c{attrs}>{inner}</c>"


def make_xlsx(path, date1904=False):
    shared = ["Müşteri Adı", "Doğum Tarihi", "Şükrü Çağlar İnce", "00123"]
    sst = "".join(f"<si><t>{s}</t></si>" for s in shared) + "<si><r><t>Bo</t></r><r><t>rç</t></r><rPh><t>x</t></rPh></si>"
    styles = (f'<styleSheet {S}><numFmts count="3"><numFmt numFmtId="164" formatCode="dd.mm.yyyy hh:mm"/>'
              '<numFmt numFmtId="165" formatCode="0000000000"/><numFmt numFmtId="166" formatCode="[$-41F]d mmmm yyyy;@"/></numFmts>'
              '<cellXfs count="7"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="164"/><xf numFmtId="10"/>'
              '<xf numFmtId="165"/><xf numFmtId="4"/><xf numFmtId="166"/></cellXfs></styleSheet>')
    rows = [
        '<row r="2">' + c("B2", 0, "s") + c("C2", 1, "s") + c("D2", 4, "s") + c("E2", kind="inlineStr", inline="Oran")
        + c("F2", kind="inlineStr", inline="Müşteri No") + c("G2", kind="inlineStr", inline="Aktif") + "</row>",
        '<row r="3">' + c("B3", 2, "s") + c("C3", 45000, style=1) + c("D3", "1234.5000000000002", style=5)
        + c("E3", "0.035", style=3) + c("F3", 3, "s") + c("G3", 1, "b") + "</row>",
        '<row r="4">' + c("B4", kind="inlineStr", inline="Ali") + c("C4", "46306.5", style=2) + c("D4", "42")
        + c("E4", "0.1", style=3, formula="E3*2") + c("F4", 123, style=4) + c("G4", 0, "b") + "</row>",
        '<row r="6">' + c("B6", "Toplam", "str", formula='"Toplam"') + c("C6", "46306", style=6) + "</row>",
    ]
    sheet2 = f'<worksheet {S}><sheetData>{"".join(rows)}</sheetData></worksheet>'
    sheet1 = f'<worksheet {S}><sheetData><row r="1">{c("A1", 0, style=1)}</row></sheetData></worksheet>'
    book = (f'<workbook {S} xmlns:r="{R}"><workbookPr{" date1904=\"1\"" if date1904 else ""}/>'
            '<sheets><sheet name="Özet" sheetId="1" r:id="rId1"/><sheet name="Müşteriler" sheetId="2" r:id="rId2"/></sheets></workbook>')
    return make_zip(path, {
        "_rels/.rels": rels(("rId1", "officeDocument", "xl/workbook.xml")),
        "xl/workbook.xml": book,
        "xl/_rels/workbook.xml.rels": rels(("rId1", "worksheet", "worksheets/sheet1.xml"),
                                           ("rId2", "worksheet", "/xl/worksheets/sheet2.xml"),
                                           ("rId3", "sharedStrings", "sharedStrings.xml"), ("rId4", "styles", "styles.xml")),
        "xl/worksheets/sheet1.xml": sheet1, "xl/worksheets/sheet2.xml": sheet2,
        "xl/sharedStrings.xml": f"<sst {S}>{sst}</sst>", "xl/styles.xml": styles,
    })


def slide(*texts, placeholder=None):
    shapes = "".join(
        f'<p:sp><p:nvSpPr><p:nvPr>{f"<p:ph type=\"{ph}\"/>" if ph else ""}</p:nvPr></p:nvSpPr>'
        f'<p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>'
        for text, ph in zip(texts, placeholder or [None] * len(texts)))
    return f"<p:sld {P} {A}><p:cSld><p:spTree>{shapes}</p:spTree></p:cSld></p:sld>"


def make_pptx(path):
    pres = (f'<p:presentation {P} xmlns:r="{R}"><p:sldIdLst><p:sldId id="256" r:id="rId2"/>'
            '<p:sldId id="257" r:id="rId1"/></p:sldIdLst></p:presentation>')
    return make_zip(path, {
        "_rels/.rels": rels(("rId1", "officeDocument", "ppt/presentation.xml")),
        "ppt/presentation.xml": pres,
        "ppt/_rels/presentation.xml.rels": rels(("rId1", "slide", "slides/slide1.xml"), ("rId2", "slide", "slides/slide2.xml")),
        "ppt/slides/slide1.xml": slide("İkinci slayt"),
        "ppt/slides/slide2.xml": slide("Açılış", "Gündem maddesi"),
        "ppt/slides/_rels/slide2.xml.rels": rels(("rId9", "notesSlide", "../notesSlides/notesSlide1.xml")),
        "ppt/notesSlides/notesSlide1.xml": slide("Konuşmacı notu", "7", placeholder=["body", "sldNum"]),
    })


def text_of(path, tmp_path):
    docs, skipped = collect([path], tmp_path / "work")
    assert len(docs) == 1, skipped
    return docs[0]["text"]


def test_docx_headings_lists_tables_notes_and_text_boxes(tmp_path):
    text = text_of(make_docx(tmp_path / "analiz.docx"), tmp_path)
    assert text.startswith("# Kart Borcu Yapılandırma\n\n## Kurallar\n\nMüşteri\tödeme\nikinci satır[^1]")
    assert "Kalan eklenen[comment 0]" in text and "silinen" not in text
    assert "- Madde bir\n1. Birinci\n  a) Alt\n2. İkinci\n- Numarasız liste" in text
    assert ("| Segment | Oran | Not |\n|---|---|---|\n| Bireysel | 3,5% | a / b |\n| Bireysel | Tek |  |") in text
    assert text.count("Kutu metni") == 1 and "[text box] Kutu metni" in text
    assert "## Footnotes\n\n[^1]: Dipnot metni" in text
    assert "## Comments\n\n- [comment 0] Ayşe: Kontrol et" in text


def test_xlsx_dates_numbers_strings_and_used_range(tmp_path):
    text = text_of(make_xlsx(tmp_path / "musteriler.xlsx"), tmp_path)
    first, second = text.split("## Sheet: Müşteriler")
    assert first.strip() == "## Sheet: Özet\n\n1899-12-31"
    lines = second.strip().split("\n")
    assert lines[0] == "| Müşteri Adı | Doğum Tarihi | Borç | Oran | Müşteri No | Aktif |"
    assert lines[1] == "|---|---|---|---|---|---|"
    assert lines[2] == "| Şükrü Çağlar İnce | 2023-03-15 | 1234.5 | 3.5% | 00123 | TRUE |"
    assert lines[3] == "| Ali | 2026-10-11 12:00 | 42 | 10% | 0000000123 | FALSE |"
    assert lines[4] == "|  |  |  |  |  |  |"  # the empty row 5 stays as one separator
    assert lines[5] == "| Toplam | 2026-10-11 |  |  |  |  |"
    assert len(lines) == 6


def test_xlsx_date1904_and_the_1900_leap_year_bug(tmp_path):
    text = text_of(make_xlsx(tmp_path / "book.xlsx", date1904=True), tmp_path)
    assert text.startswith("## Sheet: Özet\n\n1904-01-01")
    day = ("date", True, False, False, False)
    assert [documents._excel_date(x, day, False) for x in (1, 59, 60, 61)] == ["1900-01-01", "1900-02-28", "1900-02-29", "1900-03-01"]
    assert documents._excel_date(0.5, ("date", False, True, True, False), False) == "12:00:00"
    assert documents._excel_date(1.5, ("date", False, True, False, True), False) == "36:00"


def test_number_format_codes():
    kind = documents._format_kind
    assert kind("[$-41F]d mmmm yyyy;@")[:3] == ("date", True, False)
    assert kind("dd.mm.yyyy hh:mm")[:3] == ("date", True, True)
    assert kind("[h]:mm:ss") == ("date", False, True, True, True)
    assert kind('#,##0.00 "TL gün"') is None and kind("General") is None and kind("@") is None
    assert kind("0.0%") == ("percent",) and kind("000000") == ("pad", 6)
    assert documents._plain(0.1 + 0.2) == "0.3" and documents._plain(1e-7) == "0.0000001" and documents._plain(-0.0) == "0"


def test_pptx_slides_in_presentation_order_with_notes(tmp_path):
    text = text_of(make_pptx(tmp_path / "sunum.pptx"), tmp_path)
    assert text == "## Slide 1\n\nAçılış\nGündem maddesi\n\nNotes:\nKonuşmacı notu\n\n## Slide 2\n\nİkinci slayt"


def test_folder_order_and_hidden_files(tmp_path):
    case = tmp_path / "case"
    for name, text in {"z.md": "son", "a.md": "ilk", "sub/Brief.md": "brief", "README.md": "readme",
                       "ornek-10.md": "on", "ornek-2.md": "iki", ".hidden.md": "gizli", "__MACOSX/x.md": "mac",
                       "~$analiz.docx": "kilit", ".DS_Store": "x", "sub/Thumbs.db": "x"}.items():
        (case / name).parent.mkdir(parents=True, exist_ok=True)
        (case / name).write_text(text)
    (case / "akis.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    docs, skipped = collect(case, tmp_path / "work")
    assert [d["path"] for d in docs] == ["sub/Brief.md", "README.md", "a.md", "ornek-2.md", "ornek-10.md", "z.md"]
    assert {d["kind"] for d in docs} == {"md"}
    reasons = {s["path"]: s["reason"] for s in skipped}
    assert reasons["akis.png"] == "image"
    assert {".hidden.md", "__MACOSX/", "~$analiz.docx", ".DS_Store", "sub/Thumbs.db"} <= set(reasons)
    assert all(d["sha256"] == documents.hashlib.sha256(d["text"].encode()).hexdigest() for d in docs)


def test_zip_extraction_refuses_unsafe_members(tmp_path):
    archive = make_zip(tmp_path / "case.zip", {
        "../evil.md": "kötü", "/abs.md": "mutlak", "case/BRIEF.md": "# Brief", "case/README.md": "oku",
        "case/docs/a.md": "belge", "__MACOSX/case/._a.md": "x", "case/.DS_Store": "x"})
    work = tmp_path / "deep" / "work"
    docs, skipped = collect([archive], work)
    assert [d["path"] for d in docs] == ["BRIEF.md", "README.md", "docs/a.md"]
    reasons = {s["path"]: s["reason"] for s in skipped}
    assert "unsafe" in reasons["case.zip/../evil.md"] and "unsafe" in reasons["case.zip//abs.md"]
    assert "case.zip/__MACOSX/" in reasons and "case.zip/case/.DS_Store" in reasons
    assert not list(tmp_path.rglob("evil.md")) and not list(tmp_path.rglob("abs.md"))


def test_zip_inside_folder_and_duplicates(tmp_path):
    case = tmp_path / "case"
    case.mkdir()
    (case / "memo.md").write_text("Duyuru 3: ödeme günü değişti")
    make_zip(case / "ekler.zip", {"memo.md": "Duyuru 3: ödeme günü değişti", "yeni.md": "Ek kural"})
    docs, skipped = collect(case, tmp_path / "work")
    assert [d["path"] for d in docs] == ["ekler.zip/yeni.md", "memo.md"]
    assert {"path": "ekler.zip/memo.md", "reason": "same text as memo.md"} in skipped


def test_text_decoding_and_normalising(tmp_path):
    (tmp_path / "duyuru.txt").write_bytes("Müşteri İşlem ğı çö\r\nikinci   \r\n".encode("cp1254"))
    assert text_of(tmp_path / "duyuru.txt", tmp_path) == "Müşteri İşlem ğı çö\nikinci"
    assert documents.decode("Başlık".encode("utf-8-sig")) == "Başlık"
    assert documents.decode("Başlık".encode("utf-16")) == "Başlık"
    assert normalize("a  \r\nb\r\n\r\n\r\n\r\n\r\nc\n\n") == "a\nb\n\n\nc"
    info = zipfile.ZipInfo("Müşteri.md".encode("cp857").decode("cp437"))
    assert documents._member_name(info) == "Müşteri.md"


def test_html_svg_drawio_and_mail(tmp_path):
    (tmp_path / "sayfa.html").write_text("<html><style>p{}</style><script>alert(1)</script><p>Kural &amp; not</p></html>")
    html_text = text_of(tmp_path / "sayfa.html", tmp_path)
    assert "alert" not in html_text and "p{}" not in html_text and "<p>Kural &amp; not</p>" in html_text

    (tmp_path / "akis.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><title>Akış</title>'
                                       '<text>Başla<tspan>ilk</tspan></text><g><text>Bitiş</text></g></svg>')
    assert text_of(tmp_path / "akis.svg", tmp_path).endswith("\n\nAkış\nBaşla ilk\nBitiş")

    model = ('<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
             '<mxCell id="2" value="&lt;b&gt;Kimlik&lt;/b&gt;&lt;br&gt;doğrula" vertex="1" parent="1"/>'
             '<mxCell id="3" value="Ödeme sözü" vertex="1" parent="1"/>'
             '<mxCell id="4" value="evet" edge="1" source="2" target="3" parent="1"/></root></mxGraphModel>')
    packer = zlib.compressobj(wbits=-15)
    packed = base64.b64encode(packer.compress(quote(model, safe="~()*!.'").encode()) + packer.flush()).decode()
    (tmp_path / "akis.drawio").write_text(f'<mxfile><diagram name="Akış" id="d">{packed}</diagram></mxfile>')
    drawio = text_of(tmp_path / "akis.drawio", tmp_path)
    assert "## Page: Akış" in drawio and "- Kimlik / doğrula -> Ödeme sözü [evet]" in drawio
    assert 'value="Kimlik / doğrula"' in drawio

    mail = EmailMessage()
    mail["From"], mail["Subject"] = "risk@freya.example", "Duyuru: yeni kural"
    mail.set_content("Yeni kural: ödeme günü 15.")
    mail.add_attachment("# Ek\nİçerik".encode(), maintype="text", subtype="markdown", filename="ek.md")
    (tmp_path / "duyuru.eml").write_bytes(bytes(mail))
    docs, skipped = collect([tmp_path / "duyuru.eml"], tmp_path / "work")
    assert [d["path"] for d in docs] == ["duyuru.eml", "duyuru.eml/ek.md"]
    assert "Subject: Duyuru: yeni kural" in docs[0]["text"] and "Yeni kural: ödeme günü 15." in docs[0]["text"]
    assert docs[1]["text"] == "# Ek\nİçerik"


def test_unknown_broken_and_missing_files_never_raise(tmp_path, monkeypatch):
    folder = tmp_path / "case"
    folder.mkdir()
    (folder / "veri.bin").write_bytes(b"\x00\x01\x02")
    (folder / "NOTLAR").write_text("düz metin")
    make_zip(folder / "bos.docx", {"word/other.xml": "<x/>"})
    (folder / "eski.doc").write_bytes(b"\xd0\xcf\x11\xe0 not really a doc")
    (folder / "yanlis.xlsx").write_bytes(b"not a zip at all")
    make_zip(folder / "bozuk.pptx", {"ppt/presentation.xml": "<p:presentation"})
    monkeypatch.setattr(documents, "_libreoffice", lambda: shutil.which("false"))
    docs, skipped = collect([folder, tmp_path / "yok.md"], tmp_path / "work")
    assert [(d["path"], d["kind"]) for d in docs] == [("NOTLAR", "")]
    reasons = {s["path"]: s["reason"] for s in skipped}
    assert reasons["veri.bin"].startswith("binary file")
    assert reasons["bos.docx"] == "not a Word document"
    assert reasons["eski.doc"].startswith("LibreOffice could not convert the .doc")
    assert reasons["yanlis.xlsx"].startswith("LibreOffice could not convert the .xlsx")
    assert reasons["bozuk.pptx"].startswith("could not read the pptx")
    assert reasons[str(tmp_path / "yok.md")] == "not found"
    monkeypatch.setattr(documents, "_libreoffice", lambda: str(tmp_path / "no-such-office"))
    assert collect([folder / "eski.doc"], tmp_path / "work")[1][0]["reason"].startswith("LibreOffice could not start")
    monkeypatch.setattr(documents, "_libreoffice", lambda: None)
    assert collect([folder / "eski.doc"], tmp_path / "work")[1][0]["reason"].startswith("LibreOffice is not installed")


def minimal_pdf(text):
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext is not installed")
def test_pdf_text_and_scanned_pdf(tmp_path):
    (tmp_path / "kurallar.pdf").write_bytes(minimal_pdf("Statement debt rules for Freya Bank"))
    (tmp_path / "tarama.pdf").write_bytes(minimal_pdf(""))
    docs, skipped = collect([tmp_path / "kurallar.pdf", tmp_path / "tarama.pdf"], tmp_path / "work")
    assert [d["path"] for d in docs] == ["kurallar.pdf"] and docs[0]["kind"] == "pdf"
    assert docs[0]["text"].strip() == "Statement debt rules for Freya Bank"
    assert skipped == [{"path": "tarama.pdf", "reason": "PDF has almost no text (a scanned PDF?)"}]


def test_docx_numbered_headings_from_styles(tmp_path):
    styles = (f'<w:styles {W}><w:style w:styleId="Balk1"><w:name w:val="heading 1"/><w:pPr><w:numPr><w:numId w:val="3"/>'
              '</w:numPr></w:pPr></w:style><w:style w:styleId="Balk2"><w:name w:val="heading 2"/><w:basedOn w:val="Balk1"/>'
              '<w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="3"/></w:numPr></w:pPr></w:style>'
              '<w:style w:styleId="Ozel"><w:name w:val="Özel"/><w:pPr><w:outlineLvl w:val="2"/></w:pPr></w:style></w:styles>')
    numbering = (f'<w:numbering {W}><w:abstractNum w:abstractNumId="7">'
                 '<w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/><w:pStyle w:val="Balk1"/></w:lvl>'
                 '<w:lvl w:ilvl="1"><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2"/><w:pStyle w:val="Balk2"/></w:lvl>'
                 '</w:abstractNum><w:num w:numId="3"><w:abstractNumId w:val="7"/></w:num></w:numbering>')
    body = para("Giriş", "Balk1") + para("Kapsam", "Balk2") + para("Kurallar", "Balk1") + para("Ödeme", "Balk2") + para("Not", "Ozel")
    make_zip(tmp_path / "kural.docx", {
        "word/document.xml": f"<w:document {W}><w:body>{body}</w:body></w:document>",
        "word/styles.xml": styles, "word/numbering.xml": numbering})
    assert text_of(tmp_path / "kural.docx", tmp_path) == "# 1. Giriş\n\n## 1.1 Kapsam\n\n# 2. Kurallar\n\n## 2.1 Ödeme\n\n### Not"


def test_png_with_embedded_drawio(tmp_path):
    model = '<mxGraphModel><root><mxCell id="2" value="Söz al" vertex="1"/></root></mxGraphModel>'
    chunk = b"mxfile\0" + quote(model).encode()
    png = b"\x89PNG\r\n\x1a\n" + len(chunk).to_bytes(4, "big") + b"tEXt" + chunk + b"\0" * 4 + b"\0\0\0\0IEND\0\0\0\0"
    (tmp_path / "akis.png").write_bytes(png)
    assert "Boxes:\n- Söz al" in text_of(tmp_path / "akis.png", tmp_path)


def test_garbage_in_every_format_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(documents, "_libreoffice", lambda: None)
    case = tmp_path / "case"
    case.mkdir()
    kinds = ["docx", "xlsx", "pptx", "pdf", "doc", "xls", "ppt", "rtf", "odt", "zip", "eml", "svg", "drawio", "html",
             "md", "json", "png", "jpg", "xml", "csv", "bin"]
    for n, kind in enumerate(kinds):
        (case / f"bozuk.{kind}").write_bytes(b"PK\x03\x04" + bytes(range(256)) * (n + 1))
        make_zip(case / f"yarim-{kind}.zip", {f"a.{kind}": b"\x00garbage"})
    (case / "kesik.xlsx").write_bytes(make_xlsx(tmp_path / "ok.xlsx").read_bytes()[:300])
    docs, skipped = collect(case, case / "work")
    assert {d["path"] for d in docs} | {s["path"] for s in skipped} >= {f"bozuk.{kind}" for kind in kinds}
    again = collect(case, case / "work")  # the work folder inside the case is not read back
    assert [d["path"] for d in again[0]] == [d["path"] for d in docs]
