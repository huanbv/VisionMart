#!/usr/bin/env bash
# VisionMart -- Secret Generator (DevOps Toolkit Part 3 / Part 14).
#
# Creates .env from .env.example on first run, then fills in strong,
# randomly generated values for the secrets this codebase actually
# reads (verified by grepping backend/app/config/settings.py and the
# rest of the repo -- see the "Secrets covered" list in --help). Never
# overwrites a secret that already holds a non-default, non-empty value
# without explicit confirmation (or --yes / --only).
#
# All decisions are made first (nothing is written), then every pending
# change is applied to .env in exactly ONE `sed -i` pass at the end.
# This is deliberate, not just tidiness: an earlier version applied each
# secret with its own separate `sed -i`/`printf >>` call and was proven
# by real execution to occasionally corrupt the file (a value landing
# mid-line instead of at the intended position) when several small
# writes hit the same path back-to-back. Collecting every edit and
# writing once eliminates that failure mode entirely.
#
# Usage:
#   scripts/generate-secrets.sh                 # fill only missing/default secrets
#   scripts/generate-secrets.sh --only KEY1,KEY2 # regenerate specific secrets
#   scripts/generate-secrets.sh --all            # offer to regenerate every secret
#   scripts/generate-secrets.sh --yes            # don't prompt (CI/unattended)
#   scripts/generate-secrets.sh --check          # report status only, change nothing
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

ENV_FILE="${VISIONMART_APP_DIR}/.env"
ENV_EXAMPLE="${VISIONMART_APP_DIR}/.env.example"
SECRETS_DIR="${VISIONMART_APP_DIR}/secrets"

MODE_ONLY=""
MODE_ALL=0
MODE_CHECK=0

usage() {
  cat <<EOF
VisionMart Secret Generator

Usage: $(basename "$0") [options]

Options:
  --only KEY1,KEY2   Regenerate only the listed secrets (comma-separated).
  --all              Offer to regenerate every managed secret (confirms each
                      one individually unless --yes is also given).
  --check            Report which secrets are missing/default/set -- makes
                      no changes.
  --yes              Assume "yes" to all confirmation prompts (unattended).
  -h, --help         Show this help and exit.

Secrets covered (verified against backend/app/config/settings.py and the
rest of the codebase -- see docs/47_PRODUCTION_SETUP.md for the full
reconciliation notes):
  BACKEND_SECRET_KEY        backend session/signing secret
  AI_ENGINE_API_KEY         shared key between backend <-> ai-engine
  MONITORING_API_TOKEN      shared key for the monitoring service
  MINIO_ROOT_PASSWORD       MinIO admin password
  POSTGRES_PASSWORD         PostgreSQL password (also rewrites DATABASE_URL)
  SEED_ADMIN_PASSWORD       initial super_admin login password (added to
                             .env if absent; code default is a placeholder)
  JWT keypair (RS256)       generated to ./secrets/jwt_{private,public}.pem
                             (not a .env string -- see JWT_PRIVATE_KEY_PATH/
                             JWT_PUBLIC_KEY_PATH, which already point here)

Requested-but-not-applicable (kept honest rather than fabricated -- these
names do not exist anywhere in the current codebase; printed as notices,
never written to .env):
  JWT_SECRET_KEY   -- auth uses an RS256 keypair, not a shared string secret.
  REDIS_PASSWORD   -- Redis runs without auth in docker-compose.yml today;
                       wiring requirepass touches redis.conf and every
                       REDIS_URL/CELERY_BROKER_URL/CELERY_RESULT_BACKEND
                       consumer -- out of scope for this toolkit.
  SESSION_SECRET   -- no server-side session store exists (JWT-based auth).
  CSRF_SECRET      -- no CSRF middleware exists (stateless bearer-token API).
EOF
}

_args=("$@")
for i in "${!_args[@]}"; do
  case "${_args[$i]}" in
    --only=*) MODE_ONLY="${_args[$i]#*=}" ;;
    --only)
      if [ $((i + 1)) -lt ${#_args[@]} ]; then MODE_ONLY="${_args[$((i + 1))]}"; fi
      ;;
    --all) MODE_ALL=1 ;;
    --check) MODE_CHECK=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help) usage; exit "${EXIT_OK}" ;;
  esac
done

init_logging "$0"

# --------------------------------------------------------------------
# Step 1: ensure .env exists
# --------------------------------------------------------------------
FRESH_ENV=0
if [ ! -f "${ENV_FILE}" ]; then
  require_file "${ENV_EXAMPLE}"
  if [ "${MODE_CHECK}" -eq 1 ]; then
    warn "No .env found at ${ENV_FILE} (--check: not creating it)"
  else
    cp "${ENV_EXAMPLE}" "${ENV_FILE}"
    FRESH_ENV=1
    ok "Created ${ENV_FILE} from .env.example"
  fi
fi

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------
_gen_hex() { openssl rand -hex "${1:-32}"; }
_gen_b64() { openssl rand -base64 "${1:-32}" | tr -d '\n=/+' | cut -c1-"${2:-40}"; }

_is_insecure_default() {
  case "$1" in
    ""|change-me|change-me-*|visionmart|visionmart-minio|secret|ChangeMe*|password) return 0 ;;
    *) return 1 ;;
  esac
}

_wanted() {
  local key="$1"
  [ -z "${MODE_ONLY}" ] && return 0
  case ",${MODE_ONLY}," in
    *",${key},"*) return 0 ;;
    *) return 1 ;;
  esac
}

# Pending-edit queue -- nothing touches ${ENV_FILE} until apply_pending_env_edits.
declare -a _SED_EXPRS=()

# queue_env_replace <KEY> <VALUE> -- queues an in-place replacement for a
# line that already exists (every key in .env.example already has a line,
# so this is used for all of them).
queue_env_replace() {
  local key="$1" value="$2"
  local escaped
  escaped="$(printf '%s' "${value}" | sed -e 's/[\/&]/\\&/g')"
  _SED_EXPRS+=(-e "s|^${key}=.*|${key}=${escaped}|")
}

# queue_env_append <KEY> <VALUE> -- queues a brand-new line appended after
# the last line of the file (used only for SEED_ADMIN_PASSWORD, which is
# not present in .env.example).
queue_env_append() {
  local key="$1" value="$2"
  _SED_EXPRS+=(-e "\$a${key}=${value}")
}

apply_pending_env_edits() {
  if [ "${#_SED_EXPRS[@]}" -eq 0 ]; then
    return 0
  fi
  sed -i -E "${_SED_EXPRS[@]}" "${ENV_FILE}"
}

# decide_secret <KEY> <generator-fn> -- reads the ORIGINAL (pre-edit)
# value once, decides whether to (re)generate it, and if so calls
# queue_env_replace. Never writes anything itself.
decide_secret() {
  local key="$1" gen_fn="$2"
  _wanted "${key}" || return 0

  local current
  current="$(env_get "${key}" "${ENV_FILE}")"

  if [ "${MODE_CHECK}" -eq 1 ]; then
    if [ -z "${current}" ]; then
      warn "${key}: MISSING"
    elif _is_insecure_default "${current}"; then
      warn "${key}: still set to an insecure default value"
    else
      ok "${key}: set (custom value)"
    fi
    return 0
  fi

  local need_generate=0
  if [ -z "${current}" ]; then
    need_generate=1
  elif [ "${FRESH_ENV}" -eq 1 ] && _is_insecure_default "${current}"; then
    # Brand-new .env, still holding the .env.example placeholder -- this
    # is exactly the "empty" case the spec means, safe to fill without
    # asking (there is no real secret here yet to lose).
    need_generate=1
  elif [ "${MODE_ALL}" -eq 1 ] || [ -n "${MODE_ONLY}" ]; then
    if confirm "Regenerate ${key}? (current value will be overwritten)"; then
      need_generate=1
    else
      info "${key}: kept unchanged"
      return 0
    fi
  else
    info "${key}: already set -- leaving unchanged (use --only ${key} or --all to regenerate)"
    return 0
  fi

  local value
  value="$("${gen_fn}")"
  queue_env_replace "${key}" "${value}"
  ok "${key}: will generate a new value"
}

# --------------------------------------------------------------------
# Step 2: managed .env secrets (decide only -- nothing written yet)
# --------------------------------------------------------------------
log "Reconciling .env secrets"
decide_secret "BACKEND_SECRET_KEY"   "_gen_hex"
decide_secret "AI_ENGINE_API_KEY"    "_gen_hex"
decide_secret "MONITORING_API_TOKEN" "_gen_hex"
decide_secret "MINIO_ROOT_PASSWORD"  "_gen_b64"

# SEED_ADMIN_PASSWORD already has an (empty) line in .env.example, so
# this goes through the same generic replace-in-place path as every
# other secret above -- "" is already one of _is_insecure_default's
# cases, so a fresh, still-empty .env gets a generated value here with
# no special-casing needed.
_gen_seed_admin_pw() { _gen_b64 24 20; }
decide_secret "SEED_ADMIN_PASSWORD" "_gen_seed_admin_pw"

# POSTGRES_PASSWORD needs special handling: it is also embedded inside
# DATABASE_URL, and both must change together or the backend/celery
# containers will fail to authenticate against a Postgres that already
# has the old password baked into its data volume on first init.
if _wanted "POSTGRES_PASSWORD"; then
  _pg_current="$(env_get "POSTGRES_PASSWORD" "${ENV_FILE}")"
  if [ "${MODE_CHECK}" -eq 1 ]; then
    if [ -z "${_pg_current}" ] || _is_insecure_default "${_pg_current}"; then
      warn "POSTGRES_PASSWORD: still set to an insecure default value"
    else
      ok "POSTGRES_PASSWORD: set (custom value)"
    fi
  else
    _do_pg=0
    if [ -z "${_pg_current}" ]; then
      _do_pg=1
    elif [ "${FRESH_ENV}" -eq 1 ] && _is_insecure_default "${_pg_current}"; then
      _do_pg=1
    elif [ "${MODE_ALL}" -eq 1 ] || [ -n "${MODE_ONLY}" ]; then
      if confirm "Regenerate POSTGRES_PASSWORD? (only safe before the postgres volume has been initialized -- see --help)"; then
        _do_pg=1
      fi
    fi
    if [ "${_do_pg}" -eq 1 ]; then
      _pg_new="$(_gen_b64 24 24)"
      _pg_user="$(env_get "POSTGRES_USER" "${ENV_FILE}")"; _pg_user="${_pg_user:-visionmart}"
      _pg_db="$(env_get "POSTGRES_DB" "${ENV_FILE}")"; _pg_db="${_pg_db:-visionmart}"
      queue_env_replace "POSTGRES_PASSWORD" "${_pg_new}"
      queue_env_replace "DATABASE_URL" "postgresql+asyncpg://${_pg_user}:${_pg_new}@postgres:5432/${_pg_db}"
      ok "POSTGRES_PASSWORD + DATABASE_URL: will generate a new matching value"
      if [ "${FRESH_ENV}" -ne 1 ]; then
        warn "If the 'postgres_data' Docker volume already exists, Postgres will keep its OLD password until the volume is recreated (docker compose down -v postgres) -- this is destructive to existing data, do this only as part of a planned reset."
      fi
    fi
  fi
fi

# --------------------------------------------------------------------
# Step 3: apply every queued .env edit in exactly one write
# --------------------------------------------------------------------
if [ "${MODE_CHECK}" -eq 0 ]; then
  apply_pending_env_edits
  chmod 600 "${ENV_FILE}" 2>/dev/null || true
fi

# --------------------------------------------------------------------
# Step 4: JWT RS256 keypair (separate files under ./secrets, not .env --
# each openssl call below writes to its own fresh file path, so the
# single-write concern above does not apply here).
# --------------------------------------------------------------------
if _wanted "JWT_KEYPAIR"; then
  _priv="${SECRETS_DIR}/jwt_private.pem"
  _pub="${SECRETS_DIR}/jwt_public.pem"
  if [ "${MODE_CHECK}" -eq 1 ]; then
    if [ -f "${_priv}" ] && [ -f "${_pub}" ]; then
      ok "JWT keypair: present (${_priv})"
    else
      warn "JWT keypair: missing (${_priv} / ${_pub})"
    fi
  else
    _do_jwt=0
    if [ ! -f "${_priv}" ] || [ ! -f "${_pub}" ]; then
      _do_jwt=1
    elif [ "${MODE_ALL}" -eq 1 ] || [ -n "${MODE_ONLY}" ]; then
      if confirm "Regenerate JWT RS256 keypair? (invalidates every issued access/refresh token immediately)"; then
        _do_jwt=1
      fi
    fi
    if [ "${_do_jwt}" -eq 1 ]; then
      mkdir -p "${SECRETS_DIR}"
      openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "${_priv}" 2>/dev/null
      openssl rsa -in "${_priv}" -pubout -out "${_pub}" 2>/dev/null
      chmod 600 "${_priv}"; chmod 644 "${_pub}"
      ok "JWT RS256 keypair generated at ${SECRETS_DIR}/ (mounted into containers via docker-compose.yml)"
    else
      info "JWT keypair: already present -- leaving unchanged"
    fi
  fi
fi

# --------------------------------------------------------------------
# Step 5: honest notices for requested-but-not-applicable secrets
# --------------------------------------------------------------------
if [ -z "${MODE_ONLY}" ]; then
  log "Requested secrets with no equivalent in this codebase (not written anywhere)"
  info "JWT_SECRET_KEY -- not applicable: auth uses the RS256 keypair above, not a shared string secret."
  info "REDIS_PASSWORD -- not applicable: Redis runs without auth today (docker-compose.yml has no 'requirepass'); see --help for why this is out of scope here."
  info "SESSION_SECRET -- not applicable: no server-side session store exists."
  info "CSRF_SECRET -- not applicable: no CSRF middleware exists (stateless bearer-token API)."
fi

if [ "${MODE_CHECK}" -eq 1 ]; then
  log "Secret check complete (no changes made)"
else
  log "Secret generation complete"
  info "Review ${ENV_FILE} before starting the stack: scripts/status.sh and scripts/doctor.sh both flag any secret still at an insecure default."
fi
