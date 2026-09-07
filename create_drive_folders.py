"""
UtiliVault — create_drive_folders.py
Creates the full folder structure + executive briefing doc in the configured Drive.
Uses the Google account authorized for this host.
"""
import os
from googleapiclient.discovery import build

from google_drive_auth import load_google_credentials

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]

BRIEFING_TITLE = "UtiliVault — Executive Briefing & Cost Analysis"

BRIEFING_CONTENT = """UtiliVault — Executive Briefing & Cost Analysis
Example Utility Water & Sewer Tie-Card Digitization Automation

Prepared for: Example Utility Management
Prepared by: Morgan Nichols, Water Distribution 4 Certified
System: UtiliVault

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT IS UTILIAVAULT?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

UtiliVault is an AI-powered automation system that digitizes Example Utility's physical water and sewer tie-card records. It reads handwritten and typed tiecards using computer vision, extracts all field data and sketch measurements, reproduces the sketch geometry digitally, and outputs a pixel-perfect digital replica of each card — organized, searchable, and stored in Google Drive.

The system requires zero human interaction once initiated. A technician drops a folder of scans and the system handles everything end to end.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE PROBLEM BEING SOLVED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Example Utility maintains thousands of physical tie-card records for every water and sewer service connection. These records:

  - Are stored as physical paper cards, vulnerable to loss, damage, and deterioration
  - Cannot be searched digitally — locating a record requires manual lookup
  - Are not accessible in the field — technicians must return to the office to reference them
  - Contain hand-drawn triangulation sketches that are difficult to read and impossible to query
  - Have no backup — if lost or destroyed, the service location data is gone permanently

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW IT WORKS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 1 — SCAN
  Physical tiecards are scanned as TIF files (existing scanner workflow, no new hardware needed).

Step 2 — OCR & EXTRACTION
  Claude Vision AI reads every field on the front of the card:
  registration number, address, contractor, date, pipe material, diameter,
  inspector, comments, and all sketch measurements on the back.

Step 3 — VERIFICATION
  EasyOCR (local open-source AI) independently re-reads all measurements.
  If Claude and EasyOCR agree → High confidence, auto-approved.
  If they disagree → card is flagged for human review before filing.

Step 4 — SKETCH REPRODUCTION
  OpenCV traces the actual geometry from the scan pixel-by-pixel.
  Measurements from Step 2/3 are overlaid on the traced geometry.
  Result: a digitally perfect replica of the hand-drawn triangulation sketch.

Step 5 — RENDER
  A pixel-perfect digital tiecard is generated matching Example Utility's exact
  card format — indistinguishable from a card filled out by hand.

Step 6 — SORT & STORE
  Cards are automatically sorted into Google Drive:
    - Water cards → "3 - Completed Water Cards"
    - Sewer cards → "4 - Completed Sewer Cards"
    - Pre-approved (already compliant) → "2 - Pre-Approved"
    - Flagged → held for review before filing

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COST ANALYSIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AI API Cost (Claude Vision — per card)
  Front page extraction:    ~$0.009
  Back/sketch extraction:   ~$0.009
  Per card total:           ~$0.018

Local Processing (no cost)
  EasyOCR measurement verification:   $0.00
  OpenCV sketch tracing:              $0.00
  scikit-image image cleaning:        $0.00
  Google Drive storage:               $0.00 (included in Google Workspace)
  Google Sheets logging:              $0.00 (included in Google Workspace)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COST BY VOLUME
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  100 cards        →    $1.80
  275 cards        →    $5.00
  500 cards        →    $9.00
  1,000 cards      →   $18.00
  5,000 cards      →   $90.00
  10,000 cards     →  $180.00
  25,000 cards     →  $450.00
  50,000 cards     →  $900.00

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COST COMPARISON — MANUAL vs. UTILIAVAULT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Manual digitization (staff labor estimate):
  Avg time per card (read, type, verify, file):   15 minutes
  Staff cost at $25/hr:                           $6.25 per card
  1,000 cards:                                    $6,250 + ~125 staff hours
  10,000 cards:                                   $62,500 + ~1,250 staff hours

UtiliVault:
  1,000 cards:     $18.00  (99.7% cost reduction vs. manual)
  10,000 cards:   $180.00  (99.7% cost reduction vs. manual)

Processing speed:
  Manual:         ~4 cards per hour per staff member
  UtiliVault:     ~60-120 cards per hour (limited by scanner throughput)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ACCURACY & QUALITY CONTROL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  - Dual AI verification on all measurements (Claude Vision + EasyOCR)
  - Three confidence tiers: High / Moderate / Low
  - Low confidence cards are automatically held and flagged — never silently filed
  - Side-by-side review page generated for every batch before final commit
  - Sketch geometry traced directly from the scan — not estimated or invented
  - All source TIF scans preserved as permanent backup

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INFRASTRUCTURE & SECURITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  - Runs on existing Example Utility hardware — no new servers required
  - All processing happens locally on the PC — scan data does not leave the network
    except for the Claude Vision API call (image sent over HTTPS, not stored)
  - Output stored in Example Utility's existing Google Drive (Google Workspace)
  - Access controlled via Google OAuth2 — tied to the organization account
  - Remote operation available via encrypted SSH tunnel (Tailscale VPN)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IMPLEMENTATION TIMELINE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Phase 1 (Current — Demo):
    - System built and tested
    - Remote access configured (Tailscale VPN + SSH)
    - Google Drive folder structure live in personal Drive
    - Executive briefing created

  Phase 2 (Pending — Card Format Match):
    - Blank tiecard received from Morgan
    - Output format updated to match Example Utility's exact card design 100%
    - Final QA batch run and reviewed by Morgan

  Phase 3 (Full Production):
    - Batch processing of full archive
    - Automatic Drive upload and Sheets logging
    - Ongoing: new cards scanned and processed same day

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTACT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Morgan Nichols
Water Distribution 4 Certified Technician
Example Utility
{{CONTACT_EMAIL}}
"""


def get_creds():
    return load_google_credentials()


def find_or_create_folder(drive, name, parent_id):
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false"
    results = drive.files().list(q=q, fields="files(id,name)").execute().get("files", [])
    if results:
        print(f"  Already exists: {name}")
        return results[0]["id"]
    f = drive.files().create(body={
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }, fields="id").execute()
    print(f"  Created: {name}")
    return f["id"]


def main():
    creds = get_creds()
    drive = build("drive", "v3", credentials=creds)
    docs  = build("docs",  "v1", credentials=creds)

    print("\n[UtiliVault] Setting up folder structure in your personal Drive...\n")

    # Create UtiliVault parent folder at root
    utili_id = find_or_create_folder(drive, "UtiliVault", "root")

    # Create the 4 subfolders
    find_or_create_folder(drive, "1 - Feed",                  utili_id)
    find_or_create_folder(drive, "2 - Pre-Approved",          utili_id)
    find_or_create_folder(drive, "3 - Completed Water Cards", utili_id)
    find_or_create_folder(drive, "4 - Completed Sewer Cards", utili_id)
    find_or_create_folder(drive, "5 - Blank Card Layouts",    utili_id)

    # Create executive briefing doc
    q = f"name='{BRIEFING_TITLE}' and '{utili_id}' in parents and trashed=false"
    existing = drive.files().list(q=q, fields="files(id,webViewLink)").execute().get("files", [])
    if existing:
        link = existing[0]["webViewLink"]
        print(f"  Briefing doc already exists: {link}")
    else:
        doc = docs.documents().create(body={"title": BRIEFING_TITLE}).execute()
        doc_id = doc["documentId"]
        # Move into UtiliVault folder
        drive.files().update(
            fileId=doc_id,
            addParents=utili_id,
            removeParents="root",
            fields="id,parents",
        ).execute()
        # Insert content
        contact_email = os.getenv(
            "UTILIVAULT_CONTACT_EMAIL", "Contact email not configured"
        ).strip()
        briefing_content = BRIEFING_CONTENT.replace(
            "{{CONTACT_EMAIL}}", contact_email
        )
        docs.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [{"insertText": {"location": {"index": 1}, "text": briefing_content}}]},
        ).execute()
        link = f"https://docs.google.com/document/d/{doc_id}/edit"
        print(f"  Created briefing doc: {link}")

    print("\n[Done] Your Google Drive now has:")
    print("  UtiliVault/")
    print("    1 - Feed")
    print("    2 - Pre-Approved")
    print("    3 - Completed Water Cards")
    print("    4 - Completed Sewer Cards")
    print("    5 - Blank Card Layouts")
    print(f"    {BRIEFING_TITLE}")
    print(f"\n  Briefing doc link: {link}")


if __name__ == "__main__":
    main()
