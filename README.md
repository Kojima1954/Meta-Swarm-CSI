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
| **Swarm Orchestrator** | Custom Python service orchestrating the CSI lifecycle, including a built-in web UI and REST/WebSocket API |

## Architecture

```
swarm-orchestrator/          # The CSI engine (Python, async)
├── src/orchestrator/
│   ├── matrix/              # Matrix room listener + Swarm Signal injection
│   ├── llm/                 # Two-pass LLM summarization via Ollama
│   ├── rag/                 # Qdrant vector store for context retrieval
│   ├── federation/          # Encrypted summary exchange via GoToSocial
│   ├── topology/            # Swarm graph management
│   ├── rounds/              # DISCUSS → SUMMARIZE → PROPAGATE state machine
│   └── web/                 # FastAPI web UI + REST + WebSocket API
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
or manually via `!summarize` in chat — or via the web UI / REST API.

## Web UI

Every node ships with a production web UI served by the orchestrator itself.
After install it's available at:

```
https://swarm.<your-domain>
```

and directly on the internal network at `http://swarm-orchestrator:8080`.

The UI provides:

- **Dashboard** — live phase, round number, transcript stats, uptime, and a
  countdown to the next automatic round. Includes a one-click trigger button.
- **Summaries** — browse and filter every SwarmSummary produced locally or
  received from peers, with key positions, consensus, dissent, and open
  questions rendered structurally.
- **Transcript** — live Matrix room feed, with Swarm Signals highlighted.
- **Topology** — circular graph of the swarm, showing each peer's role and
  whether their public key is loaded.
- **Events** — tail of every orchestrator event (round transitions,
  federation activity, manual triggers).
- **Settings** — view the active (redacted) config, manage the API token.

### REST API

Every panel in the UI is also a plain REST endpoint. Useful for scripting
or integrating another front-end.

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/api/v1/health` | Liveness probe (no auth) |
| `GET`  | `/api/v1/status` | Node, phase, round, transcript stats |
| `GET`  | `/api/v1/topology` | Nodes + roles + key-loaded flags |
| `GET`  | `/api/v1/transcript?limit=N` | Recent transcript entries |
| `GET`  | `/api/v1/summaries?limit=N` | Recent SwarmSummaries |
| `GET`  | `/api/v1/events/recent?limit=N` | Recent event bus history |
| `GET`  | `/api/v1/config` | Active config, secrets redacted |
| `POST` | `/api/v1/rounds/trigger` | Trigger a round (requires bearer token) |
| `WS`   | `/ws` | Live event stream |

Interactive docs are available at `/api/docs` (FastAPI-generated).

### Authentication

Mutating endpoints (`POST /api/v1/rounds/trigger`) require a bearer token.

- The installer generates a random 32-char token and writes it to `.env`
  as `WEB_API_TOKEN`.
- Paste the token into the Settings tab of the UI once; it's stored in
  `localStorage` and sent on every control request.
- To disable control endpoints entirely, set `WEB_API_TOKEN=` (empty).
  Read-only views still work.

### WebSocket event types

Subscribe to `/ws` to receive JSON-encoded events as the orchestrator runs:

| Event type | Data |
|-----------|------|
| `orchestrator.running` | `node_id`, `version` |
| `round.phase` | `phase`, `round` |
| `round.complete` | `next_round` |
| `round.failed` | `round` |
| `round.manual_trigger` | `source` |
| `message.received` | `timestamp`, `sender`, `body`, `is_swarm_signal`, `message_count`, `participant_count` |
| `summary.created` | `origin` (`local`/`federation`), `source_name`, `summary` (full SwarmSummary) |

On connect the server replays the last ~50 events so newly-opened UIs have
immediate context; thereafter events are pushed live.

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
│   ├── src/orchestrator/     # Application source (core + web UI)
│   └── tests/                # 58 passing tests
└── docs/
    └── INSTALL.md            # Detailed installation guide
```

## License

This project is a companion stack for Project N.O.M.A.D., which is licensed
under the Apache License 2.0.
