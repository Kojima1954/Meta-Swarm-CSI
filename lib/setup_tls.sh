#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  N.O.M.A.D. Swarm Intelligence — TLS Certificate Setup
# ═══════════════════════════════════════════════════════════════
# Run this AFTER DNS is configured and pointing to this server.
# Not called during install.sh — run manually:
#   sudo bash lib/setup_tls.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

setup_tls() {
    # Load environment
    if [[ -f "${PROJECT_ROOT}/.env" ]]; then
        set -a
        # shellcheck disable=SC1091
        source "${PROJECT_ROOT}/.env"
        set +a
    else
        log_error ".env file not found. Run install.sh first."
        exit 1
    fi

    local domain="${DOMAIN:?DOMAIN not set in .env}"
    local email="${GOTOSOCIAL_ADMIN_EMAIL:?GOTOSOCIAL_ADMIN_EMAIL not set in .env}"

    log_info "Setting up TLS certificates for ${domain}..."

    # ── Stop nginx to free ports 80/443 ───────────────────────
    log_info "Temporarily stopping nginx..."
    (cd "$PROJECT_ROOT" && docker compose stop nginx) || true

    # ── Request certificate via certbot ───────────────────────
    log_info "Requesting Let's Encrypt certificate..."
    if ! docker run --rm \
        -v certbot-etc:/etc/letsencrypt \
        -v certbot-var:/var/lib/letsencrypt \
        -p 80:80 \
        certbot/certbot certonly \
        --standalone \
        -d "$domain" \
        --agree-tos \
        --email "$email" \
        --non-interactive; then
        log_error "Certificate request failed. Ensure DNS A record points to this server."
        # Restart nginx anyway
        (cd "$PROJECT_ROOT" && docker compose start nginx) || true
        exit 1
    fi

    log_success "TLS certificate obtained for ${domain}."

    # ── Restart nginx with TLS ────────────────────────────────
    log_info "Restarting nginx with TLS..."
    (cd "$PROJECT_ROOT" && docker compose start nginx)

    # ── Set up renewal cron job ───────────────────────────────
    setup_renewal_cron "$domain"

    log_success "TLS setup complete. Your services are now available over HTTPS."
}

setup_renewal_cron() {
    local domain="$1"
    local cron_cmd="0 3 * * * docker run --rm -v certbot-etc:/etc/letsencrypt -v certbot-var:/var/lib/letsencrypt certbot/certbot renew --quiet && cd ${PROJECT_ROOT} && docker compose exec nginx nginx -s reload"

    # Check if cron job already exists
    if crontab -l 2>/dev/null | grep -q "certbot renew"; then
        log_info "Certbot renewal cron job already exists."
        return 0
    fi

    # Add cron job
    (crontab -l 2>/dev/null; echo "$cron_cmd") | crontab -
    log_info "Certbot auto-renewal cron job installed (runs daily at 3 AM)."
}

# Run directly if executed as a script
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    require_root
    setup_tls
fi
