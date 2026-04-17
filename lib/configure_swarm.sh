#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  N.O.M.A.D. Swarm Intelligence — Configuration Wizard
# ═══════════════════════════════════════════════════════════════

configure_swarm() {
    log_info "Configuring N.O.M.A.D. Swarm Intelligence..."

    if [[ "${NONINTERACTIVE:-0}" != "1" ]]; then
        echo ""
        echo -e "${BOLD}Swarm Configuration Wizard${RESET}"
        echo "Press Enter to accept defaults shown in [brackets]."
        echo ""
    fi

    # ── Collect configuration values ──────────────────────────
    DOMAIN=$(prompt_or_env "DOMAIN" "Domain name (e.g., swarm.example.org)" "")
    validate_hostname "$DOMAIN"

    local default_node_id
    default_node_id="node-$(hostname -s | tr '[:upper:]' '[:lower:]' | tr -dc 'a-z0-9-')"
    NODE_ID=$(prompt_or_env "NODE_ID" "Node ID" "$default_node_id")
    validate_node_id "$NODE_ID"

    local default_node_name
    default_node_name=$(echo "$NODE_ID" | sed 's/-/ /g' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) tolower(substr($i,2))}1')
    NODE_NAME=$(prompt_or_env "NODE_NAME" "Node display name" "$default_node_name")

    LLM_MODEL=$(prompt_or_env "LLM_MODEL" "LLM model" "llama3.1:8b")
    EMBEDDING_MODEL=$(prompt_or_env "EMBEDDING_MODEL" "Embedding model" "nomic-embed-text")
    ROUND_INTERVAL=$(prompt_or_env "ROUND_INTERVAL" "Round interval (seconds)" "300")
    ROUND_MODE=$(prompt_or_env "ROUND_MODE" "Round mode (timer/message_count/manual)" "timer")
    MESSAGE_THRESHOLD=$(prompt_or_env "MESSAGE_THRESHOLD" "Message threshold (for message_count mode)" "50")
    MATRIX_ADMIN_PASSWORD=$(prompt_or_env "MATRIX_ADMIN_PASSWORD" "Matrix admin password" "$(generate_password 24)")
    GOTOSOCIAL_ADMIN_EMAIL=$(prompt_or_env "GOTOSOCIAL_ADMIN_EMAIL" "GoToSocial admin email" "")
    WEB_API_TOKEN=$(prompt_or_env "WEB_API_TOKEN" "Web UI API token (for round-trigger control)" "$(generate_password 32)")

    # ── Generate .env file ────────────────────────────────────
    log_info "Generating .env file..."

    local compose_profiles=""
    if [[ "${OLLAMA_MANAGED_BY_NOMAD:-false}" == "false" ]] || [[ "${QDRANT_MANAGED_BY_NOMAD:-false}" == "false" ]]; then
        compose_profiles="self-managed"
    fi

    cat > "${PROJECT_ROOT}/.env" <<EOF
# ═══════════════════════════════════════════════════════════════
#  N.O.M.A.D. Swarm Intelligence — Environment Configuration
#  Generated on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# ═══════════════════════════════════════════════════════════════

# ─── Domain & Identity ───
DOMAIN=${DOMAIN}
NODE_ID=${NODE_ID}
NODE_NAME=${NODE_NAME}

# ─── N.O.M.A.D. Docker Network (auto-detected) ───
NOMAD_NETWORK=${NOMAD_NETWORK:-project-nomad_default}

# ─── Compose Profiles ───
COMPOSE_PROFILES=${compose_profiles}

# ─── Image Versions ───
OLLAMA_IMAGE=ollama/ollama:latest
QDRANT_IMAGE=qdrant/qdrant:latest
CONDUIT_IMAGE=matrixconduit/matrix-conduit:latest
ELEMENT_IMAGE=vectorim/element-web:latest
GOTOSOCIAL_IMAGE=superseriousbusiness/gotosocial:0.21.2
NGINX_IMAGE=nginx:1.27-alpine

# ─── AI Models ───
LLM_MODEL=${LLM_MODEL}
EMBEDDING_MODEL=${EMBEDDING_MODEL}

# ─── Matrix ───
MATRIX_ADMIN_PASSWORD=${MATRIX_ADMIN_PASSWORD}

# ─── GoToSocial ───
GOTOSOCIAL_ADMIN_EMAIL=${GOTOSOCIAL_ADMIN_EMAIL}

# ─── Swarm Rounds ───
ROUND_MODE=${ROUND_MODE}
ROUND_INTERVAL=${ROUND_INTERVAL}
MESSAGE_THRESHOLD=${MESSAGE_THRESHOLD}

# ─── Web UI ───
# Bearer token required for control endpoints (manual round trigger).
# Empty disables those endpoints; read-only views still work.
WEB_API_TOKEN=${WEB_API_TOKEN}
EOF

    chmod 600 "${PROJECT_ROOT}/.env"

    # ── Process config templates ──────────────────────────────
    log_info "Processing configuration templates..."
    process_templates

    log_success "Configuration complete."
}

validate_hostname() {
    local hostname="$1"
    if [[ ! "$hostname" =~ ^[a-zA-Z0-9]([a-zA-Z0-9\.\-]*[a-zA-Z0-9])?$ ]]; then
        log_error "Invalid domain: ${hostname}"
        exit 1
    fi
}

validate_node_id() {
    local node_id="$1"
    if [[ ! "$node_id" =~ ^[a-z0-9][a-z0-9\-]*[a-z0-9]$ ]] && [[ ! "$node_id" =~ ^[a-z0-9]$ ]]; then
        log_error "Invalid node ID: ${node_id}. Must be lowercase alphanumeric with hyphens."
        exit 1
    fi
}

process_templates() {
    local templates=(
        "config/conduit/conduit.toml.template:config/conduit/conduit.toml"
        "config/gotosocial/config.yaml.template:config/gotosocial/config.yaml"
        "config/element/config.json.template:config/element/config.json"
        "config/nginx/conf.d/matrix.conf.template:config/nginx/conf.d/matrix.conf"
        "config/nginx/conf.d/gotosocial.conf.template:config/nginx/conf.d/gotosocial.conf"
        "config/nginx/conf.d/element.conf.template:config/nginx/conf.d/element.conf"
        "config/nginx/conf.d/swarm.conf.template:config/nginx/conf.d/swarm.conf"
    )

    local entry src dest
    for entry in "${templates[@]}"; do
        src="${PROJECT_ROOT}/${entry%%:*}"
        dest="${PROJECT_ROOT}/${entry##*:}"

        if [[ ! -f "$src" ]]; then
            log_warn "Template not found: ${src}. Skipping."
            continue
        fi

        cp "$src" "$dest"
        replace_placeholder "$dest" "__DOMAIN__" "$DOMAIN"
        replace_placeholder "$dest" "__NODE_ID__" "$NODE_ID"
        replace_placeholder "$dest" "__NODE_NAME__" "$NODE_NAME"
        replace_placeholder "$dest" "__LLM_MODEL__" "$LLM_MODEL"
        replace_placeholder "$dest" "__EMBEDDING_MODEL__" "$EMBEDDING_MODEL"
        replace_placeholder "$dest" "__ROUND_INTERVAL__" "$ROUND_INTERVAL"
        replace_placeholder "$dest" "__ROUND_MODE__" "$ROUND_MODE"
        replace_placeholder "$dest" "__MESSAGE_THRESHOLD__" "$MESSAGE_THRESHOLD"
        replace_placeholder "$dest" "__MATRIX_ADMIN_PASSWORD__" "$MATRIX_ADMIN_PASSWORD"
        replace_placeholder "$dest" "__GOTOSOCIAL_ADMIN_EMAIL__" "$GOTOSOCIAL_ADMIN_EMAIL"

        log_info "  Processed: ${dest}"
    done

    # Process orchestrator config
    if [[ -f "${PROJECT_ROOT}/config/default.toml" ]]; then
        local orch_config="${PROJECT_ROOT}/config/default.toml"
        # Create a working copy if it has placeholders
        if grep -q "__" "$orch_config" 2>/dev/null; then
            replace_placeholder "$orch_config" "__DOMAIN__" "$DOMAIN"
            replace_placeholder "$orch_config" "__NODE_ID__" "$NODE_ID"
            replace_placeholder "$orch_config" "__NODE_NAME__" "$NODE_NAME"
            replace_placeholder "$orch_config" "__LLM_MODEL__" "$LLM_MODEL"
            replace_placeholder "$orch_config" "__EMBEDDING_MODEL__" "$EMBEDDING_MODEL"
            replace_placeholder "$orch_config" "__ROUND_INTERVAL__" "$ROUND_INTERVAL"
            replace_placeholder "$orch_config" "__ROUND_MODE__" "$ROUND_MODE"
            replace_placeholder "$orch_config" "__MESSAGE_THRESHOLD__" "$MESSAGE_THRESHOLD"
            log_info "  Processed: ${orch_config}"
        fi
    fi

    # Process topology file
    if [[ ! -f "${PROJECT_ROOT}/config/topology.toml" ]] && [[ -f "${PROJECT_ROOT}/config/topology.example.toml" ]]; then
        cp "${PROJECT_ROOT}/config/topology.example.toml" "${PROJECT_ROOT}/config/topology.toml"
        replace_placeholder "${PROJECT_ROOT}/config/topology.toml" "__NODE_ID__" "$NODE_ID"
        replace_placeholder "${PROJECT_ROOT}/config/topology.toml" "__NODE_NAME__" "$NODE_NAME"
        replace_placeholder "${PROJECT_ROOT}/config/topology.toml" "__DOMAIN__" "$DOMAIN"
        log_info "  Processed: config/topology.toml"
    fi
}
