"""Load street tiecard references from Google Docs in a Drive project folder."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from googleapiclient.http import MediaIoBaseDownload


_ADDRESS_HEADING = re.compile(
    r"^(?P<address>\d+\s+.+?)\s+[\N{EN DASH}\N{EM DASH}-]\s+"
    r"Registr(?:y|ies)\s+(?P<registries>.+?)"
    r"(?:\s+[\N{EN DASH}\N{EM DASH}-]\s+COMPLETE)?$",
    re.IGNORECASE,
)
_SERVICE_LINE = re.compile(r"^Service:\s*PS\s*(.*?)\s*\|\s*HS\s*(.*?)\s*$", re.IGNORECASE)
_SERVICE_SPEC = re.compile(
    r"^(?P<diameter>(?:\d+\s+)?(?:\d+/\d+|[\N{VULGAR FRACTION ONE QUARTER}\N{VULGAR FRACTION ONE HALF}\N{VULGAR FRACTION THREE QUARTERS}]|\d+(?:\.\d+)?))"
    r"\s*(?P<inch>[\"\N{RIGHT DOUBLE QUOTATION MARK}])?\s+(?P<material>.+)$"
)
_MEASUREMENT = re.compile(r"^(HS|CH|HC|MC|LS|RS):\s*(.*)$", re.IGNORECASE)
_COMPLETION_DATE = re.compile(r"^Completion Date:\s*(.*)$", re.IGNORECASE)
_DOUBLE_CURB = re.compile(
    r"^Double Curbed\s*:\s*(?P<offset>.*?)\s*(?:from\s+old\s+curb)?\s*$",
    re.IGNORECASE,
)
_SUFFIXES = {
    "STREET": "ST",
    "ROAD": "RD",
    "AVENUE": "AVE",
    "DRIVE": "DR",
    "LANE": "LN",
    "COURT": "CT",
    "PLACE": "PL",
    "BOULEVARD": "BLVD",
    "TERRACE": "TER",
    "CIRCLE": "CIR",
    "HIGHWAY": "HWY",
    "SQUARE": "SQ",
    "PARKWAY": "PKWY",
}


def normalize_address(value: str) -> str:
    """Normalize an address enough to match photo OCR to a document heading."""
    words = re.sub(r"[^A-Z0-9 ]+", " ", str(value).upper()).split()
    return " ".join(_SUFFIXES.get(word, word) for word in words)


def _registry_display(value: str) -> str:
    """Keep every listed registry number while making multi-number cards compact."""
    parts = [part.strip() for part in re.split(r"\s+(?:AND|&)\s+|\s*/\s*", value, flags=re.I)]
    return " / ".join(part for part in parts if part)


def _split_service_spec(value: str) -> tuple[str, str]:
    """Split ``1” Copper`` into service diameter and material fields."""
    value = str(value or "").strip()
    match = _SERVICE_SPEC.match(value)
    if not match:
        return "", value
    diameter = match.group("diameter") + (match.group("inch") or "”")
    return diameter, match.group("material").strip()


def _parse_measurement_line(line: str, card: dict) -> None:
    current_key = None
    key_map = {
        "HS": "curb_to_house",
        "CH": "curb_to_house",
        "HC": "curb_to_house",
        "MC": "vertical",
        "LS": "left",
        "RS": "right",
    }
    for raw_part in line.split("|"):
        part = raw_part.strip()
        match = _MEASUREMENT.match(part)
        if match:
            current_key = key_map[match.group(1).upper()]
            value = match.group(2).strip()
            if value:
                card[current_key] = value
        elif current_key and part:
            card[current_key] = f"{card.get(current_key, '')} | {part}".strip(" |")


def parse_reference_document(text: str, title: str = "") -> list[dict]:
    """Parse address sections from the field-entry layout used by the project Docs."""
    lines = [line.strip() for line in text.replace("\r", "").split("\n")]
    main_label = ""
    for index, line in enumerate(lines):
        if line.casefold() == "street main":
            for candidate in lines[index + 1:]:
                if not candidate:
                    continue
                if candidate.lower().startswith("material / size:"):
                    candidate = candidate.split(":", 1)[1].strip()
                main_label = candidate
                break
            break

    references = []
    current = None
    for line in lines:
        heading = _ADDRESS_HEADING.match(line)
        if heading:
            if current:
                references.append(current)
            current = {
                "address": heading.group("address").strip(),
                "reg_no": _registry_display(heading.group("registries")),
                "contractor": "Demo Contractor",
                "inspected_by": "Morgan",
                "_reference_document": title,
            }
            if main_label:
                current["main_label"] = main_label
            continue
        if not current or not line:
            continue
        completion_date = _COMPLETION_DATE.match(line)
        if completion_date:
            value = completion_date.group(1).strip()
            if value:
                current["date"] = value
            continue
        service = _SERVICE_LINE.match(line)
        if service:
            ps, hs = service.group(1).strip(), service.group(2).strip()
            if ps:
                ps_diameter, ps_material = _split_service_spec(ps)
                current["service_main_to_curb"] = ps_material
                if ps_diameter:
                    current["diameter_service"] = ps_diameter
            if hs:
                hs_diameter, hs_material = _split_service_spec(hs)
                current["service_curb_to_house"] = hs_material
                if hs_diameter and not current.get("diameter_service"):
                    current["diameter_service"] = hs_diameter
            continue
        double_curb = _DOUBLE_CURB.match(line)
        if double_curb:
            offset = re.sub(
                r"\s*from\s+old\s+curb\s*$",
                "",
                double_curb.group("offset"),
                flags=re.I,
            ).strip()
            current["double_curbed"] = True
            if offset:
                current["curb_offset"] = offset
            continue
        if _MEASUREMENT.match(line.split("|", 1)[0].strip()):
            _parse_measurement_line(line, current)

    if current:
        references.append(current)
    return references


def merge_reference(card: dict, reference: dict) -> dict:
    """Fill only blank card fields; field-photo data remains authoritative."""
    for key, value in reference.items():
        if value in (None, "", False):
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, dict) and not any(str(v).strip() for v in value.values() if v not in (None, False)):
            continue
        if not card.get(key):
            card[key] = value
    return card


@dataclass
class ReferenceIndex:
    by_address: dict[str, dict]
    by_registry: dict[str, dict]

    @classmethod
    def from_references(cls, references: list[dict]) -> "ReferenceIndex":
        by_address = {}
        by_registry = {}
        for reference in references:
            address_key = normalize_address(reference.get("address", ""))
            if address_key:
                by_address[address_key] = reference
            for registry in str(reference.get("reg_no", "")).split("/"):
                registry = registry.strip().upper()
                if registry:
                    by_registry[registry] = reference
        return cls(by_address, by_registry)

    def lookup(self, card: dict) -> dict | None:
        address_key = normalize_address(card.get("address", ""))
        if address_key and address_key in self.by_address:
            return self.by_address[address_key]
        registry = str(card.get("reg_no", "")).strip().upper()
        return self.by_registry.get(registry) if registry else None

    def enrich(self, card: dict) -> dict:
        reference = self.lookup(card)
        if not reference:
            return card
        merge_reference(card, reference)
        print(
            f"  [Reference] Matched {reference.get('address')} in "
            f"'{reference.get('_reference_document')}'"
        )
        return card


def _export_document_text(drive, file_id: str) -> str:
    request = drive.files().export_media(fileId=file_id, mimeType="text/plain")
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue().decode("utf-8-sig", errors="replace")


def load_reference_index(drive, project_folder_id: str) -> ReferenceIndex:
    """Export every Google Doc in the project folder and index its address sections."""
    response = drive.files().list(
        q=(
            f"'{project_folder_id}' in parents and "
            "mimeType='application/vnd.google-apps.document' and trashed=false"
        ),
        fields="files(id,name)",
        pageSize=200,
    ).execute()
    references = []
    for item in response.get("files", []):
        text = _export_document_text(drive, item["id"])
        parsed = parse_reference_document(text, item.get("name", ""))
        for reference in parsed:
            reference["_reference_document_id"] = item["id"]
        references.extend(parsed)
    return ReferenceIndex.from_references(references)
