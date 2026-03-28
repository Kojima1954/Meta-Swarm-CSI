#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  N.O.M.A.D. Swarm Intelligence — Uninstaller
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

require_root

echo ""
echo -e "${BOLD}N.O.M.A.D. Swarm Intelligence — Uninstaller${RESET}"
echo ""

# ─── Confirm ──────────────────────────────────────────────────
if [[ "${NONINTERACTIVE:-0}" != "1" ]]; then
    read -rp "Are you sure you want to uninstall the Swarm Intelligence stack? (y/N): " confirm
    if [[ "${confirm,,}" != "y" ]]; then
        log_info "Uninstall cancelled."
        exit 0
    fi
fi

# ─── Stop and remove swarm containers + volumes ──────────────
log_info "Stopping and removing Swarm Intelligence stack..."
cd "$PROJECT_ROOT"
if [[ -f docker-compose.yml ]]; then
    docker compose --profile self-managed down -v 2>/dev/null || true
    docker compose down -v 2>/dev/null || true
    log_success "Swarm stack removed."
else
    log_info "No docker-compose.yml found. Skipping."
fi

# ─── Ask about N.O.M.A.D. ────────────────────────────────────
remove_nomad=false
if [[ "${NONINTERACTIVE:-0}" != "1" ]]; then
    read -rp "Also uninstall Project N.O.M.A.D.? (y/N): " confirm_nomad
    if [[ "${confirm_nomad,,}" == "y" ]]; then
        remove_nomad=true
    fi
fi

if [[ "$remove_nomad" == "true" ]]; then
    log_info "Uninstalling Project N.O.M.A.D...."
    local uninstall_url="https://raw.githubusercontent.com/Crosstalk-Solutions/project-nomad/refs/heads/main/install/uninstall_nomad.sh"
    if curl -fsSL "$uninstall_url" -o /tmp/uninstall_nomad.sh; then
        bash /tmp/uninstall_nomad.sh
        rm -f /tmp/uninstall_nomad.sh
        log_success "N.O.M.A.D. uninstalled."
    else
        log_error "Failed to download N.O.M.A.D. uninstall script."
    fi
fi

# ─── Ask about data deletion ─────────────────────────────────
remove_data=false
if [[ "${NONINTERACTIVE:-0}" != "1" ]]; then
    read -rp "Delete encryption keys and data? (y/N): " confirm_data
    if [[ "${confirm_data,,}" == "y" ]]; then
        remove_data=true
    fi
fi

if [[ "$remove_data" == "true" ]]; then
    log_info "Removing data directory..."
    rm -rf "${PROJECT_ROOT}/data/"
    log_success "Data deleted."
fi

# ─── Remove generated config files (keep templates) ──────────
log_info "Removing generated configuration files..."
rm -f "${PROJECT_ROOT}/config/conduit/conduit.toml"
rm -f "${PROJECT_ROOT}/config/gotosocial/config.yaml"
rm -f "${PROJECT_ROOT}/config/element/config.json"
rm -f "${PROJECT_ROOT}/config/nginx/conf.d/matrix.conf"
rm -f "${PROJECT_ROOT}/config/nginx/conf.d/gotosocial.conf"
rm -f "${PROJECT_ROOT}/config/nginx/conf.d/element.conf"
rm -f "${PROJECT_ROOT}/config/topology.toml"
rm -f "${PROJECT_ROOT}/docker-compose.override.yml"

# ─── Remove .env ──────────────────────────────────────────────
rm -f "${PROJECT_ROOT}/.env"

log_success "Uninstall complete."
echo ""
echo "Templates and source files have been preserved."
echo "To fully remove, delete this directory: ${PROJECT_ROOT}"
