#!/usr/bin/env sh
set -eu
ollama serve &
pid=$!
until ollama list >/dev/null 2>&1; do sleep 1; done
if ! ollama list | grep -q "${OLLAMA_MODEL}"; then
  echo "Pulling ${OLLAMA_MODEL}..." >&2
  ollama pull "${OLLAMA_MODEL}"
fi
wait "$pid"
