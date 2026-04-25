#!/bin/bash

# Move to the script's directory to ensure relative paths work
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "Starting Crawler Pipeline..."

# 1. Check if Ollama is running
if curl -s -m 5 http://localhost:11434/api/tags > /dev/null; then
    echo "[OK] Ollama daemon is responding."
else
    echo "[ERROR] Ollama daemon is not running on localhost:11434. Exiting."
    exit 1
fi

# 2. Activate the standard Python virtual environment
ENV_NAME=${1:-venv}
if [ -f "$ENV_NAME/bin/activate" ]; then
    source "$ENV_NAME/bin/activate"
    echo "[OK] Activated virtual environment: $ENV_NAME"
else
    echo "[ERROR] Virtual environment '$ENV_NAME' not found in $DIR!"
    exit 1
fi

# 3. Execute the crawler
python main.py

# 4. Cleanup
deactivate
echo "Pipeline execution finished."