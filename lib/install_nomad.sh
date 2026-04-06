#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  N.O.M.A.D. Swarm Intelligence — N.O.M.A.D. Bootstrap
# ═══════════════════════════════════════════════════════════════
# Replicates the official install_nomad.sh non-interactively.
# Downloads the management compose file, configures credentials,
# and starts the self-contained management stack.
#
# Compatible with Project N.O.M.A.D. v1.30.3+.

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
    local START_URL="${BASE_URL}/start_nomad.sh"
    local STOP_URL="${BASE_URL}/stop_nomad.sh"
    local UPDATE_URL="${BASE_URL}/update_nomad.sh"

    # ── Create directory structure ────────────────────────────
    mkdir -p "$NOMAD_DIR"
    mkdir -p "$NOMAD_DIR/storage/logs"
    touch "$NOMAD_DIR/storage/logs/admin.log"

    # ── Download management compose file ──────────────────────
    log_info "Downloading management compose file..."
    if ! curl -fsSL "$COMPOSE_URL" -o "$NOMAD_DIR/compose.yml"; then
        log_error "Failed to download: ${COMPOSE_URL}"
        exit 1
    fi

    # ── Generate credentials and substitute ───────────────────
    local app_key mysql_root_pass mysql_user_pass local_ip
    app_key=$(generate_password 32)
    mysql_root_pass=$(generate_password 32)
    mysql_user_pass=$(generate_password 32)
    local_ip=$(get_local_ip)

    # Remove stale MySQL data to prevent credential mismatch on reinstall
    if [[ -d "$NOMAD_DIR/mysql" ]]; then
        log_info "Removing existing MySQL data directory to ensure credentials match..."
        rm -rf "$NOMAD_DIR/mysql"
    fi

    sed -i "s|URL=replaceme|URL=http://${local_ip}:8080|g" \
        "$NOMAD_DIR/compose.yml"
    sed -i "s|APP_KEY=replaceme|APP_KEY=${app_key}|g" \
        "$NOMAD_DIR/compose.yml"
    sed -i "s|DB_PASSWORD=replaceme|DB_PASSWORD=${mysql_user_pass}|g" \
        "$NOMAD_DIR/compose.yml"
    sed -i "s|MYSQL_ROOT_PASSWORD=replaceme|MYSQL_ROOT_PASSWORD=${mysql_root_pass}|g" \
        "$NOMAD_DIR/compose.yml"
    sed -i "s|MYSQL_PASSWORD=replaceme|MYSQL_PASSWORD=${mysql_user_pass}|g" \
        "$NOMAD_DIR/compose.yml"

    log_info "Generated and substituted credentials."

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
    (cd "$NOMAD_DIR" && docker compose -p project-nomad -f compose.yml up -d)

    log_success "N.O.M.A.D. installed. Command Center will be at http://${local_ip}:8080"
}
