#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  N.O.M.A.D. Swarm Intelligence — Docker Installation
# ═══════════════════════════════════════════════════════════════

install_docker() {
    # ── Check if Docker + Compose v2 already installed ────────
    if command -v docker &>/dev/null && docker compose version &>/dev/null; then
        local compose_ver
        compose_ver=$(docker compose version --short 2>/dev/null || echo "unknown")
        log_info "Docker and Compose v2 already installed (Compose ${compose_ver}). Skipping."
        return 0
    fi

    log_info "Installing Docker CE and Compose v2 plugin..."

    # ── Install prerequisites ─────────────────────────────────
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg lsb-release

    # ── Add Docker GPG key and repository ─────────────────────
    install -m 0755 -d /etc/apt/keyrings

    local distro
    # shellcheck disable=SC1091
    source /etc/os-release
    distro="${ID}"

    if [[ ! -f /etc/apt/keyrings/docker.gpg ]]; then
        curl -fsSL "https://download.docker.com/linux/${distro}/gpg" | \
            gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        chmod a+r /etc/apt/keyrings/docker.gpg
    fi

    local arch
    arch=$(dpkg --print-architecture)

    echo \
        "deb [arch=${arch} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${distro} \
        $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list

    # ── Install Docker packages ───────────────────────────────
    apt-get update -qq
    apt-get install -y -qq \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        docker-buildx-plugin \
        docker-compose-plugin

    # ── Enable and start Docker ───────────────────────────────
    systemctl enable --now docker

    # ── Verify ────────────────────────────────────────────────
    if docker run --rm hello-world &>/dev/null; then
        log_success "Docker installed and verified."
    else
        log_error "Docker installation failed verification."
        exit 1
    fi

    # ── NVIDIA Container Toolkit (if GPU detected) ────────────
    if [[ "${HAS_NVIDIA_GPU:-false}" == "true" ]]; then
        install_nvidia_container_toolkit
    fi
}

install_nvidia_container_toolkit() {
    if dpkg -l nvidia-container-toolkit &>/dev/null 2>&1; then
        log_info "NVIDIA Container Toolkit already installed. Skipping."
        return 0
    fi

    log_info "Installing NVIDIA Container Toolkit..."

    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
        gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

    curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' > \
        /etc/apt/sources.list.d/nvidia-container-toolkit.list

    apt-get update -qq
    apt-get install -y -qq nvidia-container-toolkit

    # Configure Docker to use NVIDIA runtime
    nvidia-ctk runtime configure --runtime=docker
    systemctl restart docker

    log_success "NVIDIA Container Toolkit installed."
}
