#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  N.O.M.A.D. Swarm Intelligence — Preflight System Checks
# ═══════════════════════════════════════════════════════════════

run_preflight_checks() {
    log_info "Running preflight system checks..."

    local errors=0

    # ── OS check ──────────────────────────────────────────────
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        source /etc/os-release
        log_info "Detected OS: ${PRETTY_NAME:-${NAME} ${VERSION_ID}}"

        local ok=false
        case "${ID:-}" in
            ubuntu)
                if [[ "$(echo "${VERSION_ID:-0}" | cut -d. -f1)" -ge 22 ]]; then
                    ok=true
                fi
                ;;
            debian)
                if [[ "$(echo "${VERSION_ID:-0}" | cut -d. -f1)" -ge 12 ]]; then
                    ok=true
                fi
                ;;
        esac

        if [[ "$ok" != "true" ]]; then
            log_error "Unsupported OS. Requires Ubuntu >= 22.04 or Debian >= 12."
            errors=$((errors + 1))
        fi
    else
        log_error "Cannot detect OS: /etc/os-release not found."
        errors=$((errors + 1))
    fi

    # ── Architecture check ────────────────────────────────────
    local arch
    arch=$(uname -m)
    log_info "Architecture: ${arch}"
    if [[ "$arch" != "x86_64" && "$arch" != "aarch64" ]]; then
        log_error "Unsupported architecture: ${arch}. Requires x86_64 or aarch64."
        errors=$((errors + 1))
    fi

    # ── RAM check ─────────────────────────────────────────────
    local mem_kb mem_gb
    mem_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
    mem_gb=$((mem_kb / 1024 / 1024))
    log_info "Total RAM: ${mem_gb} GB"

    if [[ $mem_gb -lt 4 ]]; then
        log_error "Insufficient RAM: ${mem_gb} GB. Minimum 4 GB required."
        errors=$((errors + 1))
    elif [[ $mem_gb -lt 8 ]]; then
        log_warn "Low RAM: ${mem_gb} GB. 8 GB+ recommended, 16 GB+ ideal."
    fi

    # ── Disk check ────────────────────────────────────────────
    local free_gb
    free_gb=$(df -BG "$PWD" | awk 'NR==2 {gsub(/G/,"",$4); print $4}')
    log_info "Free disk space: ${free_gb} GB (on partition containing ${PWD})"

    if [[ $free_gb -lt 20 ]]; then
        log_error "Insufficient disk space: ${free_gb} GB. Minimum 20 GB required."
        errors=$((errors + 1))
    elif [[ $free_gb -lt 50 ]]; then
        log_warn "Low disk space: ${free_gb} GB. 50 GB+ recommended."
    fi

    # ── Internet check ────────────────────────────────────────
    if curl -fsS --max-time 10 https://github.com > /dev/null 2>&1; then
        log_info "Internet connectivity: OK"
    else
        log_error "No internet connectivity. The installer needs to download Docker images and models."
        errors=$((errors + 1))
    fi

    # ── Existing N.O.M.A.D. check ────────────────────────────
    NOMAD_ALREADY_INSTALLED=false
    if [[ -f /opt/project-nomad/compose.yml ]]; then
        if docker compose -p project-nomad -f /opt/project-nomad/compose.yml ps --status running 2>/dev/null | grep -q "running"; then
            NOMAD_ALREADY_INSTALLED=true
            log_info "Existing N.O.M.A.D. installation detected and running."
        else
            log_info "N.O.M.A.D. compose file found at /opt/project-nomad but not running."
        fi
    else
        log_info "No existing N.O.M.A.D. installation found."
    fi
    export NOMAD_ALREADY_INSTALLED

    # ── GPU check ─────────────────────────────────────────────
    HAS_NVIDIA_GPU=false
    if detect_nvidia_gpu; then
        HAS_NVIDIA_GPU=true
        log_info "NVIDIA GPU detected."
    else
        log_info "No NVIDIA GPU detected (CPU-only mode)."
    fi
    export HAS_NVIDIA_GPU

    # ── Final result ──────────────────────────────────────────
    if [[ $errors -gt 0 ]]; then
        log_error "Preflight checks failed with ${errors} error(s). Fix the issues above and retry."
        exit 1
    fi

    log_success "All preflight checks passed."
}
