# UtiliVault cloud runtime decision

Status: accepted for implementation; production provisioning remains an owner action.

## Decision

Keep the public site on Cloudflare Pages. Run `field_intake_watcher.py --once`
every five minutes in a pinned Linux container on one small Debian 12 VM. Use a
systemd timer, a persistent data volume, a protected persistent credential
directory, journald logs, and a separate freshness monitor.

## Why this is the smallest reliable change

- It keeps the existing deterministic Python renderer and Claude image-analysis
  calls instead of rewriting them for Workers or changing model providers.
- Pillow/libtiff, OpenCV headless, Google Drive/Docs clients, and long image calls
  are ordinary container dependencies.
- One authoritative VM makes the local cross-process lock meaningful and gives
  OAuth refreshes, card assets, retry state, and logs durable storage.
- `--once` maps directly to the current five-minute schedule; systemd does not
  start a second instance while the service is active, and the application lock
  adds a second guard.
- The artifact is provider-neutral. A GCE, Hetzner, DigitalOcean, AWS, Azure, or
  other Debian VM can run it without pipeline changes.

## Rejected for the first migration

- Cloudflare Pages/Workers: not a fit for this native Python/TIFF workload.
- A multi-service serverless design: adds distributed locking, token/state
  persistence, and more failure boundaries without changing owner-visible behavior.
- Grok/Claude provider replacement: changes image interpretation while changing
  hosts, making parity failures difficult to isolate.

## Reliability boundaries

Drive is the system of record. Same-name TIFFs are updated in place, document
updates are idempotent, and a source photo is archived only after required
outputs and document status succeed. Local state is health/audit metadata, not a
second business database. Cross-host exclusivity is enforced operationally:
production enablement requires the explicit `ONE_WATCHER_CONFIRMED` gate after
the Windows task is stopped and verified stopped.

