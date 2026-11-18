# Pharmavique app (React Native + Expo)

Arabic-first, right-to-left app built from `pharmavique-wireframes/` (phase 2 plan, owner decision
2026-11-18). It holds no drug data of its own: every screen calls the Pharmavique API.

## Screens so far

- `src/app/index.tsx`: B1 home (search box, sample searches, data source).
- `src/app/search.tsx`: B3/B4 search (as you type, loading, no result and error states).
- `src/app/drug/[register].tsx`: B8 drug page (registry fields and their source; no advice).

The screens were rebuilt on 2026-11-19 after the first versions were lost in a machine move
(they had never been pushed).

## Run it on a phone (Expo Go)

1. Phone and computer on the same Wi-Fi. Install **Expo Go** on the phone.
2. Start the API on all interfaces from the project root, so the phone can reach it:
   `uv run uvicorn pharmavique.bootstrap.api:create_app --factory --host 0.0.0.0 --port 8000`.
   Windows asks once whether Python may accept connections: allow it.
3. In `mobile/`: `npm ci` once, then
   `EXPO_PUBLIC_API_URL=http://<computer's LAN address>:8000 npx expo start`
   (PowerShell: `$env:EXPO_PUBLIC_API_URL="http://<address>:8000"; npx expo start`).
   Find the address with `ipconfig` (the Wi-Fi adapter's IPv4 address).
4. Scan the QR code with Expo Go (Android) or the camera (iPhone).

In a browser instead: `npx expo start --web --port 8081` (the API allows that origin by default,
see `PHARMAVIQUE_CORS_ORIGINS`).

Checks: `npx tsc --noEmit`.
