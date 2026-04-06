# N.O.M.A.D. Swarm Intelligence — Installation Guide

## Prerequisites

### Hardware Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU      | 4 cores | 8+ cores    |
| RAM      | 4 GB    | 16+ GB      |
| Disk     | 20 GB   | 50+ GB      |
| GPU      | None    | NVIDIA (for faster LLM inference) |

### Software Requirements

- **OS**: Ubuntu 22.04+ or Debian 12+
- **Architecture**: x86_64 (amd64) or aarch64 (arm64)
- **Shell**: Bash
- **Internet**: Required for downloading Docker images and AI models

The installer will automatically install Docker and Docker Compose v2 if not
present.

### Network Requirements

- Ports 80, 443, 8448 must be available (or configurable)
- A domain name with DNS A record pointing to your server (for TLS/federation)
- Outbound internet access for image pulls and model downloads

---

## Quick Install

```bash
git clone https://github.com/OWNER/nomad-swarm.git
cd nomad-swarm
sudo bash install.sh
```

The interactive wizard will guide you through configuration.

---

## What the Installer Does

The installer runs through these phases:

| Phase | Description |
|-------|-------------|
| 1     | **Preflight checks** — Validates OS, architecture, RAM, disk, internet |
| 2     | **Docker installation** — Installs Docker CE + Compose v2 if missing; NVIDIA toolkit if GPU detected |
| 3     | **N.O.M.A.D. bootstrap** — Downloads and starts Project N.O.M.A.D. management stack at `/opt/project-nomad` |
| 4     | **Wait for N.O.M.A.D.** — Polls the Command Center until it's ready (up to 180s) |
| 5     | **Service detection** — Checks if Ollama/Qdrant are already running via N.O.M.A.D. |
| 6     | **Configuration** — Interactive wizard (or env vars) for domain, node ID, models, etc. |
| 7     | **Key generation** — Creates X25519 encryption keypair for inter-node communication |
| 8     | **Stack launch** — Starts all swarm services, creates Matrix room, provisions AI models |

---

## Unattended Install

Set environment variables and use `NONINTERACTIVE=1`:

```bash
export NONINTERACTIVE=1
export DOMAIN=swarm.example.org
export NODE_ID=node-alpha
export NODE_NAME="Node Alpha"
export LLM_MODEL=llama3.1:8b
export EMBEDDING_MODEL=nomic-embed-text
export ROUND_INTERVAL=300
export GOTOSOCIAL_ADMIN_EMAIL=admin@example.org

sudo -E bash install.sh
```

The `-E` flag preserves environment variables through `sudo`.

---

## Post-Install Setup

### 1. DNS Configuration

Point your domain's DNS A record to your server's public IP:

```
swarm.example.org.    A    203.0.113.10
element.swarm.example.org.    A    203.0.113.10
```

### 2. TLS Certificate Setup

After DNS propagation (may take up to 48 hours):

```bash
sudo bash lib/setup_tls.sh
```

This uses Let's Encrypt to obtain and configure TLS certificates.

### 3. Topology Configuration

Edit `config/topology.toml` to add peer nodes to your swarm:

```toml
[[nodes]]
id = "node-beta"
name = "Node Beta"
domain = "beta.example.org"
public_key = "BASE64_PUBLIC_KEY_FROM_PEER"
role = "participant"
is_self = false
```

### 4. Sharing Public Keys

Your node's public key is displayed during installation and stored at
`data/keys/node.pub`. Share this with swarm peers so they can add your
node to their topology.

---

## Joining a Swarm

1. Each node operator runs the installer on their own server
2. Exchange public keys (from `data/keys/node.pub`)
3. Each operator adds all other nodes to their `config/topology.toml`
4. Restart the orchestrator: `docker compose restart swarm-orchestrator`

The swarm will begin deliberation rounds automatically based on the
configured `ROUND_MODE` and `ROUND_INTERVAL`.

---

## AI Service Modes

The installer auto-detects whether Ollama and Qdrant are running:

- **Self-managed mode** (default): Our docker-compose.yml starts Ollama and
  Qdrant. They work perfectly but won't appear in N.O.M.A.D.'s Command Center.
- **NOMAD-managed mode**: If you've installed Ollama/Qdrant through N.O.M.A.D.'s
  UI, we detect them and connect to the existing containers.

To switch from self-managed to NOMAD-managed:
1. Install Ollama and Qdrant from the N.O.M.A.D. Command Center
2. Edit `.env` and set `COMPOSE_PROFILES=` (empty)
3. Restart: `docker compose up -d`

---

## Troubleshooting

### N.O.M.A.D. Command Center not responding

```bash
docker compose -p project-nomad -f /opt/project-nomad/compose.yml logs
docker compose -p project-nomad -f /opt/project-nomad/compose.yml ps
```

### Swarm services not starting

```bash
cd /path/to/nomad-swarm
docker compose ps
docker compose logs <service-name>
```

### Model download fails or is slow

Ollama model pulls can take 10-30+ minutes depending on your connection.
Check progress:

```bash
docker compose logs ollama
```

To manually pull a model:

```bash
curl -X POST http://localhost:11434/api/pull \
  -H "Content-Type: application/json" \
  -d '{"name": "llama3.1:8b"}'
```

### Port conflicts

Check what's using a port:

```bash
ss -tlnp | grep :8080
```

### TLS certificate issues

Ensure DNS is pointing to your server before running `setup_tls.sh`.
Test with:

```bash
dig +short swarm.example.org
```

For testing, use Let's Encrypt staging:

```bash
# Modify the certbot command in lib/setup_tls.sh to add --staging
```

### Services unreachable from the Windows host (VM deployments)

If you run the stack inside a VM (e.g., WSL 2, Hyper-V, VirtualBox) and can
`curl` a service from **inside** the VM but not from Windows, the most common
cause is the service binding to `127.0.0.1` instead of `0.0.0.0`.

Ollama and Qdrant intentionally bind to `127.0.0.1` in `docker-compose.yml`
because they are back-end services that should not be publicly exposed. Other
containers reach them over the internal Docker network using service names
(`ollama:11434`, `qdrant:6333`). If you need to reach them from the host for
debugging:

```yaml
# docker-compose.override.yml (do NOT commit)
services:
  ollama:
    ports:
      - "0.0.0.0:11434:11434"
```

> **Security note:** Never expose back-end ports to `0.0.0.0` in production.

### Conduit well-known federation not working

Conduit v0.8+ uses a flat configuration key for well-known delegation. The
old dotted form (`well_known.server`) is **silently ignored**. Make sure
`config/conduit/conduit.toml` uses the new format:

```toml
well_known_server = "yourdomain.example:443"
well_known_client = "https://yourdomain.example"
```

As a drop-in alternative, [conduwuit](https://github.com/girlbossceo/conduwuit)
is a more actively maintained community fork of Conduit. Change
`CONDUIT_IMAGE` in `.env` to switch:

```
CONDUIT_IMAGE=ghcr.io/girlbossceo/conduwuit:latest
```

### GoToSocial upgrade notes

GoToSocial source has moved to Codeberg
(<https://codeberg.org/superseriousbusiness/gotosocial>) as of v0.20.0 — the
GitHub mirror no longer exists. Docker Hub images are still published under
`superseriousbusiness/gotosocial`.

> **⚠ Database migrations:** Upgrading from a version older than 0.20.0 may
> trigger long-running database migrations. **Back up your data** before
> upgrading and allow extra time for the container to become ready.

### Ollama model reloading after restart

On CPU-only hosts, Ollama works reliably. However, if the container restarts
and `OLLAMA_KEEP_ALIVE` is not set, the model will be unloaded from memory
and the next request will take 10–30 seconds while it reloads. The default
`docker-compose.yml` sets `OLLAMA_KEEP_ALIVE=-1` (infinite) to prevent this.
Override via `.env`:

```
OLLAMA_KEEP_ALIVE=30m
```

---

## Updating

### Update N.O.M.A.D.

```bash
bash /opt/project-nomad/update_nomad.sh
```

### Update Swarm Stack

```bash
cd /path/to/nomad-swarm
git pull
docker compose pull
docker compose build swarm-orchestrator
docker compose up -d
```

---

## Uninstalling

```bash
sudo bash uninstall.sh
```

The uninstaller will prompt you to optionally:
- Remove Project N.O.M.A.D.
- Delete encryption keys and data

Templates and source files are preserved.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    nginx (reverse proxy)                  │
│                   :80 / :443 / :8448                     │
└──────┬──────────────┬──────────────────┬────────────────┘
       │              │                  │
┌──────▼──────┐ ┌─────▼──────┐ ┌────────▼────────┐
│   Conduit   │ │  Element   │ │   GoToSocial    │
│  (Matrix)   │ │   (Web)    │ │  (ActivityPub)  │
│   :6167     │ │   :80      │ │     :8080       │
└──────┬──────┘ └────────────┘ └────────┬────────┘
       │                                │
┌──────▼────────────────────────────────▼────────┐
│           Swarm Orchestrator (Python)           │
│          Manages deliberation rounds            │
└──────┬────────────────────────────┬────────────┘
       │                            │
┌──────▼──────┐            ┌───────▼──────┐
│   Ollama    │            │    Qdrant    │
│   (LLM)    │            │  (Vectors)   │
│  :11434     │            │   :6333      │
└─────────────┘            └──────────────┘

  Connected to: project-nomad_default network
```
