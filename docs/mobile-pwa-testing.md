# Mobile & PWA Testing Guide

Estate Steward is a Progressive Web App (PWA): once installed, it lives on a phone's home screen and behaves like a native app. Several features — ID scanning, the inventory camera ("Quick Capture"), and voice story recording — are designed to be used on a phone, so testing on real hardware is part of normal development, not an edge case.

This page covers everything needed to get the app running on a phone for the first time, why some features behave differently over plain HTTP vs. HTTPS, and how to debug the most common "it doesn't work on my phone" issues.

If you just want HTTPS working as fast as possible, skip to [Cloudflare Tunnel Setup](./cloudflare-tunnel-setup.md) — that page is a standalone walkthrough of the one-time setup. This page assumes you've already done that, or are testing HTTP-only for now.

---

## 1. Why HTTPS matters here (read this first)

Browsers gate powerful device APIs — camera, microphone, geolocation — behind a "secure context" requirement: the page must be served over `https://`, or from `localhost`/`127.0.0.1`. A phone loading your dev machine's LAN IP (e.g. `http://192.168.1.42`) is **not** a secure context, even though it's on your trusted home network.

This plays out differently across the app's two camera/mic features:

| Feature | How it's implemented | Works over plain HTTP (LAN IP)? |
|---|---|---|
| ID scan / inventory photo capture | `<input type="file" accept="image/*" capture="environment">` — hands off to the OS's native camera app | ✅ Yes — file inputs with `capture` don't require a secure context |
| Voice story recording | `MediaRecorder` + `navigator.mediaDevices.getUserMedia({ audio: true })` — records live in-page | ❌ No — `getUserMedia` is hard-blocked outside a secure context, no fallback |

So: **you can test photo capture over a plain LAN IP, but voice recording requires real HTTPS.** [AdminVoiceRecorder.jsx](../frontend/src/components/AdminVoiceRecorder.jsx) checks this explicitly (its `isSecureContext()` helper) and will show "Voice recording requires a secure HTTPS connection" with the Record button disabled if you're not in a secure context. That message is not a bug — it's the browser's policy being surfaced honestly. The fix is to get HTTPS working, not to patch the component.

---

## 2. Quick start: same-Wi-Fi HTTP install

For a fast look at the UI, layout, and anything that doesn't touch the camera/mic, you don't need HTTPS at all:

```bash
./scripts/install_on_phone.sh
```

What this does:
1. Runs `npm run build` in `frontend/` (this regenerates the PWA manifest and service worker — a `vite dev` server alone won't produce an installable PWA).
2. Starts the Docker stack (`app`, `nginx`, and `db` etc. via `docker compose up -d`).
3. Restarts `nginx` (its bind mount of `frontend/dist` can otherwise serve a stale/empty directory on the very first build).
4. Detects whether `CLOUDFLARE_TUNNEL_TOKEN` is set in `.env`:
   - **If set:** starts the `cloudflared` tunnel and prints your `PUBLIC_BASE_URL` (a real `https://` link) plus a QR code.
   - **If not set:** detects your machine's LAN IP and prints `http://<lan-ip>` plus a QR code, with a warning that this is HTTP-only.

Your phone must be on the same Wi-Fi network as the machine running the script when using the HTTP fallback path.

### Installing on the phone

**iPhone (must be Safari — Chrome/Firefox on iOS can't install PWAs):**
1. Open the link (or scan the QR code with the Camera app).
2. Tap the Share icon (square with an up arrow) in the bottom toolbar.
3. Tap **Add to Home Screen**, then **Add**.

**Android (Chrome):**
1. Open the link (or scan the QR code).
2. Tap the **⋮** menu (top right).
3. Tap **Add to Home Screen** or **Install app**, then confirm.

The app icon now appears on the home screen and launches in standalone mode (no browser address bar).

---

## 3. Full setup: HTTPS via Cloudflare Tunnel

To exercise every feature — voice recording included — you need a real HTTPS URL. The project is pre-wired for [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/), which is free and doesn't require port forwarding or a static IP.

See **[Cloudflare Tunnel Setup](./cloudflare-tunnel-setup.md)** for the full walkthrough (creating the tunnel, getting a hostname, configuring `.env`). Once `CLOUDFLARE_TUNNEL_TOKEN` and `PUBLIC_BASE_URL` are set, every future run of `./scripts/install_on_phone.sh` automatically uses HTTPS — no extra flags needed.

---

## 4. Updating the installed app after code changes

PWAs installed to a home screen register a **service worker**, which aggressively caches the app's JS/CSS/assets so it can work offline. This is great for end users, but it means re-running `./scripts/install_on_phone.sh` after a code change doesn't always show up immediately on a phone that already has the app installed — the service worker may keep serving the old bundle.

If you've made a change and the phone still shows old behavior:

1. **Confirm you rebuilt.** The install script's `npm run build` step is what matters — a bare `docker compose restart nginx` alone serves whatever is already in `frontend/dist`.
2. **Remove the installed PWA icon** from the phone's home screen.
3. **Clear site data** for the install URL in the regular mobile browser:
   - **Safari (iOS):** Settings app → Safari → Advanced → Website Data → find the host → swipe to delete (or "Remove All Website Data").
   - **Chrome (Android):** open the site → tap the site info icon (left of the address bar) → Site settings → Clear & reset.
4. **Reload the page in the browser tab** and confirm the fix is visible there first.
5. **Re-install**: Add to Home Screen again.

If you only changed backend code (no frontend changes), you can usually skip steps 2–4 — service workers cache frontend assets, not API responses.

---

## 5. Troubleshooting

### "The browser does not expose a camera" / camera button does nothing
This was a known issue with an earlier implementation that used a hand-rolled `getUserMedia` video overlay for the inventory "Take photo" button. That approach is unreliable in installed (standalone-display) PWAs on iOS — camera permission prompts can silently fail to appear. It's been replaced with a native `<input type="file" capture="environment">`, which delegates to the OS camera app directly and works in both browser tabs and installed PWAs. If you see this exact error message, you are running stale cached code — follow [Updating the installed app](#4-updating-the-installed-app-after-code-changes) above.

### "Voice recording requires a secure HTTPS connection"
Expected behavior over plain HTTP. See [Section 1](#1-why-https-matters-here-read-this-first) — set up the [Cloudflare Tunnel](./cloudflare-tunnel-setup.md).

### "Microphone permission is blocked" / no audio captured
- **iOS Safari:** Settings app → Safari → Settings for [Website] (or Advanced → Website Data) → ensure Microphone is set to Allow for the install host. The in-app "🎙 Microphone Setup" panel (in the voice recorder) also has a "Reconnect & Test" button that re-requests permission and lists available input devices.
- **Android Chrome:** tap the site info icon → Permissions → Microphone → Allow.
- If multiple microphones are available (e.g. phone case with external mic), use the in-app Microphone Setup panel to pick the correct input device — `OverconstrainedError` usually means a previously selected device ID is no longer available; switch to "Use System Default".

### QR code won't scan
The install script renders a PNG QR code (more reliable than terminal ASCII art, which can be distorted by font rendering) and opens it automatically. If `python3 -c "import qrcode"` fails and the package can't be installed, the script falls back to ASCII art in the terminal — if that doesn't scan, just type the printed `http://` or `https://` link directly into the phone's browser instead.

### "Could not detect a LAN IP automatically"
Find your IP manually: **System Settings → Wi-Fi → Details → IP Address** (macOS), then open `http://<that-ip>` on the phone yourself, or set up the Cloudflare Tunnel to avoid this entirely.

### App installed but shows a blank/broken page
Usually means `frontend/dist` was empty or stale when `nginx` last started. Re-run `./scripts/install_on_phone.sh` (it rebuilds and restarts `nginx` every time), or manually run `docker compose restart nginx` after confirming `frontend/dist` has content.
