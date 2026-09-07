# UtiliVault Field — mobile app

Phone app for field techs: type the tie-card data, snap the house photo,
tap **Submit** — the UtiliVault PC draws the card immediately (no Vision
call), uploads the digital TIF to Drive folder 14, and sends the finished
pages back to the phone for review. **Edit** reopens the form prefilled and
regenerates in place (rename-safe: old files are cleaned up locally and in
Drive).

```
Home ──＋ New Card──▶ Form ──Submit──▶ Preview (swipe 3 pages)
  │                    ▲                  │
  │                    └──── ✏️ Edit ─────┘
  └─ tap a card ─────▶ Preview of any existing card
```

## Server side (the UtiliVault PC)

```powershell
py water_automation\api_server.py            # 0.0.0.0:8791, Drive upload ON
py water_automation\api_server.py --no-drive # local-only testing
```

Optional auth: set `UTILIVAULT_API_KEY` in the PC's environment (or `.env`),
then enter the same key in the app's Settings.

Find the PC's LAN IP with `ipconfig` (IPv4 Address) — that plus the port is
what goes in the app's Settings, e.g. `192.168.1.50:8791`.

## Phone side — development / crew testing (Expo Go)

1. `cd water_automation\mobile`
2. `npm install`
3. `npx expo start`
4. Install **Expo Go** from the App Store / Play Store on the phone.
5. Scan the QR code in the terminal. Phone and PC must share a network.
6. First launch opens Settings — enter the server address, **Test
   Connection**, Save.

## Building a real installable APK

One-time: create a free account at https://expo.dev/signup, then log in
from a terminal (`npx eas-cli login`) or set `EXPO_TOKEN` from an access
token at https://expo.dev/settings/access-tokens.

```powershell
cd water_automation\mobile
npx eas-cli build -p android --profile preview     # builds in the cloud, ~10-15 min
```

When it finishes, EAS prints a download URL for the `.apk`. Grab it locally
(`npx eas-cli build:list` finds it again later), then push it to Drive so it
can be downloaded on any phone, anywhere:

```powershell
py ..\upload_apk_to_drive.py path\to\UtiliVault-Field.apk --public-link
```

This uploads to Drive folder **"16 - Mobile App (APK Download)"** and (with
`--public-link`) makes the file downloadable by link without requiring a
Google sign-in on the phone — open the link, tap Download, tap the
downloaded file, allow "install from unknown sources" if Android asks.
Every rebuild replaces the old APK at the same name, so re-share the same
link after each update.

iOS needs an Apple Developer account ($99/yr) and is out of scope for now;
Android sideloading is free. A multi-municipality rollout would eventually
mean proper Play Store builds — later phase.

## Reaching the server from outside the house

The phone can only reach `api_server.py` if it can route to the PC. On the
home Wi-Fi that's the LAN IP; away from home, use **Tailscale**
(https://tailscale.com) — install it on the PC and the phone with the same
account, then use the PC's `100.x.x.x` Tailscale address in the app's
Settings (or bake it into `src/defaults.js` as `DEFAULT_SERVER_URL` before
building, so the app works with zero setup on first launch).

## Field workflow notes

- **Nothing on the form is required** except *either* an address or a reg
  number (the card file needs a name). Blank fields print blank, exactly
  like a half-filled paper card.
- Material chips (Copper / Lead / Galv / …) are shortcuts — the text box
  accepts anything.
- The house photo is optional and **never appears on the printable card**;
  it becomes page 3 of the digital TIF in Drive folder 14.
- Cards submitted from the app skip Claude Vision entirely (the tech typed
  the data) — faster and zero API cost per card.
- The Drive-folder-11 photo intake (red-text annotated photos) still works
  unchanged; the app is a second, parallel path into the same pipeline.
