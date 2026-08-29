#!/usr/bin/env bash
# VisionMart DevOps & Deployment Toolkit -- shared deployment engine.
#
# Sourced by setup-production.sh AND update-production.sh so the
# pull/build/up/wait-healthy/migrate/seed/doctor sequence exists in
# exactly ONE place (Part 4/5/6 of the DevOps toolkit spec explicitly
# reuse the same steps from two different entry points). Always source
# scripts/lib/common.sh first -- this file assumes log()/ok()/warn()/
# error()/die()/dc()/confirm()/container_health()/EXIT_* already exist.
#
# This file orchestrates existing, already-built components only
# (docker compose, alembic, app.scripts.seed_initial, visionmart doctor)
# -- it contains no business logic of its own.

# --------------------------------------------------------------------
# Part 4: Deployment Engine
# --------------------------------------------------------------------

# deploy_pull_build [services...] -- pulls prebuilt images where available
# and (re)builds the ones that are always built locally (backend,
# ai-engine, frontend, monitoring, backup all have `build:` blocks, so
# `pull` is a no-op for them unless a registry image is also tagged --
# harmless either way, matches `docker compose pull` semantics of
# skipping build-only services with a warning).
deploy_pull_build() {
  log "Pulling images (services with a registry image)"
  dc pull --ignore-pull-failures "$@" || warn "Some services have no pullable image (build-only) -- continuing"

  log "Building images${*:+: $*}"
  dc build "$@"
}

# deploy_up [services...] -- brings the stack up in detached mode.
deploy_up() {
  log "Starting containers${*:+: $*}"
  dc up -d "$@"
}

# List of (container_name, human label) pairs that have a Docker
# HEALTHCHECK defined in docker-compose.yml -- see docker-compose.yml's
# postgres/redis/minio/backend/ai-engine/monitoring services. Containers
# without a healthcheck (celery-worker, celery-beat, frontend, nginx)
# are intentionally not polled here; their readiness is implied by their
# dependencies already being healthy.
_HEALTHCHECKED_CONTAINERS=(
  "visionmart-postgres:PostgreSQL"
  "visionmart-redis:Redis"
  "visionmart-minio:MinIO"
  "visionmart-backend:Backend API"
  "visionmart-ai-engine:AI Engine"
  "visionmart-monitoring:Monitoring"
)

# wait_for_stack_healthy [timeout_seconds] -- polls every healthchecked
# container, printing progress, retrying an unhealthy container once via
# `docker compose restart <service>` before giving up on it. Returns 0
# if every present, healthchecked container reaches "healthy" (or has
# no healthcheck reported yet but the container is at least "running"),
# non-zero if any is still unhealthy/missing when the timeout expires.
wait_for_stack_healthy() {
  local timeout="${1:-180}"
  local waited=0
  local interval=5
  local -A retried=()
  local all_healthy=0

  log "Waiting for containers to become healthy (timeout ${timeout}s)"
  while [ "${waited}" -lt "${timeout}" ]; do
    all_healthy=1
    local line name label status
    for line in "${_HEALTHCHECKED_CONTAINERS[@]}"; do
      name="${line%%:*}"
      label="${line#*:}"
      status="$(container_health "${name}")"
      case "${status}" in
        healthy|none)
          : # none = container has no healthcheck reported yet or is up without one; not a failure by itself
          ;;
        missing)
          all_healthy=0
          ;;
        unhealthy)
          all_healthy=0
          if [ -z "${retried[${name}]:-}" ]; then
            warn "${label} (${name}) is unhealthy -- restarting once"
            local svc="${name#visionmart-}"
            dc restart "${svc}" >/dev/null 2>&1 || true
            retried[${name}]=1
          fi
          ;;
        starting|*)
          all_healthy=0
          ;;
      esac
    done

    if [ "${all_healthy}" -eq 1 ]; then
      ok "All containers healthy"
      return 0
    fi

    printf "${C_GRAY}  ... waiting (%ss/%ss)${C_RESET}\r" "${waited}" "${timeout}"
    sleep "${interval}"
    waited=$((waited + interval))
  done

  echo
  warn "Timed out waiting for all containers to become healthy -- current status:"
  local line name label status
  for line in "${_HEALTHCHECKED_CONTAINERS[@]}"; do
    name="${line%%:*}"
    label="${line#*:}"
    status="$(container_health "${name}")"
    if [ "${status}" = "healthy" ]; then
      ok "${label}: ${status}"
    else
      error "${label}: ${status} -- check: docker compose logs --tail=100 ${name#visionmart-}"
    fi
  done
  return 1
}

# --------------------------------------------------------------------
# Part 5: Database Initialization
# --------------------------------------------------------------------

# run_db_migrations -- applies Alembic migrations. `alembic upgrade
# head` is idempotent and forward-only (see docs/DEPLOY_VPS.md §12) so
# it is always safe to call, whether the database is brand new (creates
# every table from scratch) or already up to date (no-op). This is the
# single migration entry point used by both first-time setup and
# updates -- never generates a new revision and never touches existing
# data beyond what the checked-in migration scripts do.
run_db_migrations() {
  log "Applying database migrations (alembic upgrade head)"
  if dc run --rm backend alembic upgrade head; then
    ok "Migrations applied"
    return 0
  fi
  error "Migration failed -- database left untouched beyond what Alembic itself applied/rolled back"
  return 1
}

# run_seed_initial -- creates the default organization/roles/admin user
# ONLY if SEED_ADMIN_ON_SETUP=1 is set by the caller (setup-production.sh
# opts in; update-production.sh never calls this). Safe to re-run: see
# backend/app/scripts/seed_initial.py's own idempotency guarantee
# (existing rows are reused, nothing is deleted or reset).
run_seed_initial() {
  if [ "${SEED_ADMIN_ON_SETUP:-0}" != "1" ]; then
    info "Skipping seed_initial (SEED_ADMIN_ON_SETUP not set) -- run manually with:"
    info "  docker compose run --rm backend python -m app.scripts.seed_initial"
    return 0
  fi
  log "Seeding initial organization/roles/admin user (idempotent)"
  if dc run --rm backend python -m app.scripts.seed_initial; then
    ok "Seed complete"
    return 0
  fi
  warn "Seed step reported an error -- this never deletes/resets existing data; check logs above"
  return 1
}

# --------------------------------------------------------------------
# Part 6: Health Verification
# --------------------------------------------------------------------

# run_health_verification -- runs the existing `visionmart doctor` check
# engine (visionmart/doctor.py, built in the Final Production Readiness
# phase) inside the monitoring container, which already has every
# dependency (monitoring/requirements.txt) the checks need. Interprets
# the shared PASS/WARNING/FAIL contract:
#   FAIL     -> abort the calling script with EXIT_UNHEALTHY and print
#               the recommendations already produced by doctor.py.
#   WARNING  -> print a notice but let the caller continue.
#   PASS     -> continue silently (doctor's own output already showed it).
# Never re-implements the checks themselves -- this is orchestration only.
run_health_verification() {
  log "Running deployment validation (python -m visionmart doctor)"
  local output status
  output="$(dc exec -T monitoring python -m visionmart doctor 2>&1)"
  status=$?
  echo "${output}"

  if [ "${status}" -eq 0 ]; then
    if echo "${output}" | grep -q "WARNING"; then
      warn "Doctor reported WARNING(s) above -- continuing, but review before relying on this deployment"
    else
      ok "Doctor: all checks PASS"
    fi
    return 0
  fi

  error "Doctor reported one or more FAIL checks above -- aborting"
  error "Fix the FAIL items and re-run this script. See docs/46_DEPLOYMENT_VALIDATION.md for what each check means."
  return "${EXIT_UNHEALTHY}"
}
