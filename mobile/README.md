# Pharmavique app (React Native + Expo)

Arabic-first, right-to-left app built from `pharmavique-wireframes/` (phase 2 plan, owner decision
2026-11-18). It holds no drug data of its own: every screen calls the Pharmavique API.

## Screens so far

- `src/app/index.tsx`: B1 home (search box, sample searches, data source).
- `src/app/search.tsx`: B3/B4 search (as you type, loading, no result and error states).
- `src/app/drug/[register].tsx`: B8 drug page (registry fields and their source; no advice).

## Run it

1. Start the API from the project root: `python -m uvicorn pharmavique.bootstrap.api:create_app --factory --port 8000`.
2. In `mobile/`: `npm install` once, then `npx expo start --web --port 8081` (or scan the QR code with Expo Go).
3. The API address comes from `EXPO_PUBLIC_API_URL` (default `http://127.0.0.1:8000`).

`node_modules` is a junction to `%USERPROFILE%\.node_modules\pharmavique-mobile` so OneDrive does
not sync it.
