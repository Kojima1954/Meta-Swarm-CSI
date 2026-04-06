# N.O.M.A.D. Swarm Intelligence

Conversational Swarm Intelligence (CSI) network for
[Project N.O.M.A.D.](https://github.com/Crosstalk-Solutions/project-nomad) —
decentralized deliberation through overlapping small groups connected by
AI-generated summaries over the Fediverse.

## How It Works

Small groups of humans chat in local Matrix rooms on their own N.O.M.A.D.
instance ("Node"). At configurable intervals, a local LLM summarizes the
group's deliberation. That encrypted summary is sent over ActivityPub to
adjacent Nodes, where it is decrypted and injected into their chat rooms as a
"Swarm Signal." This creates large-scale collective intelligence through
federated, overlapping small-group conversations.

```
  Node Alpha                    Node Beta                    Node Gamma
 ┌──────────┐    encrypted     ┌──────────┐    encrypted    ┌──────────┐
 │ 👥 Chat  │───summary──────▶│ 👥 Chat  │───summary─────▶│ 👥 Chat  │
 │ 🤖 LLM  │◀──────────────── │ 🤖 LLM  │◀────────────── │ 🤖 LLM  │
 │ 📊 Qdrant│   Swarm Signal  │ 📊 Qdrant│   Swarm Signal │ 📊 Qdrant│
 └──────────┘                  └──────────┘                 └──────────┘
      │                              │                            │
      └──────────── Project N.O.M.A.D. (each node) ──────────────┘
```

## Quick Start

```bash
git clone https://github.com/Kojima1954/Meta-Swarm-CSI.git
cd Meta-Swarm-CSI
sudo bash install.sh
```

One command installs everything: Project N.O.M.A.D., Docker, AI services,
Matrix homeserver, Fediverse endpoint, and the Swarm Orchestrator.

## What Gets Installed

| Service | Role |
|---------|------|
| [Project N.O.M.A.D.](https://github.com/Crosstalk-Solutions/project-nomad) | Offline-first survival computer (base platform) |
| [Conduit](https://conduit.rs/) / [conduwuit](https://github.com/girlbossceo/conduwuit) | Matrix homeserver for local chat (conduwuit is a more actively maintained fork) |
| [Element Web](https://element.io/) | Matrix web client |
| [GoToSocial](https://gotosocial.org/) | ActivityPub/Fediverse endpoint for inter-node communication ([source on Codeberg](https://codeberg.org/superseriousbusiness/gotosocial)) |
| [Ollama](https://ollama.ai/) | Local LLM inference |
| [Qdrant](https://qdrant.tech/) | Vector database for RAG context |
| Nginx | Reverse proxy with TLS termination |
| **Swarm Orchestrator** | Custom Python service orchestrating the CSI lifecycle |

## Architecture

```
swarm-orchestrator/          # The CSI engine (Python, async)
├── src/orchestrator/
│   ├── matrix/              # Matrix room listener + Swarm Signal injection
│   ├── llm/                 # Two-pass LLM summarization via Ollama
│   ├── rag/                 # Qdrant vector store for context retrieval
│   ├── federation/          # Encrypted summary exchange via GoToSocial
│   ├── topology/            # Swarm graph management
│   └── rounds/              # DISCUSS → SUMMARIZE → PROPAGATE state machine
```

The orchestrator runs as a single Docker container alongside the infrastructure
services. It connects to Matrix (Conduit) for chat, Ollama for AI, Qdrant for
memory, and GoToSocial for federation — all over the internal Docker network.

## Round Lifecycle

Each deliberation round follows three phases:

1. **DISCUSS** — Humans chat in the local Matrix room. Inbound Swarm Signals
   from peer nodes are injected into the conversation.
2. **SUMMARIZE** — The orchestrator feeds the transcript (+ RAG context +
   inbound signals) to the local LLM, producing a structured summary.
3. **PROPAGATE** — The summary is encrypted per-recipient (X25519 SealedBox)
   and sent as a direct message via ActivityPub to adjacent nodes.

Rounds can be triggered by timer (default: 5 minutes), message count threshold,
or manually via `!summarize` in chat.

## Configuration

### Interactive Install

The installer walks you through configuration:
- Domain name, node ID, display name
- LLM and embedding model selection
- Round timing mode and interval
- Matrix admin credentials
- GoToSocial admin email

### Unattended Install

```bash
NONINTERACTIVE=1 \
DOMAIN=swarm.example.org \
NODE_ID=node-alpha \
GOTOSOCIAL_ADMIN_EMAIL=admin@example.org \
sudo -E bash install.sh
```

See [docs/INSTALL.md](docs/INSTALL.md) for the full configuration reference.

## Post-Install

1. **DNS** — Point your domain's A record to the server
2. **TLS** — Run `sudo bash lib/setup_tls.sh` after DNS propagates
3. **Topology** — Edit `config/topology.toml` to add peer nodes
4. **Keys** — Share your public key (`data/keys/node.pub`) with peers

## Joining a Swarm

1. Each operator installs on their own server
2. Exchange public keys (from `data/keys/node.pub`)
3. Each operator adds peers to `config/topology.toml`
4. Restart: `docker compose restart swarm-orchestrator`

The swarm begins deliberating automatically.

## AI Service Modes

- **Self-managed** (default): Ollama and Qdrant run in the companion stack
- **NOMAD-managed**: If installed via N.O.M.A.D.'s UI, the orchestrator
  detects and connects to existing containers

## Requirements

- Ubuntu 22.04+ or Debian 12+
- 4 GB RAM minimum (16 GB+ recommended)
- 20 GB disk minimum (50 GB+ recommended)
- Internet connection (for Docker images and model downloads)
- NVIDIA GPU optional (auto-detected for accelerated inference)

## Project Structure

```
├── install.sh               # Master installer (8 phases)
├── uninstall.sh              # Full teardown
├── lib/                      # Installer library scripts
├── docker-compose.yml        # All services + optional self-managed AI
├── .env.example              # Configuration template
├── config/                   # Service configuration templates
│   ├── default.toml          # Orchestrator config
│   ├── topology.example.toml # Swarm topology
│   ├── conduit/              # Matrix homeserver config
│   ├── gotosocial/           # Fediverse config
│   ├── element/              # Matrix web client config
│   └── nginx/                # Reverse proxy config
├── swarm-orchestrator/       # The CSI engine
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── src/orchestrator/     # Application source
│   └── tests/                # 36 passing tests
└── docs/
    └── INSTALL.md            # Detailed installation guide
```

## License

This project is a companion stack for Project N.O.M.A.D., which is licensed
under the Apache License 2.0.
