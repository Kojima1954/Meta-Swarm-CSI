#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  N.O.M.A.D. Swarm Intelligence — Launch & Post-Setup
# ═══════════════════════════════════════════════════════════════

start_swarm() {
    log_info "Starting N.O.M.A.D. Swarm Intelligence stack..."

    cd "$PROJECT_ROOT"

    # ── Generate GPU override if needed ───────────────────────
    if [[ "${HAS_NVIDIA_GPU:-false}" == "true" ]]; then
        generate_gpu_override
    fi

    # ── Determine compose profile ─────────────────────────────
    local profile_args=()
    if [[ "${OLLAMA_MANAGED_BY_NOMAD:-false}" == "false" ]] || [[ "${QDRANT_MANAGED_BY_NOMAD:-false}" == "false" ]]; then
        profile_args=(--profile self-managed)
        log_info "Using self-managed profile for AI services."
    else
        log_info "Using NOMAD-managed AI services."
    fi

    # ── Build the orchestrator image ──────────────────────────
    log_info "Building swarm-orchestrator image..."
    docker compose build swarm-orchestrator 2>&1 | tail -5

    # ── Start all services ────────────────────────────────────
    log_info "Starting services..."
    docker compose "${profile_args[@]}" up -d

    # ── Wait for Conduit ──────────────────────────────────────
    log_info "Waiting for Conduit (Matrix homeserver)..."
    if wait_for_http "http://localhost:6167/_matrix/client/versions" 60; then
        log_success "Conduit is ready."
    else
        log_warn "Conduit did not respond in time. It may still be starting."
    fi

    # ── Wait for GoToSocial ───────────────────────────────────
    log_info "Waiting for GoToSocial..."
    if wait_for_http "http://localhost:8081/api/v1/instance" 60; then
        log_success "GoToSocial is ready."
    else
        log_warn "GoToSocial did not respond in time. It may still be starting."
    fi

    # ── Create Matrix admin user ──────────────────────────────
    create_matrix_admin

    # ── Create Matrix deliberation room ───────────────────────
    create_deliberation_room

    # ── Register GoToSocial account ───────────────────────────
    register_gotosocial_account

    # ── Provision AI models ───────────────────────────────────
    if [[ "${OLLAMA_MANAGED_BY_NOMAD:-false}" == "false" ]]; then
        # Self-managed Ollama — wait for our container
        provision_models
    else
        # NOMAD-managed Ollama — check if models are available
        log_info "Checking NOMAD-managed Ollama for required models..."
        provision_models
    fi

    # ── Print service status ──────────────────────────────────
    echo ""
    log_info "Service status:"
    docker compose "${profile_args[@]}" ps
}

generate_gpu_override() {
    log_info "NVIDIA GPU detected. Generating docker-compose.override.yml..."
    cat > "${PROJECT_ROOT}/docker-compose.override.yml" <<'EOF'
services:
  ollama:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
EOF
    log_info "GPU passthrough configured for Ollama."
}

create_matrix_admin() {
    local admin_password="${MATRIX_ADMIN_PASSWORD:-}"
    if [[ -z "$admin_password" ]]; then
        log_warn "No Matrix admin password set. Skipping admin user creation."
        return 0
    fi

    log_info "Creating Matrix admin user..."

    # Register admin user via Conduit's admin API
    local register_url="http://localhost:6167/_matrix/client/v3/register"
    local response
    response=$(curl -fsSL -X POST "$register_url" \
        -H "Content-Type: application/json" \
        -d "{
            \"username\": \"admin\",
            \"password\": \"${admin_password}\",
            \"auth\": {\"type\": \"m.login.dummy\"}
        }" 2>/dev/null) || true

    if echo "$response" | grep -q "user_id"; then
        log_success "Matrix admin user created: @admin:${DOMAIN}"
    elif echo "$response" | grep -q "M_USER_IN_USE"; then
        log_info "Matrix admin user already exists."
    else
        log_warn "Could not create Matrix admin user. You may need to create it manually."
    fi
}

create_deliberation_room() {
    log_info "Creating deliberation room..."

    local admin_password="${MATRIX_ADMIN_PASSWORD:-}"
    if [[ -z "$admin_password" ]]; then
        log_warn "No admin password. Skipping room creation."
        return 0
    fi

    # Login to get access token
    local login_response
    login_response=$(curl -fsSL -X POST "http://localhost:6167/_matrix/client/v3/login" \
        -H "Content-Type: application/json" \
        -d "{
            \"type\": \"m.login.password\",
            \"user\": \"admin\",
            \"password\": \"${admin_password}\"
        }" 2>/dev/null) || true

    local access_token
    access_token=$(echo "$login_response" | grep -o '"access_token":"[^"]*"' | sed 's/"access_token":"//;s/"//')

    if [[ -z "$access_token" ]]; then
        log_warn "Could not authenticate. Skipping room creation."
        return 0
    fi

    # Create the deliberation room
    local room_response
    room_response=$(curl -fsSL -X POST "http://localhost:6167/_matrix/client/v3/createRoom" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${access_token}" \
        -d "{
            \"room_alias_name\": \"swarm-deliberation\",
            \"name\": \"Swarm Deliberation\",
            \"topic\": \"Conversational Swarm Intelligence — Main deliberation room\",
            \"visibility\": \"private\",
            \"preset\": \"private_chat\"
        }" 2>/dev/null) || true

    if echo "$room_response" | grep -q "room_id"; then
        log_success "Deliberation room created: #swarm-deliberation:${DOMAIN}"
    elif echo "$room_response" | grep -q "M_ROOM_IN_USE"; then
        log_info "Deliberation room already exists."
    else
        log_warn "Could not create deliberation room. You may need to create it manually."
    fi
}

register_gotosocial_account() {
    local admin_email="${GOTOSOCIAL_ADMIN_EMAIL:-}"
    local node_id="${NODE_ID:-}"

    if [[ -z "$admin_email" || -z "$node_id" ]]; then
        log_warn "Missing admin email or node ID. Skipping GoToSocial account creation."
        return 0
    fi

    log_info "Registering GoToSocial account for node: ${node_id}..."

    # Use GoToSocial admin CLI via docker exec
    local gts_container
    gts_container=$(docker ps --format '{{.Names}}' | grep -i gotosocial | head -1)

    if [[ -z "$gts_container" ]]; then
        log_warn "GoToSocial container not found. Skipping account creation."
        return 0
    fi

    docker exec "$gts_container" \
        /gotosocial/gotosocial admin account create \
        --username "$node_id" \
        --email "$admin_email" \
        --password "$(generate_password 32)" 2>/dev/null || true

    log_info "GoToSocial account registration attempted for: ${node_id}"
}
