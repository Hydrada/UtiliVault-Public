"""
UtiliVault — registry_lookup.py
Look up the existing water REGISTER # for an address, from the District's
"Water Registry" Google Sheet, so a new tie card reuses the real registry
number instead of the tech typing it (or a fresh one being invented).

The registry sheet has four columns:

    REGISTER #   the number we want to reuse (e.g. 10107)
    LOC #        the house / location number (e.g. 117)
    UNIT #       optional unit, present on ~1,600 of ~18,400 rows
    LOCATION     the street, uppercase (e.g. "A ST", "CONCORD ST")

⚠️ An address is NOT guaranteed to map to a single register number. 782
addresses (LOC # + LOCATION) have more than one — a property can have several
service connections. `lookup()` therefore returns a LIST of candidates. When
there is exactly one, the caller can fill it in automatically; when there are
several, the caller must let the technician pick (the UNIT # is the usual
tie-breaker).

Offline behavior: the sheet is cached locally as CSV under WORK_ROOT. Once
cached, lookups need no internet — matching the pipeline's local-first design.
Refresh the cache with `refresh()` (or `--refresh` on the CLI) after the
registry changes.
"""
import csv
import io
import os
import re
import time
from pathlib import Path

from config import WORK_ROOT

# The "Water Registry" sheet. Overridable via .env so the new host can point at
# its own copy without a code change.
REGISTRY_SHEET_ID = os.getenv(
    "WATER_REGISTRY_SHEET_ID", "YOUR_WATER_REGISTRY_SHEET_ID"
)
CACHE_PATH = WORK_ROOT / "water_registry_cache.csv"
CACHE_MAX_AGE_S = 24 * 3600            # re-pull at most once a day on demand

# Street-suffix normalization so "12 Maple St" matches a registry "MAPLE ST".
_SUFFIX = {
    "STREET": "ST", "AVENUE": "AVE", "ROAD": "RD", "DRIVE": "DR",
    "LANE": "LN", "COURT": "CT", "PLACE": "PL", "CIRCLE": "CIR",
    "TERRACE": "TER", "BOULEVARD": "BLVD", "HIGHWAY": "HWY",
    "PARKWAY": "PKWY", "SQUARE": "SQ", "PATH": "PATH",
}


def _norm_street(street: str) -> str:
    """Uppercase, collapse spaces, and canonicalize the street suffix."""
    s = re.sub(r"\s+", " ", (street or "").strip().upper())
    s = s.rstrip(".")
    parts = s.split(" ")
    if parts and parts[-1] in _SUFFIX:
        parts[-1] = _SUFFIX[parts[-1]]
    return " ".join(parts)


def _norm_house(house) -> str:
    """House number as a bare string; keep letters (e.g. '12A') but drop spaces."""
    return re.sub(r"\s+", "", str(house or "").strip().upper())


# --------------------------------------------------------------------------
# Cache management
# --------------------------------------------------------------------------
def _cache_fresh() -> bool:
    return CACHE_PATH.exists() and (time.time() - CACHE_PATH.stat().st_mtime) < CACHE_MAX_AGE_S


def refresh(drive=None) -> Path:
    """Pull the registry sheet to the local CSV cache. Needs internet."""
    if drive is None:
        from field_intake_watcher import get_drive
        drive = get_drive()
    data = drive.files().export(
        fileId=REGISTRY_SHEET_ID, mimeType="text/csv").execute()
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, CACHE_PATH)
    return CACHE_PATH


def _ensure_cache(drive=None) -> None:
    if not _cache_fresh():
        try:
            refresh(drive)
        except Exception:                                     # noqa: BLE001
            # Offline and no fresh cache: fall back to any stale cache we have.
            if not CACHE_PATH.exists():
                raise


# --------------------------------------------------------------------------
# Index + lookup
# --------------------------------------------------------------------------
_index: dict[tuple[str, str], list[dict]] | None = None
_index_mtime: float = 0.0


def _load_index(drive=None) -> dict[tuple[str, str], list[dict]]:
    """Build (or reuse) an in-memory index keyed by (house, street)."""
    global _index, _index_mtime
    _ensure_cache(drive)
    mtime = CACHE_PATH.stat().st_mtime
    if _index is not None and mtime == _index_mtime:
        return _index

    idx: dict[tuple[str, str], list[dict]] = {}
    with CACHE_PATH.open(encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            reg = (row.get("REGISTER #") or "").strip()
            if not reg:
                continue
            key = (_norm_house(row.get("LOC #")), _norm_street(row.get("LOCATION")))
            idx.setdefault(key, []).append({
                "register": reg,
                "unit": (row.get("UNIT #") or "").strip(),
                "location": (row.get("LOCATION") or "").strip(),
                "loc_no": (row.get("LOC #") or "").strip(),
            })
    _index, _index_mtime = idx, mtime
    return idx


def lookup(house_no, street, unit=None, drive=None) -> list[dict]:
    """
    Return candidate registry rows for an address, best match first.

    Each candidate is {register, unit, location, loc_no}. Zero results means
    the address isn't in the registry (a genuinely new service). One result is
    the auto-fill case. Multiple results must be disambiguated by the caller —
    passing `unit` filters to an exact unit match when one exists.
    """
    idx = _load_index(drive)
    hits = idx.get((_norm_house(house_no), _norm_street(street)), [])
    if unit:
        u = str(unit).strip().upper()
        exact = [h for h in hits if h["unit"].upper() == u]
        if exact:
            return exact
    return list(hits)


def register_for(house_no, street, unit=None, drive=None) -> str | None:
    """Convenience: the register # only when the match is unambiguous."""
    hits = lookup(house_no, street, unit=unit, drive=drive)
    return hits[0]["register"] if len(hits) == 1 else None


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Look up the water REGISTER # for an address")
    p.add_argument("house", nargs="?", help="House / LOC number, e.g. 117")
    p.add_argument("street", nargs="?", help="Street, e.g. 'A ST' or 'Example Street'")
    p.add_argument("--unit", help="Unit number, if the property has one")
    p.add_argument("--refresh", action="store_true", help="Re-pull the registry sheet now")
    args = p.parse_args()

    if args.refresh:
        print("[Registry] Refreshing cache from Drive...")
        print("  cached ->", refresh())
    if not (args.house and args.street):
        if not args.refresh:
            p.print_help()
        raise SystemExit(0)

    results = lookup(args.house, args.street, unit=args.unit)
    if not results:
        print(f"No registry entry for {args.house} {args.street} "
              f"(new service — assign/enter a number).")
    elif len(results) == 1:
        r = results[0]
        print(f"REGISTER # {r['register']}  ({r['loc_no']} {r['location']}"
              + (f", unit {r['unit']}" if r['unit'] else "") + ")")
    else:
        print(f"{len(results)} candidates for {args.house} {args.street} "
              f"— technician must choose:")
        for r in results:
            print(f"  REGISTER # {r['register']}"
                  + (f"  unit {r['unit']}" if r['unit'] else ""))
