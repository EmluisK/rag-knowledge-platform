#!/bin/bash
# Pull the Ollama model required for this project

MODEL="llama3.2:3b"

echo "── Ollama Model Setup ───────────────────────────────────"

# Check ollama is installed
if ! command -v ollama &> /dev/null; then
 echo " ollama not found. Install from https://ollama.com"
 exit 1
fi

# Check if serve is running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
 echo " ollama serve is not running."
 echo " Start it in a separate terminal: ollama serve"
 echo ""
 echo " Then re-run this script."
 exit 1
fi

echo " ollama is running"
echo " Pulling $MODEL (~2.5GB, may take a few minutes)..."
echo ""

ollama pull $MODEL

echo ""
echo " Model ready: $MODEL"
echo ""
echo "Next steps:"
echo " 1. make up — start all Docker services"
echo " 2. make scrape — scrape Cloudflare docs"
echo " 3. make ingest — trigger Airflow DAG"
echo " 4. make query — launch interactive CLI"
