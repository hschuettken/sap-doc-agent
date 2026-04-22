#!/usr/bin/env sh
# Ollama entrypoint: start the daemon, wait for it, pull the model if absent.
set -eu

OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:14b}"

# Start Ollama daemon in the background.
ollama serve &
PID=$!

# Wait until the API is responsive.
echo "Waiting for Ollama daemon..."
until ollama list > /dev/null 2>&1; do
    sleep 1
done
echo "Ollama daemon ready."

# Pull the model on first start (no-op if already cached in the volume).
if ! ollama list | grep -q "${OLLAMA_MODEL}"; then
    echo "Pulling model: ${OLLAMA_MODEL} ..."
    ollama pull "${OLLAMA_MODEL}"
    echo "Model ready: ${OLLAMA_MODEL}"
else
    echo "Model already cached: ${OLLAMA_MODEL}"
fi

wait "$PID"
