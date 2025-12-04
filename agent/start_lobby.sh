#!/bin/bash

# Secure P2P Mafia Game - Lobby Launcher
# This script starts the AI Agent Lobby Server

echo "================================================"
echo "  Secure P2P Mafia Game - Agent Lobby"
echo "  Starting Spawner Server..."
echo "================================================"
echo ""

# Check Python version
python_version=$(python --version 2>&1 | awk '{print $2}')
echo "Python version: $python_version"
echo ""

# Check if dependencies are installed
echo "Checking dependencies..."
if ! python -c "import fastapi" 2>/dev/null; then
    echo "❌ FastAPI not found. Installing dependencies..."
    pip install -r requirements.txt
fi

echo "✓ Dependencies OK"
echo ""

# Start lobby server
echo "Starting Agent Lobby on port 8000..."
echo "Press Ctrl+C to stop"
echo ""

python lobby.py
