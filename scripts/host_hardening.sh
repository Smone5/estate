#!/bin/bash
# =============================================================================
# The Estate Steward — Host Hardening Checklist (T75)
# Per Backend Spec §12.1 and Phase 7 plan.
#
# Run this script on the Raspberry Pi 5 host (not inside Docker).
# Each section can be run independently or all at once.
#
# Usage: sudo bash scripts/host_hardening.sh [--dry-run]
#    --dry-run: print what would be done without making changes
# =============================================================================

set -euo pipefail

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
  echo "=== DRY RUN MODE — no changes will be made ==="
fi

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }
info() { echo -e "[INFO] $1"; }

if [[ $EUID -ne 0 ]] && [[ "$DRY_RUN" != "true" ]]; then
  fail "This script must be run as root. Use: sudo bash scripts/host_hardening.sh"
  exit 1
fi

# ---------------------------------------------------------------------------
# Section 1: SSH Hardening — disable password login, enforce key-based auth
# ---------------------------------------------------------------------------
echo ""
echo "=== Section 1: SSH Hardening ==="

SSHD_CONFIG="/etc/ssh/sshd_config"
BACKUP_SSHD="/etc/ssh/sshd_config.estate_bak_$(date +%Y%m%d_%H%M%S)"

harden_ssh() {
  info "Backing up sshd_config to $BACKUP_SSHD"
  if [[ "$DRY_RUN" != "true" ]]; then
    cp "$SSHD_CONFIG" "$BACKUP_SSHD"
  fi

  # 1a. Disable password authentication
  if grep -q "^PasswordAuthentication yes" "$SSHD_CONFIG" || grep -q "^#PasswordAuthentication" "$SSHD_CONFIG"; then
    info "Disabling SSH password authentication..."
    if [[ "$DRY_RUN" != "true" ]]; then
      sed -i 's/^#PasswordAuthentication.*/PasswordAuthentication no/' "$SSHD_CONFIG"
      sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' "$SSHD_CONFIG"
    fi
  fi

  # 1b. Disable challenge-response authentication (S/Key, keyboard-interactive)
  if grep -q "^#ChallengeResponseAuthentication\|^ChallengeResponseAuthentication yes" "$SSHD_CONFIG"; then
    info "Disabling challenge-response authentication..."
    if [[ "$DRY_RUN" != "true" ]]; then
      sed -i 's/^#ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' "$SSHD_CONFIG"
      sed -i 's/^ChallengeResponseAuthentication yes/ChallengeResponseAuthentication no/' "$SSHD_CONFIG"
    fi
  fi

  # 1c. Disable root SSH login
  if grep -q "^#PermitRootLogin\|^PermitRootLogin yes" "$SSHD_CONFIG"; then
    info "Disabling root SSH login..."
    if [[ "$DRY_RUN" != "true" ]]; then
      sed -i 's/^#PermitRootLogin.*/PermitRootLogin no/' "$SSHD_CONFIG"
      sed -i 's/^PermitRootLogin yes/PermitRootLogin no/' "$SSHD_CONFIG"
    fi
  fi

  # 1d. Restrict MaxAuthTries
  if grep -q "^#MaxAuthTries\|^MaxAuthTries" "$SSHD_CONFIG"; then
    info "Setting MaxAuthTries to 3..."
    if [[ "$DRY_RUN" != "true" ]]; then
      sed -i 's/^#MaxAuthTries.*/MaxAuthTries 3/' "$SSHD_CONFIG"
      sed -i 's/^MaxAuthTries [0-9].*/MaxAuthTries 3/' "$SSHD_CONFIG"
    fi
  fi

  # 1e. Restart SSH daemon
  if [[ "$DRY_RUN" != "true" ]]; then
    info "Restarting SSH daemon..."
    systemctl restart sshd || systemctl restart ssh
  fi

  if [[ "$DRY_RUN" != "true" ]]; then
    # Verify
    if grep -q "^PasswordAuthentication no" "$SSHD_CONFIG"; then
      pass "SSH password authentication: DISABLED"
    else
      warn "Could not verify PasswordAuthentication setting — check manually in $SSHD_CONFIG"
    fi
  fi
}

# ---------------------------------------------------------------------------
# Section 2: Enable automatic security updates (unattended-upgrades)
# ---------------------------------------------------------------------------
echo ""
echo "=== Section 2: Automatic Security Updates ==="

enable_unattended_upgrades() {
  if [[ "$DRY_RUN" != "true" ]]; then
    # Check if unattended-upgrades is installed
    if ! dpkg -l | grep -q unattended-upgrades; then
      info "Installing unattended-upgrades..."
      apt-get update -qq
      apt-get install -y unattended-upgrades
    else
      info "unattended-upgrades is already installed."
    fi

    # Enable automatic security updates
    cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
APT::Periodic::Unattended-Upgrade "1";
EOF

    # Enable only security repository for unattended upgrades
    cat > /etc/apt/apt.conf.d/50unattended-upgrades <<'EOF'
Unattended-Upgrade::Allowed-Origins {
  "${distro_id}:${distro_codename}-security";
  "${distro_id}ESMApps:${distro_codename}-apps-security";
  "${distro_id}ESM:${distro_codename}-infra-security";
};
Unattended-Upgrade::Automatic-Reboot "false";
EOF

    systemctl restart unattended-upgrades 2>/dev/null || true

    if systemctl is-active --quiet unattended-upgrades 2>/dev/null; then
      pass "unattended-upgrades: ENABLED and running"
    else
      pass "unattended-upgrades: CONFIGURED (timer-based, not a persistent service)"
    fi
  fi
}

# ---------------------------------------------------------------------------
# Section 3: UFW Firewall — block all except 80/443
# ---------------------------------------------------------------------------
echo ""
echo "=== Section 3: Firewall (UFW) ==="

configure_firewall() {
  if [[ "$DRY_RUN" != "true" ]]; then
    if ! command -v ufw &>/dev/null; then
      info "Installing ufw..."
      apt-get update -qq
      apt-get install -y ufw
    fi

    # Default deny incoming, allow outgoing
    ufw default deny incoming
    ufw default allow outgoing

    # Allow only HTTP (80) and HTTPS (443)
    ufw allow 80/tcp
    ufw allow 443/tcp

    # Deny direct backend port access from external networks
    ufw deny 8000/tcp
    ufw deny 5432/tcp
    ufw deny 3000/tcp

    # Enable firewall
    ufw --force enable

    if ufw status | grep -q "Status: active"; then
      pass "UFW firewall: ACTIVE"
    else
      fail "UFW firewall: FAILED to activate"
    fi

    echo ""
    ufw status verbose
  fi
}

# ---------------------------------------------------------------------------
# Section 4: Default user credential change (Raspberry Pi)
# ---------------------------------------------------------------------------
echo ""
echo "=== Section 4: Default User Credentials ==="

warn_default_creds() {
  warn "REMINDER: Change the default 'pi' user password if not already done:"
  info "  passwd pi"
  info ""
  warn "REMINDER: Verify no other default accounts have weak passwords:"
  info "  cat /etc/passwd | grep -E '/bin/bash|/bin/sh'"
  info ""
  warn "If SSH keys are not yet configured, generate a key pair now:"
  info "  ssh-keygen -t ed25519 -C 'estate-steward-admin'"
  info "  ssh-copy-id pi@raspberrypi.local"
  info ""
  info "After key-based login is verified, you can further lock down SSH:"
  info "  sudo sed -i 's/^#PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config"
  info "  sudo systemctl restart sshd"
}

# ---------------------------------------------------------------------------
# Section 5: Verification
# ---------------------------------------------------------------------------
echo ""
echo "=== Section 5: Verification ==="

verify() {
  echo "--- SSH Password Auth ---"
  if grep -q "^PasswordAuthentication no" /etc/ssh/sshd_config 2>/dev/null; then
    pass "PasswordAuthentication: no"
  else
    warn "PasswordAuthentication: may still be enabled"
  fi

  echo ""
  echo "--- Firewall ---"
  if command -v ufw &>/dev/null && ufw status | grep -q "Status: active"; then
    pass "UFW: active"
  else
    warn "UFW: not active or not installed"
  fi

  echo ""
  echo "--- Open Ports ---"
  if command -v ss &>/dev/null; then
    ss -tlnp | grep LISTEN || true
  elif command -v netstat &>/dev/null; then
    netstat -tlnp | grep LISTEN || true
  fi

  echo ""
  echo "--- Automatic Updates ---"
  if dpkg -l | grep -q unattended-upgrades 2>/dev/null; then
    pass "unattended-upgrades: installed"
  else
    warn "unattended-upgrades: not installed"
  fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
echo "=============================================="
echo "  Estate Steward Host Hardening (T75)"
echo "  $(date)"
echo "=============================================="

if [[ "$DRY_RUN" == "true" ]]; then
  echo ""
  info "DRY RUN — showing what would be done"
  echo ""
fi

harden_ssh
enable_unattended_upgrades
configure_firewall
warn_default_creds
verify

echo ""
echo "=============================================="
echo "  Hardening complete."
echo "  SSH: password login disabled, key-only auth."
echo "  UFW: ports 80/443 open, all others blocked."
echo "  Patching: automatic security updates enabled."
echo "=============================================="
echo ""
warn "TEST: Open a NEW terminal and verify SSH key login works before closing this session!"