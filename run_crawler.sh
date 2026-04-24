#!/usr/bin/env bash
# run_crawler.sh — start the job ingestion pipeline
# Usage: bash run_crawler.sh [conda-env-name]
#   conda-env-name defaults to "base"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_ENV="${1:-base}"
OLLAMA_ENDPOINT="http://localhost:11434/api/tags"

# ── 1. Check / start Ollama ───────────────────────────────────────────────────
if curl -sf "$OLLAMA_ENDPOINT" > /dev/null 2>&1; then
    echo "[OK]  Ollama daemon is running."
else
    echo "[WARN] Ollama is not responding at $OLLAMA_ENDPOINT."
    if command -v ollama > /dev/null 2>&1; then
        echo "[INFO] Starting Ollama in the background..."
        ollama serve > /tmp/ollama.log 2>&1 &
        echo "[INFO] Waiting for Ollama to be ready..."
        for i in $(seq 1 15); do
            sleep 1
            if curl -sf "$OLLAMA_ENDPOINT" > /dev/null 2>&1; then
                echo "[OK]  Ollama is ready."
                break
            fi
            if [ "$i" -eq 15 ]; then
                echo "[ERROR] Ollama did not start in time. Check /tmp/ollama.log."
                exit 1
            fi
        done
    else
        echo "[ERROR] 'ollama' binary not found. Install it from https://ollama.com/download"
        exit 1
    fi
fi

# ── 2. Activate conda environment ────────────────────────────────────────────
# Locate the conda installation (checks common macOS paths).
CONDA_SH=""
for candidate in \
    "$HOME/miniconda3/etc/profile.d/conda.sh" \
    "$HOME/anaconda3/etc/profile.d/conda.sh" \
    "/opt/miniconda3/etc/profile.d/conda.sh" \
    "/opt/anaconda3/etc/profile.d/conda.sh" \
    "/usr/local/miniconda3/etc/profile.d/conda.sh"
do
    if [ -f "$candidate" ]; then
        CONDA_SH="$candidate"
        break
    fi
done

if [ -z "$CONDA_SH" ]; then
    echo "[ERROR] conda.sh not found. Is Miniconda/Anaconda installed?"
    exit 1
fi

# shellcheck disable=SC1090
source "$CONDA_SH"
conda activate "$CONDA_ENV"
echo "[OK]  Conda environment '$CONDA_ENV' activated."

# ── 3. Run the pipeline ───────────────────────────────────────────────────────
echo "[INFO] Starting pipeline at $(date '+%Y-%m-%d %H:%M:%S')..."
python "$SCRIPT_DIR/main.py"

# ── 4. Deactivate env ────────────────────────────────────────────────────────
conda deactivate
echo "[INFO] Done."
