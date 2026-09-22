"""Streaming reader for the three recap sheets in a large attendance XLSX.

Only REKAP OKT/NOV/DES and columns A:B are read. This keeps the multi-million
daily rows out of memory and treats every workbook cell as data, never as an
instruction for the application.
"""
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
import re
import xml.etree.ElementTree as ET
import zipfile


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _column_number(reference):
    letters = re.match(r"[A-Z]+", str(reference or "").upper())
    if not letters:
        return 0
    value = 0
    for character in letters.group(0):
        value = value * 26 + ord(character) - 64
    return value


def _sheet_paths(archive):
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        relation.attrib["Id"]: relation.attrib["Target"]
        for relation in relationships.findall(f"{{{PKG_REL_NS}}}Relationship")
    }
    result = {}
    for sheet in workbook.findall(f".//{{{MAIN_NS}}}sheet"):
        relation_id = sheet.attrib.get(f"{{{DOC_REL_NS}}}id")
        target = targets.get(relation_id, "")
        if not target:
            continue
        path = str(PurePosixPath("xl") / target) if not target.startswith("/") else target[1:]
        result[sheet.attrib.get("name", "")] = str(PurePosixPath(path))
    return result


def _raw_cells(archive, sheet_path):
    cells, shared_ids = [], set()
    with archive.open(sheet_path) as source:
        for _, element in ET.iterparse(source, events=("end",)):
            if element.tag != f"{{{MAIN_NS}}}c":
                continue
            reference = element.attrib.get("r", "")
            column = _column_number(reference)
            if column not in {1, 2}:
                element.clear()
                continue
            match = re.search(r"(\d+)$", reference)
            row_number = int(match.group(1)) if match else 0
            cell_type = element.attrib.get("t", "n")
            value_node = element.find(f"{{{MAIN_NS}}}v")
            value = value_node.text if value_node is not None else None
            if cell_type == "inlineStr":
                value = "".join(node.text or "" for node in element.findall(f".//{{{MAIN_NS}}}t"))
            elif cell_type == "s" and value not in (None, ""):
                shared_ids.add(int(value))
            cells.append((row_number, column, cell_type, value))
            element.clear()
    return cells, shared_ids


def _shared_strings(archive, wanted):
    if not wanted or "xl/sharedStrings.xml" not in archive.namelist():
        return {}
    result, index = {}, -1
    with archive.open("xl/sharedStrings.xml") as source:
        for _, element in ET.iterparse(source, events=("end",)):
            if element.tag != f"{{{MAIN_NS}}}si":
                continue
            index += 1
            if index in wanted:
                result[index] = "".join(
                    node.text or "" for node in element.findall(f".//{{{MAIN_NS}}}t")
                )
            element.clear()
    return result


def _value(cell_type, raw, shared):
    if raw is None:
        return ""
    if cell_type == "s":
        return shared.get(int(raw), "")
    if cell_type in {"str", "inlineStr", "e", "b"}:
        return raw
    try:
        number = Decimal(raw)
        return int(number) if number == number.to_integral_value() else float(number)
    except (InvalidOperation, ValueError):
        return raw


def read_rekap_sheets(path):
    """Return normalized import payloads for REKAP OKT, NOV, and DES."""
    with zipfile.ZipFile(path) as archive:
        paths = _sheet_paths(archive)
        selected = []
        wanted_shared = set()
        for name, month in (("REKAP OKT", 10), ("REKAP NOV", 11), ("REKAP DES", 12)):
            actual = next((item for item in paths if item.strip().upper() == name), None)
            if actual is None:
                continue
            cells, shared_ids = _raw_cells(archive, paths[actual])
            selected.append((actual, month, cells))
            wanted_shared.update(shared_ids)
        if not selected:
            raise ValueError("Sheet REKAP OKT/NOV/DES tidak ditemukan")
        shared = _shared_strings(archive, wanted_shared)

    result = []
    for sheet_name, month, cells in selected:
        by_row = {}
        for row_number, column, cell_type, raw in cells:
            by_row.setdefault(row_number, {})[column] = _value(cell_type, raw, shared)
        header_row = next((number for number, values in sorted(by_row.items())
                           if str(values.get(1, "")).strip().upper() == "NIP" and
                           "POTONGAN" in str(values.get(2, "")).upper()), None)
        if header_row is None:
            raise ValueError(f"Header NIP/Total Potongan tidak ditemukan pada {sheet_name}")
        rows = []
        for row_number, values in sorted(by_row.items()):
            if row_number <= header_row:
                continue
            nip = str(values.get(1, "")).strip()
            if nip.endswith(".0") and nip[:-2].isdigit():
                nip = nip[:-2]
            if not nip or nip.upper() in {"GRAND TOTAL", "TOTAL"}:
                continue
            rows.append({"NIP": nip, "Sum of Total Potongan (%)": values.get(2, "")})
        result.append({"sheet_name": sheet_name, "bulan": month, "rows": rows})
    return result
