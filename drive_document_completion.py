"""Keep Demo Contractor tiecard Google Docs ordered and completion statuses current."""

from __future__ import annotations

import re
from datetime import date

from drive_reference_docs import normalize_address


_ADDRESS_HEADING = re.compile(
    r"^(?P<address>\d+\s+.+?)\s+[\N{EN DASH}\N{EM DASH}-]\s+"
    r"Registr(?:y|ies)\s+.+?(?:\s+[\N{EN DASH}\N{EM DASH}-]\s+COMPLETE)?$",
    re.IGNORECASE,
)
_MEASUREMENT = re.compile(r"^(HS|CH|HC|MC|LS|RS):\s*(.*)$", re.IGNORECASE)
_LOOSE_MEASUREMENT = re.compile(
    r"(?<![A-Z])(?P<key>HS|CH|HC|MC|LS|RS)(?=[:\d\s])\s*:?\s*"
    r"(?P<value>.*?)(?=\s+(?:HS|CH|HC|MC|LS|RS)(?=[:\d\s])|$)",
    re.IGNORECASE,
)
_COMPLETION_DATE = re.compile(r"^Completion Date:\s*(.*)$", re.IGNORECASE)
_CONTRACTOR = re.compile(r"^Contractor:\s*(.*)$", re.IGNORECASE)
_INSPECTOR = re.compile(r"^Inspected By:\s*(.*)$", re.IGNORECASE)
_HOUSE_KEYS = ("HS", "CH", "HC")
_COLORS = {
    "navy": {"red": 0.08, "green": 0.22, "blue": 0.42},
    "green": {"red": 0.08, "green": 0.45, "blue": 0.20},
    "red": {"red": 0.75, "green": 0.08, "blue": 0.08},
    "teal": {"red": 0.00, "green": 0.42, "blue": 0.42},
    "blue": {"red": 0.08, "green": 0.32, "blue": 0.72},
    "purple": {"red": 0.43, "green": 0.18, "blue": 0.62},
    "orange": {"red": 0.82, "green": 0.32, "blue": 0.00},
    "gray": {"red": 0.36, "green": 0.36, "blue": 0.36},
}
_PALE_GREEN = {"red": 0.86, "green": 0.96, "blue": 0.88}
_PALE_RED = {"red": 1.00, "green": 0.88, "blue": 0.88}


def _address_from_heading(line: str) -> str:
    match = _ADDRESS_HEADING.match(line.strip())
    return match.group("address").strip() if match else ""


def _extract_blocks(lines: list[str], start: int, end: int) -> list[list[str]]:
    blocks = []
    index = start
    while index < end:
        if not _ADDRESS_HEADING.match(lines[index].strip()):
            index += 1
            continue
        block = [lines[index].rstrip()]
        index += 1
        while index < end and lines[index].strip():
            if _ADDRESS_HEADING.match(lines[index].strip()):
                break
            block.append(lines[index].rstrip())
            index += 1
        blocks.append(block)
    return blocks


def _canonical_measurement_key(key: str) -> str:
    upper = key.upper()
    return "HS" if upper in _HOUSE_KEYS else upper


def _record_measurement(values: dict[str, str], key: str, value: str) -> None:
    value = value.strip(" |")
    if not value:
        return
    canonical = _canonical_measurement_key(key)
    existing = values.get(canonical, "")
    if existing and value not in existing:
        values[canonical] = f"{existing} | {value}"
    elif not existing:
        values[canonical] = value


def _measurement_values(block: list[str]) -> dict[str, str]:
    values = {}
    for line in block[1:]:
        text = line.strip()
        if not text or text.lower().startswith((
            "status:", "completion date:", "contractor:", "inspected by:",
            "service:", "pictures:", "reference points", "address note:",
            "registry notation:", "double curbed",
        )):
            continue
        labeled = False
        current = None
        for raw_part in line.split("|"):
            part = raw_part.strip()
            match = _MEASUREMENT.match(part)
            if match:
                labeled = True
                current = match.group(1).upper()
                _record_measurement(values, current, match.group(2))
            elif current and part:
                _record_measurement(values, current, part)
        if labeled:
            continue
        for match in _LOOSE_MEASUREMENT.finditer(text):
            _record_measurement(values, match.group("key"), match.group("value"))
    return values


def measurements_complete(block: list[str]) -> bool:
    """A card is complete when house, main, left, and right ties are present."""
    values = _measurement_values(block)
    house = values.get("HS")
    return bool(house and values.get("MC") and values.get("LS") and values.get("RS"))


def _measurement_line(values: dict[str, str]) -> str:
    return " | ".join(
        f"{key}: {values.get(key, '')}".rstrip()
        for key in ("HS", "MC", "LS", "RS")
    )


def _normalize_block(block: list[str], completed: bool = False) -> list[str]:
    """Keep every parcel's measurement and Demo Contractor/Morgan fields visible."""
    heading = block[0]
    values = _measurement_values(block)
    contractor = "Demo Contractor"
    inspector = "Morgan"
    service = ""
    notes = ""
    pictures = "No"
    completion = ""
    double_curb = ""
    extras = []
    for line in block[1:]:
        text = line.strip()
        if not text or text.upper() == "STATUS: NOT COMPLETED":
            continue
        if match := _COMPLETION_DATE.match(text):
            completion = match.group(1).strip()
            continue
        if match := _CONTRACTOR.match(text):
            contractor = match.group(1).strip() or contractor
            continue
        if match := _INSPECTOR.match(text):
            inspector = match.group(1).strip() or inspector
            continue
        if text.lower().startswith("service:"):
            service = text
            continue
        if text.lower().startswith("pictures:"):
            pictures = text.split(":", 1)[1].strip() or "No"
            continue
        if text.lower().startswith(("reference points", "address note:", "registry notation:")):
            notes = text
            continue
        if text.lower().startswith("double curbed"):
            double_curb = text
            continue
        if _MEASUREMENT.match(text.split("|", 1)[0].strip()) or _LOOSE_MEASUREMENT.search(text):
            continue
        extras.append(text)

    result = [heading]
    if not completed and "COMPLETE" not in heading.upper():
        result.append("Status: NOT COMPLETED")
    result.append(f"Completion Date: {completion}".rstrip())
    result.append(f"Contractor: {contractor}")
    result.append(f"Inspected By: {inspector}")
    result.append(service or "Service: PS  | HS")
    if double_curb:
        result.append(double_curb)
    if any(len(values.get(key, "")) > 18 for key in ("HS", "MC", "LS", "RS")):
        for key in ("HS", "MC", "LS", "RS"):
            result.append(f"{key}: {values.get(key, '')}".rstrip())
    else:
        result.append(_measurement_line(values))
    if notes:
        result.append(notes)
    result.extend(extras)
    result.append(f"Pictures: {pictures}")
    return result


def _set_picture_status(block: list[str], status: str | None = None) -> list[str]:
    result = list(block)
    for index, line in enumerate(result):
        if line.strip().lower().startswith("pictures:"):
            current = line.split(":", 1)[1].strip()
            result[index] = f"Pictures: {status or current or 'No'}"
            return result
    result.append(f"Pictures: {status or 'No'}")
    return result


def _set_completion_date(block: list[str], value: str = "") -> list[str]:
    """Ensure every address block has one completion-date field."""
    result = list(block)
    for index, line in enumerate(result):
        match = _COMPLETION_DATE.match(line.strip())
        if match:
            current = match.group(1).strip()
            result[index] = f"Completion Date: {current or value}".rstrip()
            return result
    insert_at = 1
    if len(result) > 1 and result[1].strip().upper() == "STATUS: NOT COMPLETED":
        insert_at = 2
    result.insert(insert_at, f"Completion Date: {value}".rstrip())
    return result


def _promote(block: list[str], completion_date: str) -> list[str]:
    result = [line for line in block if line.strip().upper() != "STATUS: NOT COMPLETED"]
    if "COMPLETE" not in result[0].upper():
        result[0] = f"{result[0]} – COMPLETE"
    result = _set_completion_date(result, completion_date)
    return _normalize_block(result, completed=True)


def _primary_street(pending_heading: str) -> str:
    return pending_heading.split(" Parcels Ready", 1)[0].strip()


def _same_street(block: list[str], primary_street: str) -> bool:
    address = normalize_address(_address_from_heading(block[0])).split()
    return " ".join(address[1:]) == normalize_address(primary_street) if address else False


def transform_document_text(
    text: str,
    picture_updates: dict[str, str] | None = None,
    completion_date: str | None = None,
) -> tuple[str, list[str]]:
    """Promote complete address blocks and normalize every picture field."""
    completion_date = completion_date or date.today().strftime("%m/%d/%Y")
    lines = [line.rstrip() for line in text.replace("\r", "").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    try:
        completed_index = next(i for i, line in enumerate(lines) if line.strip() == "Completed Addresses")
        pending_index = next(
            i for i, line in enumerate(lines)
            if i > completed_index and line.strip().endswith("Parcels Ready for New Measurements")
        )
        field_index = next(i for i, line in enumerate(lines) if line.strip() == "Field Picture Checklist")
    except StopIteration:
        return text, []

    completed = _extract_blocks(lines, completed_index + 1, pending_index)
    pending = _extract_blocks(lines, pending_index + 1, field_index)
    picture_updates = {
        normalize_address(address): status
        for address, status in (picture_updates or {}).items()
    }
    promoted = []

    def update_picture(block: list[str]) -> list[str]:
        address = normalize_address(_address_from_heading(block[0]))
        return _set_picture_status(block, picture_updates.get(address))

    completed = [_promote(update_picture(block), completion_date) for block in completed]
    still_pending = []
    for block in pending:
        block = update_picture(block)
        if measurements_complete(block):
            promoted.append(_address_from_heading(block[0]))
            completed.append(_promote(block, completion_date))
        else:
            still_pending.append(_normalize_block(_set_completion_date(block)))

    primary_street = _primary_street(lines[pending_index].strip())
    primary_blocks = [block for block in still_pending if _same_street(block, primary_street)]
    additional_blocks = [block for block in still_pending if not _same_street(block, primary_street)]

    rebuilt = list(lines[:completed_index + 1])
    rebuilt.append("")
    if completed:
        for block in completed:
            rebuilt.extend(block)
            rebuilt.append("")
    else:
        rebuilt.extend(["None completed yet.", ""])

    rebuilt.extend([lines[pending_index].strip(), ""])
    for block in primary_blocks:
        rebuilt.extend(block)
        rebuilt.append("")
    if additional_blocks:
        rebuilt.extend(["Additional Project Address", ""])
        for block in additional_blocks:
            rebuilt.extend(block)
            rebuilt.append("")
    rebuilt.extend(lines[field_index:])
    return "\n".join(rebuilt).rstrip() + "\n", promoted


def _color(value: dict) -> dict:
    return {"color": {"rgbColor": value}}


def _paragraph_style(line: str, named_style: str) -> tuple[dict | None, str | None]:
    upper = line.upper()
    if named_style == "TITLE":
        return {"foregroundColor": _color(_COLORS["navy"]), "bold": True}, "foregroundColor,bold"
    if "COMPLETE" in upper and "NOT COMPLETED" not in upper and named_style == "HEADING_2":
        return {
            "foregroundColor": _color(_COLORS["green"]),
            "backgroundColor": _color(_PALE_GREEN),
            "bold": True,
        }, "foregroundColor,backgroundColor,bold"
    if named_style in {"HEADING_1", "HEADING_2"}:
        return {"foregroundColor": _color(_COLORS["navy"]), "bold": True}, "foregroundColor,bold"
    if line.startswith("Status: NOT COMPLETED"):
        return {
            "foregroundColor": _color(_COLORS["red"]),
            "backgroundColor": _color(_PALE_RED),
            "bold": True,
        }, "foregroundColor,backgroundColor,bold"
    if line.startswith(("Contractor:", "Inspected By:")):
        return {"foregroundColor": _color(_COLORS["teal"]), "bold": True}, "foregroundColor,bold"
    if line.startswith("Service:") or line.startswith("Material / size:") or "DUCTILE IRON" in upper:
        return {"foregroundColor": _color(_COLORS["teal"]), "bold": True}, "foregroundColor,bold"
    if line.startswith(("HS:", "CH:", "HC:", "MC:", "LS:", "RS:", "Double Curbed:")):
        return {"foregroundColor": _color(_COLORS["blue"]), "bold": True}, "foregroundColor,bold"
    if line.startswith(("Reference points / notes:", "Address note:", "Registry notation:")):
        return {"foregroundColor": _color(_COLORS["purple"]), "italic": True}, "foregroundColor,italic"
    if line.startswith("Pictures:"):
        return {"foregroundColor": _color(_COLORS["orange"]), "bold": True}, "foregroundColor,bold"
    if line.startswith("Completion Date:"):
        color = _COLORS["green"] if line.split(":", 1)[1].strip() else _COLORS["gray"]
        return {"foregroundColor": _color(color), "bold": True}, "foregroundColor,bold"
    if re.match(r"^\d+\.", line):
        return {"foregroundColor": _color(_COLORS["gray"])}, "foregroundColor"
    return None, None


def _format_requests(text: str, tab_id: str | None) -> list[dict]:
    requests = []
    h1 = {
        "Purpose", "Street Main", "Completed Addresses",
        "Additional Project Address", "Field Picture Checklist", "Registry Source",
    }
    offset = 1
    for line_number, line in enumerate(text.splitlines()):
        start = offset
        end = start + len(line) + 1
        offset = end
        if not line:
            continue
        if line_number == 0:
            named_style = "TITLE"
        elif line in h1 or line.endswith("Parcels Ready for New Measurements"):
            named_style = "HEADING_1"
        elif _ADDRESS_HEADING.match(line):
            named_style = "HEADING_2"
        else:
            named_style = "NORMAL_TEXT"
        text_range = {"startIndex": start, "endIndex": end}
        if tab_id:
            text_range["tabId"] = tab_id
        if named_style != "NORMAL_TEXT":
            requests.append({
                "updateParagraphStyle": {
                    "range": text_range,
                    "paragraphStyle": {"namedStyleType": named_style},
                    "fields": "namedStyleType",
                }
            })
        style, fields = _paragraph_style(line, named_style)
        if style:
            requests.append({
                "updateTextStyle": {
                    "range": text_range,
                    "textStyle": style,
                    "fields": fields,
                }
            })
    return requests


def _document_text(body: dict) -> str:
    return "".join(
        element.get("textRun", {}).get("content", "")
        for item in body.get("content", [])
        for element in item.get("paragraph", {}).get("elements", [])
    )


def sync_document_completion(
    docs,
    document_id: str,
    picture_updates: dict[str, str] | None = None,
) -> list[str]:
    document = docs.documents().get(
        documentId=document_id,
        includeTabsContent=True,
    ).execute()
    tabs = document.get("tabs") or []
    if not tabs:
        return []
    tab = tabs[0]
    tab_id = tab.get("tabProperties", {}).get("tabId")
    body = tab.get("documentTab", {}).get("body", {})
    current = _document_text(body)
    updated, promoted = transform_document_text(current, picture_updates)
    if updated == current:
        return promoted

    end_index = body.get("content", [])[-1].get("endIndex", 1)
    content_range = {"startIndex": 1, "endIndex": max(1, end_index - 1)}
    location = {"index": 1}
    if tab_id:
        content_range["tabId"] = tab_id
        location["tabId"] = tab_id
    requests = [
        {"deleteContentRange": {"range": content_range}},
        {"insertText": {"location": location, "text": updated}},
        *_format_requests(updated, tab_id),
    ]
    docs.documents().batchUpdate(
        documentId=document_id,
        body={
            "requests": requests,
            "writeControl": {"requiredRevisionId": document["revisionId"]},
        },
    ).execute()
    return promoted


def sync_project_documents(drive, docs, project_folder_id: str) -> dict[str, list[str]]:
    response = drive.files().list(
        q=(
            f"'{project_folder_id}' in parents and "
            "mimeType='application/vnd.google-apps.document' and trashed=false"
        ),
        fields="files(id,name)",
        pageSize=200,
    ).execute()
    result = {}
    for item in response.get("files", []):
        promoted = sync_document_completion(docs, item["id"])
        if promoted:
            result[item.get("name", item["id"])] = promoted
    return result
