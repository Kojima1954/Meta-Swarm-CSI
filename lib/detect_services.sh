#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  N.O.M.A.D. Swarm Intelligence — Detect Running AI Services
# ═══════════════════════════════════════════════════════════════

detect_services() {
    log_info "Detecting existing AI services..."

    # ── Detect Ollama ─────────────────────────────────────────
    OLLAMA_MANAGED_BY_NOMAD=false
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qi "ollama"; then
        OLLAMA_MANAGED_BY_NOMAD=true
        log_info "Ollama container detected (NOMAD-managed)."

        # Attempt to find the Ollama URL from the container
        local ollama_port
        ollama_port=$(docker inspect --format='{{range $p, $conf := .NetworkSettings.Ports}}{{if eq $p "11434/tcp"}}{{(index $conf 0).HostPort}}{{end}}{{end}}' \
            "$(docker ps --format '{{.Names}}' | grep -i ollama | head -1)" 2>/dev/null || echo "11434")
        OLLAMA_URL="http://localhost:${ollama_port:-11434}"
        log_info "Ollama URL: ${OLLAMA_URL}"
    else
        OLLAMA_URL="http://localhost:11434"
        log_info "No Ollama container found. Will use self-managed mode."
    fi
    export OLLAMA_MANAGED_BY_NOMAD OLLAMA_URL

    # ── Detect Qdrant ─────────────────────────────────────────
    QDRANT_MANAGED_BY_NOMAD=false
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qi "qdrant"; then
        QDRANT_MANAGED_BY_NOMAD=true
        log_info "Qdrant container detected (NOMAD-managed)."
    else
        log_info "No Qdrant container found. Will use self-managed mode."
    fi
    export QDRANT_MANAGED_BY_NOMAD

    # ── Detect N.O.M.A.D. Docker network ─────────────────────
    NOMAD_NETWORK=$(docker network ls --format '{{.Name}}' 2>/dev/null | grep "project-nomad" | head -1)
    if [[ -z "$NOMAD_NETWORK" ]]; then
        NOMAD_NETWORK="project-nomad_default"
        log_warn "N.O.M.A.D. Docker network not found. Using default: ${NOMAD_NETWORK}"
    else
        log_info "N.O.M.A.D. Docker network: ${NOMAD_NETWORK}"
    fi
    export NOMAD_NETWORK

    # ── Summary ───────────────────────────────────────────────
    if [[ "$OLLAMA_MANAGED_BY_NOMAD" == "true" && "$QDRANT_MANAGED_BY_NOMAD" == "true" ]]; then
        log_info "Mode: NOMAD-managed (both Ollama and Qdrant detected)."
    elif [[ "$OLLAMA_MANAGED_BY_NOMAD" == "false" && "$QDRANT_MANAGED_BY_NOMAD" == "false" ]]; then
        log_info "Mode: Self-managed (will start Ollama and Qdrant in our compose stack)."
    else
        log_info "Mode: Mixed (some services NOMAD-managed, some self-managed)."
    fi
}
