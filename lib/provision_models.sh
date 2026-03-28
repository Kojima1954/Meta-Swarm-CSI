#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  N.O.M.A.D. Swarm Intelligence — Pull LLM & Embedding Models
# ═══════════════════════════════════════════════════════════════

provision_models() {
    local ollama_api="${OLLAMA_URL:-http://localhost:11434}"
    local llm_model="${LLM_MODEL:-llama3.1:8b}"
    local embedding_model="${EMBEDDING_MODEL:-nomic-embed-text}"

    # ── Wait for Ollama API ───────────────────────────────────
    log_info "Waiting for Ollama API at ${ollama_api}..."
    if ! wait_for_http "${ollama_api}" 60; then
        log_error "Ollama API did not become ready within 60 seconds."
        exit 1
    fi
    log_success "Ollama API is ready."

    # ── Pull LLM model ────────────────────────────────────────
    pull_model "$ollama_api" "$llm_model"

    # ── Pull embedding model ──────────────────────────────────
    pull_model "$ollama_api" "$embedding_model"

    log_success "All models provisioned."
}

pull_model() {
    local api_url="$1"
    local model_name="$2"
    local max_retries=3
    local retry_delay=10
    local attempt=1

    log_info "Pulling model: ${model_name} (this may take a while)..."

    while [[ $attempt -le $max_retries ]]; do
        if curl -fsSL -X POST "${api_url}/api/pull" \
            -H "Content-Type: application/json" \
            -d "{\"name\": \"${model_name}\"}" \
            --no-buffer 2>/dev/null | while IFS= read -r line; do
                local status
                status=$(echo "$line" | grep -o '"status":"[^"]*"' | head -1 | sed 's/"status":"//;s/"//')
                if [[ -n "$status" ]]; then
                    printf "\r  %s" "$status"
                fi
            done; then
            echo ""
            log_success "Model ${model_name} pulled successfully."
            return 0
        fi

        echo ""
        log_warn "Attempt ${attempt}/${max_retries} failed for model ${model_name}."
        if [[ $attempt -lt $max_retries ]]; then
            log_info "Retrying in ${retry_delay} seconds..."
            sleep "$retry_delay"
        fi
        attempt=$((attempt + 1))
    done

    log_error "Failed to pull model ${model_name} after ${max_retries} attempts."
    exit 1
}
