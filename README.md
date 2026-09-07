UtiliVault public portfolio snapshot.

UtiliVault is a portfolio snapshot of field automation for municipal water utilities. It connects Drive-based intake, document processing, tie-card rendering, and a small field API/mobile client.

> Portfolio/demo snapshot. Production credentials, customer records, live Drive identifiers, and private operational notes are intentionally excluded. Configure isolated test resources before enabling integrations.

## Included

- Python automation for Drive intake, OCR/photo processing, tie-card rendering, and document completion.
- API server and Expo/React Native field client.
- Synthetic/unit tests and container/systemd deployment examples.
- Placeholder-only environment configuration.

## Architecture

Field technician -> Expo mobile client -> API server
                                     |
                                     v
                         Drive intake + reference docs
                                     |
                                     v
                 OCR / image analysis / deterministic renderer
                                     |
                    printable tie card + digital document

Drive is the integration boundary in the example architecture. The watcher is designed around idempotent processing, explicit output stages, and archive-after-success behavior. This public copy is not a turnkey production deployment.

## Stack

Python 3.11+, Pillow/libtiff, OpenCV, Google Drive/Docs APIs, FastAPI/Uvicorn, Expo/React Native, Docker Compose, systemd, and Pytest.

## Run locally

1. Create a virtual environment and install dependencies:

   python -m venv .venv
   python -m pip install -r requirements.txt

2. Copy `.env.example` to `.env` and replace every `YOUR_*` value with resources from an isolated test Google account. Keep credential JSON outside the repository.

3. Run the API locally:

   python -m uvicorn api_server:app --reload

4. Run tests:

   python -m pytest

Drive watcher helpers require valid test resources. Never point them at customer or production data.

## Mobile client
The mobile client lives under the mobile directory and uses Expo. Set its API base URL for your own development environment. No customer media is included.

## Repository safety
Ignore rules cover credentials, OAuth state, service-account files, private keys, generated records, scans, output/state directories, logs, APKs, local build artifacts, and internal handoff notes. Scan the working tree for secrets and real identifiers before publishing changes.

## Related work
- HydrantLoop: https://hydrantloop.com
- GitHub: https://github.com/Hydrada

This is a portfolio/demo publication. See the repository owner for reuse and licensing questions.
