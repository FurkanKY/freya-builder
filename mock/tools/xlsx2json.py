"""Every sheet of an .xlsx as JSON rows keyed by the header row. Standard library only.

    python3 -I mock/tools/xlsx2json.py <file.xlsx> [--paren-keys] > out.json

Output: {"<sheet name>": [{"<header>": value, ...}, ...], ...}, sheets in workbook order.
- Text cells stay text, so '0358' keeps its leading zero.
- Date-styled numbers become ISO dates: '1988-03-14', or '2026-10-14T11:00' when there is a time.
- Other numbers stay numbers (integers without '.0'); a '0000'-style format pads them to text.
- Empty cells are null; fully empty rows are skipped.
--paren-keys: a header like 'Müşteri No (customer_id)' gives the key 'customer_id'.
"""
import datetime
import json
import posixpath
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = {
    'm': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
}
# Built-in number formats that show a date or time.
DATE_FORMAT_IDS = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))


def text_of(el):
    """Text of a shared or inline string: its <t> runs, without phonetic hints."""
    if el is None:
        return ''
    return ''.join(t.text or '' for t in el.iter(f'{{{NS["m"]}}}t')
                   if t not in el.findall('.//m:rPh/m:t', NS))


def is_date_format(code):
    code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', '', code or '')  # quoted text, colours, escapes
    return bool(re.search(r'[dmyhs]', code, re.I))


def cell_styles(z):
    """Per style index: 'date', a zero-pad width (int), or None."""
    if 'xl/styles.xml' not in z.namelist():
        return []
    root = ET.fromstring(z.read('xl/styles.xml'))
    custom = {int(f.get('numFmtId')): f.get('formatCode') for f in root.findall('m:numFmts/m:numFmt', NS)}
    out = []
    for xf in root.findall('m:cellXfs/m:xf', NS):
        fid = int(xf.get('numFmtId', 0))
        code = custom.get(fid)
        if fid in DATE_FORMAT_IDS or (code and is_date_format(code)):
            out.append('date')
        elif code and re.fullmatch(r'0{2,}', code):
            out.append(len(code))
        else:
            out.append(None)
    return out


def serial_to_iso(v, date1904):
    base = datetime.datetime(1904, 1, 1) if date1904 else datetime.datetime(1899, 12, 30)
    dt = base + datetime.timedelta(seconds=round(float(v) * 86400))
    if dt.time() == datetime.time(0):
        return dt.date().isoformat()
    return dt.strftime('%Y-%m-%dT%H:%M' if dt.second == 0 else '%Y-%m-%dT%H:%M:%S')


def number(v):
    f = float(v)
    return int(f) if f.is_integer() and 'e' not in v.lower() else f


def col_index(ref):
    n = 0
    for ch in re.match(r'[A-Z]+', ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def sheets(z):
    """(name, path) per sheet in workbook order."""
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
    target = {r.get('Id'): r.get('Target') for r in rels.findall('rel:Relationship', NS)}
    date1904 = (wb.find('m:workbookPr', NS) is not None
                and wb.find('m:workbookPr', NS).get('date1904') in ('1', 'true'))
    out = []
    for s in wb.findall('m:sheets/m:sheet', NS):
        t = target[s.get(f'{{{NS["r"]}}}id')]
        path = t.lstrip('/') if t.startswith('/') else posixpath.normpath(posixpath.join('xl', t))
        out.append((s.get('name'), path))
    return out, date1904


def read_rows(z, path, shared, styles, date1904):
    root = ET.fromstring(z.read(path))
    rows = []
    for row in root.findall('m:sheetData/m:row', NS):
        values = {}
        for i, c in enumerate(row.findall('m:c', NS)):
            ref = c.get('r')
            col = col_index(ref) if ref else i
            t = c.get('t', 'n')
            v = c.find('m:v', NS)
            raw = v.text if v is not None else None
            if t == 's':
                val = shared[int(raw)] if raw is not None else None
            elif t == 'inlineStr':
                val = text_of(c.find('m:is', NS))
            elif t in ('str', 'e'):
                val = raw
            elif t == 'b':
                val = None if raw is None else raw == '1'
            elif raw is None or raw == '':
                val = None
            else:
                style = styles[int(c.get('s', 0))] if styles and int(c.get('s', 0)) < len(styles) else None
                if style == 'date':
                    val = serial_to_iso(raw, date1904)
                elif isinstance(style, int) and float(raw).is_integer():
                    val = str(int(float(raw))).zfill(style)
                else:
                    val = number(raw)
            values[col] = val
        if any(x not in (None, '') for x in values.values()):
            width = max(values) + 1
            rows.append([values.get(i) for i in range(width)])
    return rows


def key_of(header, i, paren):
    h = '' if header is None else str(header).strip()
    if paren:
        m = re.search(r'\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*$', h)
        if m:
            return m.group(1)
    return h or f'column_{i + 1}'


def convert(path, paren=False):
    with zipfile.ZipFile(path) as z:
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            shared = [text_of(si) for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', NS)]
        styles = cell_styles(z)
        found, date1904 = sheets(z)
        out = {}
        for name, sheet_path in found:
            rows = read_rows(z, sheet_path, shared, styles, date1904)
            if not rows:
                out[name] = []
                continue
            keys = [key_of(h, i, paren) for i, h in enumerate(rows[0])]
            items = []
            for r in rows[1:]:
                r = r + [None] * (len(keys) - len(r))
                extra = {f'column_{i + 1}': v for i, v in enumerate(r[len(keys):], len(keys)) if v is not None}
                items.append({**dict(zip(keys, r)), **extra})
            out[name] = items
        return out


def main(argv):
    args = [a for a in argv if not a.startswith('--')]
    if len(args) != 1:
        sys.exit(__doc__)
    json.dump(convert(args[0], paren='--paren-keys' in argv), sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main(sys.argv[1:])
