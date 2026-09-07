"""
status.py — Example Utility Water Automation — Live Status Dashboard
Zero external dependencies (sqlite3 + pathlib only).

Usage:
  python status.py
  python status.py --json     # machine-readable output
"""

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH    = Path("db/records.db")
OUTPUT_DIR = Path("output")
TIECARD_DIR= OUTPUT_DIR / "tiecards"


# ─── ANSI COLORS (disabled on Windows if no ANSI support) ────────────────────

import sys, os
_COLOR = sys.stdout.isatty() and os.name != "nt" or os.environ.get("FORCE_COLOR")

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text

def red(s):    return _c("31;1", s)
def yellow(s): return _c("33;1", s)
def green(s):  return _c("32;1", s)
def cyan(s):   return _c("36;1", s)
def bold(s):   return _c("1", s)
def dim(s):    return _c("2", s)


# ─── DB QUERIES ──────────────────────────────────────────────────────────────

def db_connect() -> sqlite3.Connection | None:
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    r = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return r is not None


def tiecard_stats(conn: sqlite3.Connection) -> dict:
    if not table_exists(conn, "records"):
        return {}
    total   = conn.execute("SELECT COUNT(*) FROM records WHERE record_type='tie_card'").fetchone()[0]
    flagged = conn.execute("SELECT COUNT(*) FROM records WHERE record_type='tie_card' AND flagged=1").fetchone()[0]
    last_r  = conn.execute(
        "SELECT processed_at FROM records WHERE record_type='tie_card' ORDER BY processed_at DESC LIMIT 1"
    ).fetchone()
    return {
        "total":   total,
        "flagged": flagged,
        "last_ocr": last_r[0] if last_r else None,
    }


def bill_stats(conn: sqlite3.Connection) -> dict:
    if not table_exists(conn, "records"):
        return {}
    total = conn.execute("SELECT COUNT(*) FROM records WHERE record_type='bill'").fetchone()[0]
    return {"total": total}


def pipe_spec_stats(conn: sqlite3.Connection) -> dict:
    if not table_exists(conn, "records"):
        return {}
    total = conn.execute("SELECT COUNT(*) FROM records WHERE record_type='pipe_spec'").fetchone()[0]
    return {"total": total}


def udf_stats(conn: sqlite3.Connection) -> dict:
    if not table_exists(conn, "zone_status"):
        return {}
    total    = conn.execute("SELECT COUNT(*) FROM zone_status").fetchone()[0]
    complete = conn.execute("SELECT COUNT(*) FROM zone_status WHERE latest_status='complete'").fetchone()[0]
    pending  = conn.execute(
        "SELECT COUNT(*) FROM zone_status WHERE latest_status='pending' OR latest_status IS NULL OR latest_status=''"
    ).fetchone()[0]
    in_prog  = conn.execute("SELECT COUNT(*) FROM zone_status WHERE latest_status='in_progress'").fetchone()[0]
    deferred = conn.execute("SELECT COUNT(*) FROM zone_status WHERE latest_status='deferred'").fetchone()[0]
    p_flags  = conn.execute("SELECT COUNT(*) FROM zone_status WHERE pressure_flag=1").fetchone()[0]
    no_clear = conn.execute("SELECT COUNT(*) FROM zone_status WHERE turbidity_clear=0").fetchone()[0]
    last_r   = conn.execute("SELECT updated_at FROM zone_status ORDER BY updated_at DESC LIMIT 1").fetchone()
    return {
        "total": total, "complete": complete, "pending": pending,
        "in_progress": in_prog, "deferred": deferred,
        "pressure_flags": p_flags, "turbidity_not_cleared": no_clear,
        "last_field_log": last_r[0] if last_r else None,
    }


def anomaly_stats(conn: sqlite3.Connection) -> dict:
    if not table_exists(conn, "anomaly_reviews"):
        return {}
    total   = conn.execute("SELECT COUNT(*) FROM anomaly_reviews").fetchone()[0]
    flagged = conn.execute("SELECT COUNT(*) FROM anomaly_reviews WHERE has_anomaly=1").fetchone()[0]
    high    = conn.execute("SELECT COUNT(*) FROM anomaly_reviews WHERE severity='high'").fetchone()[0]
    last_r  = conn.execute("SELECT reviewed_at FROM anomaly_reviews ORDER BY reviewed_at DESC LIMIT 1").fetchone()
    return {
        "reviewed": total, "flagged": flagged, "high_severity": high,
        "last_check": last_r[0] if last_r else None,
    }


def flush_log_stats(conn: sqlite3.Connection) -> dict:
    if not table_exists(conn, "flush_log"):
        return {}
    total  = conn.execute("SELECT COUNT(*) FROM flush_log").fetchone()[0]
    last_r = conn.execute("SELECT created_at FROM flush_log ORDER BY created_at DESC LIMIT 1").fetchone()
    return {"entries": total, "last_entry": last_r[0] if last_r else None}


# ─── FILE SYSTEM STATS ───────────────────────────────────────────────────────

def pdf_stats() -> dict:
    if not TIECARD_DIR.exists():
        return {"count": 0, "merged": 0}
    pdfs   = list(TIECARD_DIR.glob("tiecard_*.pdf"))
    merged = list(TIECARD_DIR.glob("tiecards_merged_*.pdf"))
    return {"count": len(pdfs), "merged": len(merged)}


def output_stats() -> dict:
    if not OUTPUT_DIR.exists():
        return {}
    csvs   = list(OUTPUT_DIR.glob("*.csv"))
    excels = list(OUTPUT_DIR.glob("*.xlsx"))
    return {"csv_files": len(csvs), "excel_files": len(excels)}


# ─── LAST-RUN TIMESTAMPS ─────────────────────────────────────────────────────

def last_modified(pattern: str) -> str | None:
    """Most recent modification time of files matching glob pattern."""
    files = sorted(Path(".").glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    ts = datetime.fromtimestamp(files[0].stat().st_mtime)
    return ts.strftime("%Y-%m-%d %H:%M")


def pipeline_timestamps() -> dict:
    return {
        "pipeline_a_ocr":        last_modified("pipeline_a_ocr.py"),
        "pipeline_b_flushing":   last_modified("pipeline_b_flushing.py"),
        "pipeline_c_tiecard_pdf":last_modified("pipeline_c_tiecard_pdf.py"),
        "pipeline_c_field":      last_modified("pipeline_c_field.py"),
        "pipeline_d_sequence":   last_modified("pipeline_d_sequence.py"),
        "pipeline_e_anomaly":    last_modified("pipeline_e_anomaly.py"),
    }


def last_output_run() -> dict:
    """Use output file timestamps as proxy for last pipeline execution."""
    return {
        "last_csv":    _newest_file(OUTPUT_DIR.glob("*.csv")),
        "last_excel":  _newest_file(OUTPUT_DIR.glob("*.xlsx")),
        "last_pdf":    _newest_file(TIECARD_DIR.glob("tiecard_*.pdf")) if TIECARD_DIR.exists() else None,
        "last_sequence": _newest_file(OUTPUT_DIR.glob("flush_sequence_*.csv")),
        "last_anomaly":  _newest_file(OUTPUT_DIR.glob("anomaly_report_*.csv")),
        "last_field_csv":_newest_file(OUTPUT_DIR.glob("field_log_*.csv")),
    }


def _newest_file(paths) -> str | None:
    files = sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    return datetime.fromtimestamp(files[0].stat().st_mtime).strftime("%Y-%m-%d %H:%M")


# ─── DISPLAY ─────────────────────────────────────────────────────────────────

def bar(label: str, value, total: int, width: int = 20, color_fn=green) -> str:
    if total == 0:
        filled = 0
    else:
        filled = int((value / total) * width)
    bar_str = "█" * filled + "░" * (width - filled)
    pct = f"{value/total*100:.0f}%" if total else "—"
    return f"  {label:<18} {color_fn(bar_str)}  {value}/{total} ({pct})"


SEP = dim("─" * 64)


def print_dashboard(data: dict):
    tc  = data["tiecards"]
    udf = data["udf"]
    an  = data["anomalies"]
    pdf = data["pdfs"]
    out = data["outputs"]
    fl  = data["flush_log"]
    ts  = data["output_timestamps"]

    print()
    print(bold("╔══════════════════════════════════════════════════════════════╗"))
    print(bold("║    EXAMPLE UTILITY WATER AUTOMATION — STATUS DASHBOARD           ║"))
    print(bold(f"║    {datetime.now().strftime('%Y-%m-%d  %H:%M:%S'):<56}║"))
    print(bold("╚══════════════════════════════════════════════════════════════╝"))

    # ── OCR / Records ──
    print()
    print(cyan(bold("  ── PIPELINE A: OCR RECORDS ──")))
    if tc:
        flagged_color = red if tc.get("flagged", 0) > 0 else green
        print(f"  Tie-cards in DB:   {bold(str(tc.get('total',0)))}  "
              f"({flagged_color(str(tc.get('flagged',0)) + ' flagged')})")
        print(f"  Bills:             {data['bills'].get('total', 0)}")
        print(f"  Pipe specs:        {data['pipe_specs'].get('total', 0)}")
        print(f"  Last OCR run:      {dim(tc.get('last_ocr') or 'never')}")
    else:
        print(dim("  No records table found — run pipeline_a_ocr.py first"))

    # ── PDFs ──
    print()
    print(cyan(bold("  ── PIPELINE C: TIE-CARD PDFs ──")))
    print(f"  PDFs generated:    {bold(str(pdf.get('count', 0)))}")
    print(f"  Merged PDFs:       {pdf.get('merged', 0)}")
    print(f"  Last PDF:          {dim(ts.get('last_pdf') or 'never')}")

    # ── UDF Zones ──
    print()
    print(cyan(bold("  ── PIPELINE B/C-FIELD: UDF ZONES (43 total) ──")))
    if udf:
        total_zones = 43
        complete    = udf.get("complete", 0)
        pending     = udf.get("pending", 0)
        in_prog     = udf.get("in_progress", 0)
        deferred    = udf.get("deferred", 0)
        logged      = udf.get("total", 0)
        p_flags     = udf.get("pressure_flags", 0)

        print(bar("Complete",   complete,  total_zones, color_fn=green))
        print(bar("In Progress",in_prog,   total_zones, color_fn=yellow))
        print(bar("Pending",    pending,   total_zones, color_fn=dim))
        print(bar("Deferred",   deferred,  total_zones, color_fn=yellow))
        if p_flags:
            print(f"  {red('⚠  PRESSURE FLAGS:')}      {red(str(p_flags))} zone(s) below 20 PSI minimum")
        if udf.get("turbidity_not_cleared", 0):
            print(f"  {yellow('⚠  TURBIDITY NOT CLEARED:')} {udf['turbidity_not_cleared']} zone(s)")
        print(f"  Field log entries: {fl.get('entries', 0)}  "
              f"(last: {dim(fl.get('last_entry') or 'never')})")
        print(f"  Last Sheets sync:  {dim(ts.get('last_excel') or 'never')}")
    else:
        print(dim("  No zone_status table — run pipeline_c_field.py --log first"))

    # ── Anomaly Detector ──
    print()
    print(cyan(bold("  ── PIPELINE E: ANOMALY REVIEWS ──")))
    if an:
        reviewed = an.get("reviewed", 0)
        flagged  = an.get("flagged", 0)
        high     = an.get("high_severity", 0)
        flag_c   = red if flagged > 0 else green
        print(f"  Records reviewed:  {reviewed}")
        print(f"  Anomalies flagged: {flag_c(str(flagged))}"
              + (f"  ({red(str(high) + ' HIGH severity')})" if high else ""))
        print(f"  Last check:        {dim(an.get('last_check') or 'never')}")
    else:
        print(dim("  No anomaly_reviews table — run pipeline_e_anomaly.py --check first"))

    # ── Output files ──
    print()
    print(cyan(bold("  ── OUTPUT FILES ──")))
    print(f"  CSV exports:       {out.get('csv_files', 0)}   (last: {dim(ts.get('last_csv') or 'never')})")
    print(f"  Excel reports:     {out.get('excel_files', 0)}   (last: {dim(ts.get('last_excel') or 'never')})")
    print(f"  Flush sequences:   (last: {dim(ts.get('last_sequence') or 'never')})")
    print(f"  Field log CSVs:    (last: {dim(ts.get('last_field_csv') or 'never')})")

    # ── Recommended next actions ──
    actions = []
    if tc and tc.get("flagged", 0):
        actions.append(f"Review {tc['flagged']} flagged tie-card(s):  "
                       "python pipeline_c_tiecard_pdf.py --flagged-only --review-sheet")
    if an and an.get("flagged", 0):
        actions.append(f"Inspect {an['flagged']} AWWA anomaly flag(s):  "
                       "python pipeline_e_anomaly.py --report")
    if udf and udf.get("pressure_flags", 0):
        actions.append(f"Supervisor notification needed — {udf['pressure_flags']} pressure flag(s) below 20 PSI")
    if tc and tc.get("total", 0) > pdf.get("count", 0):
        diff = tc["total"] - pdf["count"]
        actions.append(f"Generate PDFs for {diff} unrendered tie-card(s):  "
                       "python pipeline_c_tiecard_pdf.py")

    if actions:
        print()
        print(cyan(bold("  ── RECOMMENDED ACTIONS ──")))
        for a in actions:
            print(f"  {yellow('►')} {a}")

    print()
    print(SEP)
    print()


# ─── JSON OUTPUT ─────────────────────────────────────────────────────────────

def print_json(data: dict):
    # Flatten for machine consumption
    print(json.dumps(data, indent=2, default=str))


# ─── MAIN ────────────────────────────────────────────────────────────────────

def collect_data() -> dict:
    conn = db_connect()
    if conn:
        tc   = tiecard_stats(conn)
        bills= bill_stats(conn)
        ps   = pipe_spec_stats(conn)
        udf  = udf_stats(conn)
        an   = anomaly_stats(conn)
        fl   = flush_log_stats(conn)
        conn.close()
    else:
        tc = bills = ps = udf = an = fl = {}

    return {
        "tiecards":   tc,
        "bills":      bills,
        "pipe_specs": ps,
        "udf":        udf,
        "anomalies":  an,
        "flush_log":  fl,
        "pdfs":       pdf_stats(),
        "outputs":    output_stats(),
        "output_timestamps": last_output_run(),
        "generated_at": datetime.now().isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Example Utility Water Automation — Live Status Dashboard"
    )
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()

    data = collect_data()

    if args.json:
        print_json(data)
    else:
        print_dashboard(data)


if __name__ == "__main__":
    main()
