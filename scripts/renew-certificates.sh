#!/usr/bin/env bash
# VisionMart -- Certificate Helper (DevOps Toolkit Part 15).
#
# Checks Let's Encrypt certificate expiration and assists with renewal
# via the host's own certbot (matches the standalone-Certbot-on-host
# design already documented in docs/DEPLOY_VPS.md §6 -- TLS is
# terminated outside any container). This script never modifies nginx
# configuration itself -- it only reports whether nginx's docker-compose
# service currently has the certificate path mounted at all, and points
# to the manual wiring steps in docs/DEPLOY_VPS.md if not, matching the
# "does not auto-modify nginx" requirement exactly.
#
# Usage:
#   scripts/renew-certificates.sh [--domain DOMAIN] [--check-only] [--yes]
#
# With no --domain, derives it from PUBLIC_APP_BASE_URL in .env.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

DOMAIN=""
CHECK_ONLY=0

_args=("$@")
i=0
while [ "$i" -lt "${#_args[@]}" ]; do
  arg="${_args[$i]}"
  case "$arg" in
    --domain) i=$((i + 1)); DOMAIN="${_args[$i]:-}" ;;
    --check-only) CHECK_ONLY=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help)
      sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
      exit "${EXIT_OK}"
      ;;
  esac
  i=$((i + 1))
done

init_logging "$0"

if [ -z "${DOMAIN}" ]; then
  base_url="$(env_get PUBLIC_APP_BASE_URL)"
  DOMAIN="$(printf '%s' "${base_url}" | sed -E 's#^https?://##; s#/.*##')"
fi

if [ -z "${DOMAIN}" ]; then
  die "Could not determine the domain -- pass --domain example.com, or set PUBLIC_APP_BASE_URL in .env." "${EXIT_VALIDATION_FAILED}"
fi
info "Domain: ${DOMAIN}"

CERT_PATH="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"

if [ ! -f "${CERT_PATH}" ]; then
  warn "No certificate found at ${CERT_PATH}."
  if [ "${CHECK_ONLY}" -eq 1 ]; then
    exit "${EXIT_GENERAL_ERROR}"
  fi
  if ! command -v certbot >/dev/null 2>&1; then
    die "certbot is not installed. Install it first: apt-get install -y certbot (requires root)." "${EXIT_MISSING_PREREQ}"
  fi
  if [ "$(id -u)" -ne 0 ]; then
    die "Obtaining a new certificate requires root (certbot binds port 80 directly)." "${EXIT_MISSING_PREREQ}"
  fi
  warn "No certificate exists yet -- obtaining one requires briefly stopping nginx (port 80 must be free for the HTTP-01 challenge)."
  if ! confirm "Stop nginx and run 'certbot certonly --standalone -d ${DOMAIN}' now?"; then
    die "Cancelled." "${EXIT_USER_ABORT}"
  fi
  dc stop nginx || true
  certbot certonly --standalone -d "${DOMAIN}" --agree-tos --non-interactive -m "admin@${DOMAIN}" --no-eff-email \
    || { dc up -d nginx || true; die "certbot failed to obtain a certificate -- nginx restarted, no changes made." "${EXIT_GENERAL_ERROR}"; }
  dc up -d nginx || true
  ok "Certificate obtained for ${DOMAIN}"
else
  DAYS_LEFT="$(( ($(date -d "$(openssl x509 -enddate -noout -in "${CERT_PATH}" | cut -d= -f2)" +%s) - $(date +%s)) / 86400 ))"
  info "Current certificate expires in ${DAYS_LEFT} day(s)"

  if [ "${DAYS_LEFT}" -gt 30 ]; then
    ok "Certificate is not due for renewal yet (>30 days remaining)."
  else
    warn "Certificate expires within 30 days."
  fi

  if [ "${CHECK_ONLY}" -eq 1 ]; then
    exit "${EXIT_OK}"
  fi

  if ! command -v certbot >/dev/null 2>&1; then
    die "certbot is not installed -- cannot renew automatically. Install it: apt-get install -y certbot." "${EXIT_MISSING_PREREQ}"
  fi
  if [ "$(id -u)" -ne 0 ]; then
    die "Renewing requires root." "${EXIT_MISSING_PREREQ}"
  fi

  log "Running certbot renew"
  certbot renew --quiet
  ok "certbot renew completed (no-op if not yet due -- certbot only renews within its own ~30-day window)"

  NEW_DAYS_LEFT="$(( ($(date -d "$(openssl x509 -enddate -noout -in "${CERT_PATH}" | cut -d= -f2)" +%s) - $(date +%s)) / 86400 ))"
  info "Certificate now expires in ${NEW_DAYS_LEFT} day(s)"
fi

log "nginx wiring check"
if dc exec -T nginx sh -c 'test -d /etc/letsencrypt' >/dev/null 2>&1; then
  ok "nginx container already has /etc/letsencrypt mounted -- reloading"
  dc exec -T nginx nginx -s reload || warn "Reload failed -- check nginx logs."
else
  warn "nginx's docker-compose service does not currently mount /etc/letsencrypt or terminate TLS (see docker-compose.yml)."
  info "This script does not modify nginx config automatically. To wire it up, follow docs/DEPLOY_VPS.md §9:"
  info "  - mount /etc/letsencrypt:/etc/letsencrypt:ro into the nginx service"
  info "  - add a 443 server block referencing ${CERT_PATH%/fullchain.pem}/fullchain.pem and privkey.pem"
  info "  - re-run docker compose up -d nginx after editing docker-compose.yml"
fi
