"""
UtiliVault — config.py
Central path configuration so the whole project runs either from its original
home-PC location OR from a portable USB bundle, with no code changes either way.

  * If the environment variable UTILIVAULT_HOME is set (the portable launchers
    set it to the USB drive's bundle root), all data/work lives UNDER the drive.
  * If it is not set, the original home-PC locations are used unchanged, so the
    always-on watcher keeps working exactly as before.

Every module imports its directories from here instead of hardcoding them.
"""
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

_HOME = os.getenv("UTILIVAULT_HOME")

if _HOME:                                   # portable: everything under the drive
    ROOT = Path(_HOME)
    DESKTOP = ROOT / "data"
    DEMO_DIR = ROOT / "data" / "Demo Tiecards"
    WORK_ROOT = ROOT / "work"
else:                                       # home PC: original locations, unchanged
    DESKTOP = PROJECT_ROOT / "local" / "data"
    DEMO_DIR = PROJECT_ROOT / "local" / "data" / "Demo Tiecards"
    WORK_ROOT = PROJECT_ROOT / "local" / "work"

# ---- Derived data directories (same names/layout the code already used) ----
MANUAL_DIR   = DEMO_DIR / "manual_draws"
DIGITAL_DIR  = DEMO_DIR / "digital_with_photo"
PDF_DIR      = DEMO_DIR / "print_pdfs"
REVIEW_DIR   = DEMO_DIR / "digital_REVIEW"
CLEAN_DIR    = DEMO_DIR / "clean_display_photos"
FEED_OUT_DIR = DEMO_DIR / "feed_batch_output"
COMPARE_DIR  = DEMO_DIR / "side_by_side"
REVIEW_HTML  = DEMO_DIR / "_review.html"

# ---- Work / scratch directories ----
FIELD_WORK_DIR = WORK_ROOT / "field_intake_work"
FEED_WORK_DIR  = WORK_ROOT / "feed_batch_work"


def is_portable() -> bool:
    return bool(_HOME)


def ensure_dirs():
    """Create the standard data/work directories if missing."""
    for d in (DEMO_DIR, MANUAL_DIR, DIGITAL_DIR, PDF_DIR, REVIEW_DIR, CLEAN_DIR,
              FEED_OUT_DIR, COMPARE_DIR, FIELD_WORK_DIR, FEED_WORK_DIR):
        d.mkdir(parents=True, exist_ok=True)
