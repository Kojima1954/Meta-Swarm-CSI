# Swarm Orchestrator

Conversational Swarm Intelligence (CSI) orchestrator for N.O.M.A.D.

## Overview

The Swarm Orchestrator is an async Python service that coordinates decentralized
deliberation across a network of N.O.M.A.D. nodes. It:

- Monitors a local Matrix chat room for human deliberation
- Periodically summarizes conversations using a local LLM (Ollama)
- Encrypts summaries and distributes them to peer nodes via ActivityPub (GoToSocial)
- Receives summaries from peers, decrypts them, and injects them as "Swarm Signals"
- Stores all summaries in a vector database (Qdrant) for RAG context

## Architecture

```
Matrix Room ──► Transcript Buffer ──► LLM Summarizer ──► Encrypted Summary
                                          ▲                      │
                                          │                      ▼
                                     RAG Context          GoToSocial (outbound)
                                     (Qdrant)
                                          ▲
GoToSocial (inbound) ──► Decrypt ──► Swarm Signal ──► Matrix Room
```

## Configuration

Configuration is loaded from `/etc/orchestrator/config.toml` (override with
`ORCHESTRATOR_CONFIG` env var). See `config/default.toml` for all options.

## Running

The orchestrator runs as a Docker container alongside the N.O.M.A.D. companion
stack. It is started automatically by `docker compose up -d`.

```bash
# Build
docker compose build swarm-orchestrator

# Run
docker compose up -d swarm-orchestrator

# Logs
docker compose logs -f swarm-orchestrator
```

## Development

```bash
cd swarm-orchestrator
pip install -e ".[dev]"
pytest tests/ -v
```
