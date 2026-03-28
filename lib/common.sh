#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  N.O.M.A.D. Swarm Intelligence — Shared Functions
# ═══════════════════════════════════════════════════════════════
# Sourced by all other scripts. Provides logging, validation,
# and utility functions used throughout the installer.

set -euo pipefail

# ─── Script location ──────────────────────────────────────────
COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$COMMON_DIR/.." && pwd)"

# ─── Version ──────────────────────────────────────────────────
NOMAD_SWARM_VERSION="0.1.0"

# ─── Color codes (disabled if stdout is not a TTY) ───────────
if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    RESET='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    CYAN=''
    BOLD=''
    RESET=''
fi

# ─── Logging ─────────────────────────────────────────────────

log_info() {
    echo -e "${CYAN}ℹ️  $*${RESET}"
}

log_warn() {
    echo -e "${YELLOW}⚠️  $*${RESET}" >&2
}

log_error() {
    echo -e "${RED}❌ $*${RESET}" >&2
}

log_success() {
    echo -e "${GREEN}✅ $*${RESET}"
}

log_phase() {
    local phase_num="$1"
    local total_phases="$2"
    shift 2
    echo ""
    echo -e "${BOLD}[${phase_num}/${total_phases}] $*${RESET}"
    echo "────────────────────────────────────────────────────"
}

# ─── Error handler ───────────────────────────────────────────

error_handler() {
    local line="$1"
    local exit_code="$2"
    local command="${BASH_COMMAND:-unknown}"
    log_error "Command failed at line ${line}: ${command} (exit code: ${exit_code})"
}

trap 'error_handler ${LINENO} $?' ERR

# ─── Utility functions ───────────────────────────────────────

require_command() {
    local cmd="$1"
    if ! command -v "$cmd" &>/dev/null; then
        return 1
    fi
    return 0
}

require_root() {
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        log_error "This script must be run as root. Use: sudo bash $0"
        exit 1
    fi
}

generate_password() {
    local length="${1:-32}"
    openssl rand -base64 48 | tr -dc 'a-zA-Z0-9' | head -c "$length"
}

wait_for_http() {
    local url="$1"
    local timeout="${2:-60}"
    local interval=3
    local elapsed=0

    while [[ $elapsed -lt $timeout ]]; do
        if curl -fsSL --max-time 5 -o /dev/null "$url" 2>/dev/null; then
            return 0
        fi
        sleep "$interval"
        elapsed=$((elapsed + interval))
    done
    return 1
}

prompt_or_env() {
    local var_name="$1"
    local prompt_text="$2"
    local default_value="${3:-}"

    # If variable is already set and non-empty, use it
    local current_value="${!var_name:-}"
    if [[ -n "$current_value" ]]; then
        printf '%s' "$current_value"
        return 0
    fi

    if [[ "${NONINTERACTIVE:-0}" == "1" ]]; then
        if [[ -n "$default_value" ]]; then
            printf '%s' "$default_value"
        else
            log_error "Variable ${var_name} is required but not set (unattended mode)."
            exit 1
        fi
    else
        local input
        if [[ -n "$default_value" ]]; then
            read -rp "${prompt_text} [${default_value}]: " input
            printf '%s' "${input:-$default_value}"
        else
            read -rp "${prompt_text}: " input
            if [[ -z "$input" ]]; then
                log_error "${var_name} is required."
                exit 1
            fi
            printf '%s' "$input"
        fi
    fi
}

replace_placeholder() {
    local file="$1"
    local placeholder="$2"
    local value="$3"
    # Escape special sed characters in value
    local escaped_value
    escaped_value=$(printf '%s\n' "$value" | sed 's/[&/\]/\\&/g')
    sed -i "s|${placeholder}|${escaped_value}|g" "$file"
}

detect_nvidia_gpu() {
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
        return 0
    fi
    if command -v lspci &>/dev/null && lspci 2>/dev/null | grep -qi nvidia; then
        return 0
    fi
    return 1
}

get_local_ip() {
    local ip
    ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')
    if [[ -z "$ip" ]]; then
        ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    fi
    printf '%s' "${ip:-127.0.0.1}"
}
