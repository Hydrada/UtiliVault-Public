"""
sheets_format.py — Example Utility Google Sheets Dashboard Formatter
Applies conditional formatting to the Zone Status sheet via Sheets API batchUpdate.

Color rules (applied in priority order — last applied wins on conflict):
  RED    — pressure_flag = 1  (residual < 20 PSI — notify supervisor)
  YELLOW — latest_status IN ('pending', 'in_progress', 'deferred', '') OR scheduled_date set
  GREEN  — latest_status = 'complete' AND pressure_flag = 0

Also applies header row formatting and column widths for readability.

Usage:
  python sheets_format.py --apply             # apply all formatting
  python sheets_format.py --apply --tab "Zone Status"   # override tab name
  python sheets_format.py --clear             # remove all conditional formatting rules
  python sheets_format.py --preview           # print rule plan without applying
"""

import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv()


# ─── COLOR PALETTE ───────────────────────────────────────────────────────────
# Sheets API uses 0.0–1.0 float RGB values

def rgb(r: int, g: int, b: int) -> dict:
    return {"red": r / 255, "green": g / 255, "blue": b / 255}


COLORS = {
    # Row fill colors
    "red_fill":    rgb(244, 199, 195),   # light red — pressure flag
    "yellow_fill": rgb(255, 243, 205),   # light yellow — scheduled / in progress
    "green_fill":  rgb(198, 239, 206),   # light green — complete
    "header_fill": rgb(41,  82,  163),   # District blue header
    "white":       rgb(255, 255, 255),

    # Text
    "header_text": rgb(255, 255, 255),
    "dark_text":   rgb(32,  32,  32),

    # Border
    "border":      rgb(180, 180, 180),
}


# ─── COLUMN MAP ──────────────────────────────────────────────────────────────
# These must match the column order written by pipeline_c_field.py push_to_sheets()
# for the "Zone Status" sheet.

ZONE_STATUS_COLUMNS = [
    "zone_id", "zone_name", "latest_status", "latest_log_date",
    "latest_gpm", "latest_psi", "turbidity_clear", "pressure_flag", "updated_at"
]
# 0-indexed column positions
COL = {name: i for i, name in enumerate(ZONE_STATUS_COLUMNS)}


# ─── CLIENT SETUP ────────────────────────────────────────────────────────────

def get_sheets_service():
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        print("[ERROR] google-api-python-client not installed. Run:")
        print("  pip install google-api-python-client")
        sys.exit(1)

    sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_path:
        print("[ERROR] GOOGLE_SERVICE_ACCOUNT_JSON not set in .env")
        sys.exit(1)

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(sa_path, scopes=scopes)
    return build("sheets", "v4", credentials=creds)


def get_sheet_id(service, spreadsheet_id: str, tab_name: str) -> int:
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for sheet in meta["sheets"]:
        if sheet["properties"]["title"] == tab_name:
            return sheet["properties"]["sheetId"]
    raise ValueError(f"Tab '{tab_name}' not found. Run pipeline_c_field.py --push-sheets first.")


# ─── RULE BUILDERS ───────────────────────────────────────────────────────────

def boolean_rule(sheet_id: int, start_row: int, end_row: int,
                 start_col: int, end_col: int,
                 formula: str, fill_color: dict) -> dict:
    """Single conditional formatting rule for a row range."""
    return {
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [{
                    "sheetId":          sheet_id,
                    "startRowIndex":    start_row,
                    "endRowIndex":      end_row,
                    "startColumnIndex": start_col,
                    "endColumnIndex":   end_col,
                }],
                "booleanRule": {
                    "condition": {
                        "type":   "CUSTOM_FORMULA",
                        "values": [{"userEnteredValue": formula}],
                    },
                    "format": {
                        "backgroundColor": fill_color,
                    },
                },
            },
            "index": 0,
        }
    }


def build_formatting_requests(sheet_id: int, max_rows: int = 500) -> list[dict]:
    """
    Build all batchUpdate requests for the Zone Status sheet.
    Rows 1..max_rows (0-indexed: 1..500); row 0 is the header.
    Columns A..I (indices 0–8).
    """
    data_start = 1      # row index after header
    data_end   = max_rows
    col_start  = 0
    col_end    = len(ZONE_STATUS_COLUMNS)

    # Column letters for CUSTOM_FORMULA references (1-indexed for Sheets formulas)
    # pressure_flag is column index COL["pressure_flag"] → letter
    def col_letter(idx: int) -> str:
        return chr(ord("A") + idx)

    pf_col    = col_letter(COL["pressure_flag"])    # e.g. "H"
    stat_col  = col_letter(COL["latest_status"])    # e.g. "C"
    sched_col = col_letter(COL["latest_log_date"])  # proxy for scheduled
    turb_col  = col_letter(COL["turbidity_clear"])  # e.g. "G"

    requests = []

    # 1. GREEN — complete and no pressure flag
    #    Formula anchored to col A of each data row ($A2 pattern)
    #    Use pressure_flag col and status col
    green_formula = (
        f'=AND(${stat_col}2="complete",${pf_col}2<>1)'
    )
    requests.append(boolean_rule(
        sheet_id, data_start, data_end, col_start, col_end,
        green_formula, COLORS["green_fill"]
    ))

    # 2. YELLOW — pending / in_progress / deferred / empty status
    yellow_formula = (
        f'=OR(${stat_col}2="pending",${stat_col}2="in_progress",'
        f'${stat_col}2="deferred",${stat_col}2="")'
    )
    requests.append(boolean_rule(
        sheet_id, data_start, data_end, col_start, col_end,
        yellow_formula, COLORS["yellow_fill"]
    ))

    # 3. RED — pressure flag set (highest priority, applied last so it wins)
    red_formula = f'=${pf_col}2=1'
    requests.append(boolean_rule(
        sheet_id, data_start, data_end, col_start, col_end,
        red_formula, COLORS["red_fill"]
    ))

    # 4. Header row formatting (row 0)
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId":          sheet_id,
                "startRowIndex":    0,
                "endRowIndex":      1,
                "startColumnIndex": 0,
                "endColumnIndex":   col_end,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": COLORS["header_fill"],
                    "textFormat": {
                        "foregroundColor": COLORS["header_text"],
                        "bold":            True,
                        "fontSize":        11,
                    },
                    "horizontalAlignment": "CENTER",
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
        }
    })

    # 5. Freeze header row
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {"frozenRowCount": 1},
            },
            "fields": "gridProperties.frozenRowCount",
        }
    })

    # 6. Column widths (pixels)
    widths = {
        COL["zone_id"]:        60,
        COL["zone_name"]:      200,
        COL["latest_status"]:  110,
        COL["latest_log_date"]:110,
        COL["latest_gpm"]:     80,
        COL["latest_psi"]:     80,
        COL["turbidity_clear"]:110,
        COL["pressure_flag"]:  100,
        COL["updated_at"]:     160,
    }
    for col_idx, px in widths.items():
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId":    sheet_id,
                    "dimension":  "COLUMNS",
                    "startIndex": col_idx,
                    "endIndex":   col_idx + 1,
                },
                "properties": {"pixelSize": px},
                "fields":     "pixelSize",
            }
        })

    # 7. Bold + border on data rows
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId":          sheet_id,
                "startRowIndex":    data_start,
                "endRowIndex":      data_end,
                "startColumnIndex": 0,
                "endColumnIndex":   col_end,
            },
            "cell": {
                "userEnteredFormat": {
                    "borders": {
                        "bottom": {
                            "style": "SOLID",
                            "color": COLORS["border"],
                            "width": 1,
                        }
                    },
                    "textFormat": {"fontSize": 10},
                    "verticalAlignment": "MIDDLE",
                }
            },
            "fields": "userEnteredFormat(borders,textFormat,verticalAlignment)",
        }
    })

    return requests


# ─── CLEAR RULES ─────────────────────────────────────────────────────────────

def build_clear_requests(sheet_id: int) -> list[dict]:
    return [{
        "deleteConditionalFormatRule": {
            "sheetId": sheet_id,
            "index":   0,
        }
    }]


# ─── APPLY ───────────────────────────────────────────────────────────────────

def apply_formatting(tab_name: str):
    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    if not spreadsheet_id:
        print("[ERROR] SPREADSHEET_ID not set in .env")
        sys.exit(1)

    service  = get_sheets_service()
    sheet_id = get_sheet_id(service, spreadsheet_id, tab_name)
    print(f"Applying formatting to '{tab_name}' (sheet ID: {sheet_id})...")

    # First, clear existing conditional formatting on this sheet
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing_rules = next(
        (s["conditionalFormats"]
         for s in meta["sheets"]
         if s["properties"]["sheetId"] == sheet_id),
        []
    )
    clear_requests = []
    for _ in existing_rules:
        clear_requests.append({"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": 0}})

    format_requests = build_formatting_requests(sheet_id)

    all_requests = clear_requests + format_requests
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": all_requests}
    ).execute()

    print(f"[OK] {len(format_requests)} formatting requests applied to '{tab_name}'.")
    print("     RED   = residual pressure < 20 PSI (pressure_flag = 1)")
    print("     YELLOW = pending / in_progress / deferred")
    print("     GREEN  = complete, no pressure flag")


def clear_formatting(tab_name: str):
    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    if not spreadsheet_id:
        print("[ERROR] SPREADSHEET_ID not set in .env")
        sys.exit(1)

    service  = get_sheets_service()
    sheet_id = get_sheet_id(service, spreadsheet_id, tab_name)
    meta     = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    rules    = next(
        (s["conditionalFormats"]
         for s in meta["sheets"]
         if s["properties"]["sheetId"] == sheet_id),
        []
    )
    if not rules:
        print(f"No conditional formatting rules found on '{tab_name}'.")
        return
    reqs = [{"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": 0}} for _ in rules]
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": reqs}
    ).execute()
    print(f"[OK] Cleared {len(rules)} conditional formatting rule(s) from '{tab_name}'.")


def preview_rules():
    print("\n=== Conditional Formatting Rule Plan ===")
    print("\n  Priority  Color    Condition")
    print("  --------  ------   ---------")
    print("  1 (low)   GREEN    latest_status = 'complete' AND pressure_flag ≠ 1")
    print("  2 (mid)   YELLOW   latest_status IN (pending, in_progress, deferred, '')")
    print("  3 (high)  RED      pressure_flag = 1  [overrides green/yellow]")
    print("\n  Header row: District blue background, white bold text, frozen")
    print("  Column widths auto-sized per field")
    print("\n  To apply: python sheets_format.py --apply")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Example Utility Google Sheets Dashboard Formatter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply",   action="store_true", help="Apply conditional formatting")
    parser.add_argument("--clear",   action="store_true", help="Remove all conditional formatting rules")
    parser.add_argument("--preview", action="store_true", help="Print rule plan without applying")
    parser.add_argument("--tab",     default="Zone Status", help="Sheet tab name (default: Zone Status)")
    args = parser.parse_args()

    if not any([args.apply, args.clear, args.preview]):
        parser.print_help()
        sys.exit(0)

    if args.preview:
        preview_rules()
    if args.clear:
        clear_formatting(args.tab)
    if args.apply:
        apply_formatting(args.tab)


if __name__ == "__main__":
    main()
