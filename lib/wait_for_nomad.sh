#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  N.O.M.A.D. Swarm Intelligence — Wait for N.O.M.A.D.
# ═══════════════════════════════════════════════════════════════

wait_for_nomad() {
    log_info "Waiting for N.O.M.A.D. Command Center to become ready..."

    if wait_for_http "http://localhost:8080" 180; then
        log_success "N.O.M.A.D. Command Center is ready."
    else
        log_error "N.O.M.A.D. Command Center did not respond within 180 seconds."
        log_error "Check logs with: docker compose -f /opt/project-nomad/docker-compose.yml logs"
        exit 1
    fi
}
