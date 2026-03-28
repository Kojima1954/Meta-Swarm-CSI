#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  N.O.M.A.D. Swarm Intelligence — Encryption Keypair Generation
# ═══════════════════════════════════════════════════════════════

generate_keys() {
    local keys_dir="${PROJECT_ROOT}/data/keys"
    mkdir -p "$keys_dir"

    if [[ -f "${keys_dir}/node.key" && -f "${keys_dir}/node.pub" ]]; then
        log_info "Encryption keypair already exists. Skipping generation."
        display_public_key "$keys_dir"
        return 0
    fi

    log_info "Generating X25519 encryption keypair..."

    docker run --rm -v "${keys_dir}:/keys" \
        python:3.12-slim \
        bash -c "
            pip install -q PyNaCl 2>/dev/null &&
            python3 -c \"
from nacl.public import PrivateKey
import base64
key = PrivateKey.generate()
with open('/keys/node.key', 'w') as f:
    f.write(base64.b64encode(bytes(key)).decode())
with open('/keys/node.pub', 'w') as f:
    f.write(base64.b64encode(bytes(key.public_key)).decode())
\"
        "

    if [[ ! -f "${keys_dir}/node.key" || ! -f "${keys_dir}/node.pub" ]]; then
        log_error "Keypair generation failed."
        exit 1
    fi

    chmod 600 "${keys_dir}/node.key"
    chmod 644 "${keys_dir}/node.pub"

    log_success "Keypair generated."
    display_public_key "$keys_dir"
}

display_public_key() {
    local keys_dir="$1"
    local pub_key
    pub_key=$(cat "${keys_dir}/node.pub")

    echo ""
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║  Your Node Public Key (share with swarm peers):        ║"
    echo "╠══════════════════════════════════════════════════════════╣"
    echo "║                                                        ║"
    printf "║  %-54s ║\n" "$pub_key"
    echo "║                                                        ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo ""
}
