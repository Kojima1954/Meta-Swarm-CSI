#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  N.O.M.A.D. Swarm Intelligence — Master Installer
# ═══════════════════════════════════════════════════════════════
#
# Usage:
#   sudo bash install.sh
#
# Supports two modes:
#   Interactive (default): prompts for domain, node ID, etc.
#   Unattended: set NONINTERACTIVE=1 and provide values as env vars.
#
# Environment variables for unattended mode:
#   NONINTERACTIVE=1
#   DOMAIN=swarm.example.org
#   NODE_ID=node-alpha
#   NODE_NAME="Node Alpha"
#   LLM_MODEL=llama3.1:8b
#   EMBEDDING_MODEL=nomic-embed-text
#   ROUND_INTERVAL=300
#   MATRIX_ADMIN_PASSWORD=<generated if not set>
#   GOTOSOCIAL_ADMIN_EMAIL=admin@example.org

set -euo pipefail

TOTAL_PHASES=8

# ─── Source common library ────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

# ─── Banner ───────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║     N.O.M.A.D. Swarm Intelligence — Installer v${NOMAD_SWARM_VERSION}    ║${RESET}"
echo -e "${BOLD}║     Conversational Swarm Intelligence for N.O.M.A.D.    ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${RESET}"
echo ""

# ─── Phase 1: Root check ─────────────────────────────────────
require_root

# ─── Phase 2: Preflight checks ───────────────────────────────
log_phase 1 $TOTAL_PHASES "Running preflight checks..."
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/preflight.sh"
run_preflight_checks

# ─── Phase 3: Docker installation ────────────────────────────
log_phase 2 $TOTAL_PHASES "Ensuring Docker is installed..."
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/install_docker.sh"
install_docker

# ─── Phase 4: N.O.M.A.D. installation ────────────────────────
log_phase 3 $TOTAL_PHASES "Installing Project N.O.M.A.D...."
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/install_nomad.sh"
install_nomad

# ─── Phase 5: Wait for N.O.M.A.D. ────────────────────────────
log_phase 4 $TOTAL_PHASES "Waiting for N.O.M.A.D. Command Center..."
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/wait_for_nomad.sh"
wait_for_nomad

# ─── Phase 6: Detect existing services ───────────────────────
log_phase 5 $TOTAL_PHASES "Detecting existing AI services..."
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/detect_services.sh"
detect_services

# ─── Phase 7: Configuration wizard ───────────────────────────
log_phase 6 $TOTAL_PHASES "Configuring Swarm Intelligence..."
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/configure_swarm.sh"
configure_swarm

# ─── Phase 8: Generate encryption keys ───────────────────────
log_phase 7 $TOTAL_PHASES "Generating encryption keypair..."
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/generate_keys.sh"
generate_keys

# ─── Phase 9: Provision models ────────────────────────────────
# (handled inside start_swarm after services are up)

# ─── Phase 10: Launch swarm stack ─────────────────────────────
log_phase 8 $TOTAL_PHASES "Launching Swarm Intelligence stack..."
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/provision_models.sh"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/start_swarm.sh"
start_swarm

# ─── Completion banner ────────────────────────────────────────
local_ip=$(get_local_ip)

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║          Installation Complete!                         ║${RESET}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════╣${RESET}"
echo -e "${BOLD}║                                                        ║${RESET}"
echo -e "${BOLD}║  N.O.M.A.D. Command Center:                           ║${RESET}"
printf  "║    http://%-46s ║\n" "${local_ip}:8080"
echo -e "${BOLD}║                                                        ║${RESET}"
echo -e "${BOLD}║  Element Web (Matrix Chat):                            ║${RESET}"
printf  "║    http://%-46s ║\n" "${local_ip}:80"
echo -e "${BOLD}║                                                        ║${RESET}"
echo -e "${BOLD}║  Next steps:                                           ║${RESET}"
echo -e "${BOLD}║  1. Point DNS A record for ${DOMAIN} to ${local_ip}   ║${RESET}"
echo -e "${BOLD}║  2. Run: sudo bash lib/setup_tls.sh                   ║${RESET}"
echo -e "${BOLD}║  3. Share your public key with swarm peers             ║${RESET}"
echo -e "${BOLD}║  4. Edit config/topology.toml to add peer nodes       ║${RESET}"
echo -e "${BOLD}║                                                        ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${RESET}"
echo ""
