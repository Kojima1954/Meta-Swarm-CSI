#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  N.O.M.A.D. Swarm Intelligence — N.O.M.A.D. Bootstrap
# ═══════════════════════════════════════════════════════════════
# Replicates the official install_nomad.sh non-interactively.
# Downloads all required files and starts the management stack.

install_nomad() {
    if [[ "${NOMAD_ALREADY_INSTALLED:-false}" == "true" ]]; then
        log_info "N.O.M.A.D. is already installed. Skipping."
        return 0
    fi

    log_info "Installing Project N.O.M.A.D. to /opt/project-nomad..."

    local NOMAD_DIR="/opt/project-nomad"

    # ── URLs (pinned to main branch) ─────────────────────────
    local BASE_URL="https://raw.githubusercontent.com/Crosstalk-Solutions/project-nomad/refs/heads/main/install"
    local COMPOSE_URL="${BASE_URL}/management_compose.yaml"
    local ENTRYPOINT_URL="${BASE_URL}/entrypoint.sh"
    local SIDECAR_DOCKERFILE_URL="${BASE_URL}/sidecar-updater/Dockerfile"
    local SIDECAR_SCRIPT_URL="${BASE_URL}/sidecar-updater/update-watcher.sh"
    local START_URL="${BASE_URL}/start_nomad.sh"
    local STOP_URL="${BASE_URL}/stop_nomad.sh"
    local UPDATE_URL="${BASE_URL}/update_nomad.sh"

    # ── Create directory structure ────────────────────────────
    mkdir -p "$NOMAD_DIR"
    mkdir -p "$NOMAD_DIR/sidecar-updater"
    mkdir -p "$NOMAD_DIR/logs"

    # ── Download management compose file ──────────────────────
    log_info "Downloading management compose file..."
    if ! curl -fsSL "$COMPOSE_URL" -o "$NOMAD_DIR/docker-compose.yml"; then
        log_error "Failed to download: ${COMPOSE_URL}"
        exit 1
    fi

    # ── Generate MySQL passwords and substitute ───────────────
    local mysql_root_pass mysql_user_pass
    mysql_root_pass=$(generate_password 32)
    mysql_user_pass=$(generate_password 32)

    sed -i "s/MYSQL_ROOT_PASSWORD=replaceme/MYSQL_ROOT_PASSWORD=${mysql_root_pass}/g" \
        "$NOMAD_DIR/docker-compose.yml"
    sed -i "s/MYSQL_PASSWORD=replaceme/MYSQL_PASSWORD=${mysql_user_pass}/g" \
        "$NOMAD_DIR/docker-compose.yml"

    log_info "Generated and substituted MySQL passwords."

    # ── Download entrypoint script ────────────────────────────
    log_info "Downloading entrypoint script..."
    if ! curl -fsSL "$ENTRYPOINT_URL" -o "$NOMAD_DIR/entrypoint.sh"; then
        log_error "Failed to download: ${ENTRYPOINT_URL}"
        exit 1
    fi
    chmod +x "$NOMAD_DIR/entrypoint.sh"

    # ── Download sidecar updater files ────────────────────────
    log_info "Downloading sidecar updater..."
    if ! curl -fsSL "$SIDECAR_DOCKERFILE_URL" -o "$NOMAD_DIR/sidecar-updater/Dockerfile"; then
        log_error "Failed to download: ${SIDECAR_DOCKERFILE_URL}"
        exit 1
    fi
    if ! curl -fsSL "$SIDECAR_SCRIPT_URL" -o "$NOMAD_DIR/sidecar-updater/update-watcher.sh"; then
        log_error "Failed to download: ${SIDECAR_SCRIPT_URL}"
        exit 1
    fi
    chmod +x "$NOMAD_DIR/sidecar-updater/update-watcher.sh"

    # ── Download utility scripts ──────────────────────────────
    log_info "Downloading utility scripts..."
    local script_url
    for script_url in "$START_URL" "$STOP_URL" "$UPDATE_URL"; do
        local filename
        filename=$(basename "$script_url")
        if ! curl -fsSL "$script_url" -o "$NOMAD_DIR/${filename}"; then
            log_error "Failed to download: ${script_url}"
            exit 1
        fi
        chmod +x "$NOMAD_DIR/${filename}"
    done

    # ── Start N.O.M.A.D. management stack ────────────────────
    log_info "Starting N.O.M.A.D. management stack..."
    (cd "$NOMAD_DIR" && docker compose up -d)

    local local_ip
    local_ip=$(get_local_ip)
    log_success "N.O.M.A.D. installed. Command Center will be at http://${local_ip}:8080"
}
