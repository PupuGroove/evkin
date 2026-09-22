"""Reconcile displayed Final -> database snapshot -> generated XLSX."""
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
import xml.etree.ElementTree as ET
import zipfile

FIELDS = ('nip', 'tukin', 'nominal', 'finalDibayar')
NS = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def rupiah(value):
    if value is None or str(value).strip() == '':
        raise ValueError('Nominal Final kosong')
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError('Nominal Final tidak valid')
    return str(int(number.quantize(Decimal('1'), rounding=ROUND_HALF_UP)))


def final_manifest(rows):
    normalized = []
    for row in rows:
        nip = str(row.get('nip') or '').strip()
        if not nip:
            raise ValueError('NIP Final kosong')
        normalized.append([nip, *[rupiah(row.get(key)) for key in FIELDS[1:]]])
    # Sort serialized rows, preserving duplicates (a set alone loses rows).
    lines = sorted(json.dumps(row, ensure_ascii=False, separators=(',', ':')) for row in normalized)
    digest = hashlib.sha256('\n'.join(lines).encode('utf-8')).hexdigest()
    return {'row_count': len(normalized), 'unique_nip': len({row[0] for row in normalized}),
            'gross': str(sum(int(row[1]) for row in normalized)),
            'deduction': str(sum(int(row[2]) for row in normalized)),
            'paid': str(sum(int(row[3]) for row in normalized)), 'sha256': digest}


def assert_manifest(actual, expected):
    if actual != expected:
        raise ValueError('Validasi Final gagal: jumlah baris, NIP, atau nominal berbeda dengan Final yang diperiksa. Buka kembali Final dan ekspor ulang.')


def verify_final_xlsx(path, expected):
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        sheet = next((s for s in workbook.find('x:sheets', NS) if s.get('name') == 'FINAL ABSENSI'), None)
        if sheet is None:
            raise ValueError('Sheet FINAL ABSENSI tidak ditemukan')
        rid = sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
        rels = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        target = next(rel.get('Target') for rel in rels if rel.get('Id') == rid)
        sheet_path = target.lstrip('/') if target.startswith('/') else 'xl/' + target
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [''.join(si.itertext()) for si in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
        rows = []
        headers = {}
        with archive.open(sheet_path) as source:
            for _, row in ET.iterparse(source, events=('end',)):
                if row.tag != '{' + NS['x'] + '}row':
                    continue
                values = {}
                for cell in row.findall('x:c', NS):
                    ref = ''.join(c for c in cell.get('r') if c.isalpha())
                    value = cell.find('x:v', NS)
                    text = value.text if value is not None else None
                    if cell.get('t') == 's':
                        text = strings[int(text)]
                    elif cell.get('t') == 'inlineStr':
                        text = ''.join(cell.find('x:is', NS).itertext())
                    values[ref] = text
                if not headers:
                    headers = values
                    if not set(FIELDS).issubset(headers.values()):
                        raise ValueError('Kolom Final tidak lengkap dalam Excel')
                else:
                    rows.append({name: values.get(col) for col, name in headers.items() if name in FIELDS})
                row.clear()
    actual = final_manifest(rows)
    assert_manifest(actual, expected)
    return actual
