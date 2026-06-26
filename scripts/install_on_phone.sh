#!/usr/bin/env bash
# Builds the frontend, makes sure the stack is reachable from a phone, then
# prints a tappable link + scannable QR code so installing the PWA on an
# iPhone/Android is "point camera, tap Add to Home Screen" instead of typing
# a URL by hand.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

log() {
  printf '\n\033[1;34m%s\033[0m\n' "$1"
}

warn() {
  printf '\n\033[1;33m%s\033[0m\n' "$1"
}

die() {
  printf '\n\033[1;31m%s\033[0m\n' "$1" >&2
  exit 1
}

env_value() {
  [[ -f "$ENV_FILE" ]] || return 0
  grep -E "^$1=" "$ENV_FILE" | head -n 1 | cut -d '=' -f 2- | sed 's/[[:space:]]*#.*$//' | tr -d '[:space:]' || true
}

print_qr() {
  local url="$1"
  if ! python3 -c "import qrcode" >/dev/null 2>&1; then
    log "Installing the 'qrcode' Python package (one-time setup for QR rendering)"
    pip3 install --quiet --user "qrcode[pil]" || warn "Could not install qrcode — skipping QR code, use the link above instead."
  fi

  # Terminal ASCII QR codes are frequently unscannable by phone cameras — the
  # font's anti-aliasing and non-square character cells distort the module
  # grid. Render a real PNG instead and open it full-size so the camera sees
  # crisp black/white squares, exactly like a printed QR code would look.
  local qr_path="$ROOT_DIR/.qr-install.png"
  if python3 -c "
import qrcode
qr = qrcode.QRCode(border=2, box_size=12)
qr.add_data('$url')
qr.make()
qr.make_image(fill_color='black', back_color='white').save('$qr_path')
" 2>/dev/null; then
    log "Opening the QR code image — point your phone's camera at the screen"
    if command -v open >/dev/null 2>&1; then
      open "$qr_path"
    else
      warn "Could not auto-open the image. Open it manually: $qr_path"
    fi
  else
    warn "QR image rendering unavailable — falling back to ASCII (may not scan reliably). If it doesn't scan, just type the link above into your phone's browser instead."
    python3 -c "
import qrcode
qr = qrcode.QRCode(border=1)
qr.add_data('$url')
qr.make()
qr.print_ascii(invert=True)
" 2>/dev/null || true
  fi
}

lan_ip() {
  # macOS: try common Wi-Fi/Ethernet interface names first, then fall back to
  # scanning every interface for a private IPv4 address (handles machines
  # where Wi-Fi isn't en0/en1, e.g. USB/Thunderbolt adapters).
  if command -v ipconfig >/dev/null 2>&1; then
    local iface ip
    for iface in en0 en1 en2 en3; do
      ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
      [[ -n "$ip" ]] && { echo "$ip"; return 0; }
    done
    ifconfig 2>/dev/null | awk '
      /^[a-z]/ { iface=$1 }
      /inet / && $2 != "127.0.0.1" {
        split($2, a, ".")
        if (a[1] == "192" || a[1] == "10" || (a[1] == "172" && a[2]+0 >= 16 && a[2]+0 <= 31)) {
          print $2
          exit
        }
      }
    '
  else
    hostname -I 2>/dev/null | awk '{print $1}'
  fi
}

main() {
  cd "$ROOT_DIR"

  log "Building the frontend (generates the PWA manifest + service worker)"
  (cd frontend && npm run build)

  log "Starting the Docker stack (app, db, nginx)"
  docker compose up -d app nginx

  # If nginx was already running before frontend/dist had real content (e.g.
  # the very first build, or dist was wiped/rebuilt), its bind mount of
  # frontend/dist can cache a stale/empty view, serving "403 Forbidden"
  # ("directory index... is forbidden") instead of the freshly built app.
  # Restarting forces nginx to remount and pick up the current dist/ files.
  log "Restarting nginx to pick up the freshly built frontend"
  docker compose restart nginx

  local tunnel_token public_url
  tunnel_token="$(env_value CLOUDFLARE_TUNNEL_TOKEN)"
  public_url="$(env_value PUBLIC_BASE_URL)"

  if [[ -n "$tunnel_token" ]]; then
    log "Cloudflare Tunnel token found — starting the tunnel for a public HTTPS URL"
    docker compose --profile tunnel up -d cloudflared

    if [[ -z "$public_url" ]]; then
      die "CLOUDFLARE_TUNNEL_TOKEN is set but PUBLIC_BASE_URL is blank in .env. Set PUBLIC_BASE_URL=https://<your-tunnel-hostname> (the hostname you configured in the Cloudflare Zero Trust dashboard) and re-run this script."
    fi

    log "Phone install link (HTTPS — service worker + offline caching fully work):"
    printf '  \033[1;32m%s\033[0m\n' "$public_url"
    print_qr "$public_url"
  else
    local ip
    ip="$(lan_ip)"
    [[ -n "$ip" ]] || die "Could not detect a LAN IP automatically. Find it manually (System Settings > Wi-Fi > Details) and open http://<that-ip> on your phone, or set up the Cloudflare Tunnel for an HTTPS link (see .env.example)."

    warn "No CLOUDFLARE_TUNNEL_TOKEN set — falling back to your local Wi-Fi IP. Your phone must be on the SAME Wi-Fi network as this computer. This is plain HTTP, so 'Add to Home Screen' creates the icon but the service worker (offline caching) won't activate — fine for trying it out, not for real use. Set up the Cloudflare Tunnel (.env.example) for the real HTTPS install."

    log "Phone install link (same Wi-Fi only):"
    printf '  \033[1;32mhttp://%s\033[0m\n' "$ip"
    print_qr "http://$ip"
  fi

  cat <<'EOF'

How to install once you've opened the link:

  iPhone (must be Safari):
    1. Tap the Share icon (square with an arrow) in the bottom toolbar
    2. Tap "Add to Home Screen"
    3. Tap "Add" — the app icon now appears on your home screen

  Android (Chrome):
    1. Tap the ⋮ menu (top right)
    2. Tap "Add to Home Screen" or "Install app"
    3. Confirm — the app icon now appears on your home screen

EOF
}

main "$@"
