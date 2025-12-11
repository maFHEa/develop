#!/bin/bash

# Secure P2P Mafia Game - Full Setup & Launcher
# This script sets up venv, installs dependencies, and starts the game

set -e  # Exit on error

echo "================================================"
echo "  Secure P2P Mafia Game"
echo "  Full Setup & Launcher"
echo "================================================"
echo ""

# Check directories
if [ ! -d "agent" ] || [ ! -d "human" ]; then
    echo "Error: Please run this script from the project root directory"
    echo "Expected directories: agent/, human/"
    exit 1
fi

# Step 1: Create virtual environment if not exists
if [ ! -d "venv" ]; then
    echo "[1/5] Creating virtual environment..."
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "[1/5] Virtual environment already exists"
fi
echo ""

# Step 2: Activate virtual environment
echo "[2/5] Activating virtual environment..."
source venv/bin/activate
echo "✓ Virtual environment activated"
echo ""

# Step 3: Install/Update dependencies
echo "[3/5] Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "✓ All dependencies installed"
echo ""

# Store PIDs for cleanup
LOBBY_PIDS=()

# Cleanup function
cleanup() {
    echo ""
    echo "Shutting down..."
    for pid in "${LOBBY_PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            echo "Stopped lobby (PID: $pid)"
        fi
    done
    exit 0
}

# Set trap for cleanup
trap cleanup SIGINT SIGTERM

# Step 4: Create logs directory
mkdir -p logs

# Start 5 lobby servers
echo "[4/5] Starting 5 Agent Lobbies..."
echo ""

for i in 0 1 2 3 4; do
    PORT=$((8000 + i))
    echo "  → Starting Lobby $i on port $PORT..."

    cd agent
    python lobby.py --port $PORT > ../logs/lobby_$PORT.log 2>&1 &
    LOBBY_PIDS+=($!)
    cd ..

    sleep 0.5
done

echo "✓ All lobbies started"
echo ""

echo "[5/5] Waiting for lobbies to initialize..."
sleep 2

# Check if lobbies are running
echo ""
echo "Checking lobby status..."
ALL_OK=true
for i in 0 1 2 3 4; do
    PORT=$((8000 + i))
    if curl -s "http://localhost:$PORT/health" > /dev/null 2>&1; then
        echo "  [OK] Lobby $i (port $PORT)"
    else
        echo "  [FAIL] Lobby $i (port $PORT)"
        ALL_OK=false
    fi
done

if [ "$ALL_OK" = false ]; then
    echo ""
    echo "Warning: Some lobbies failed to start"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        cleanup
    fi
fi

echo ""
echo "================================================"
echo "  All systems ready!"
echo "  Starting Game Host..."
echo "  Press Ctrl+C to stop all processes"
echo "================================================"
echo ""
echo "Lobby servers available at:"
echo "  - http://localhost:8000"
echo "  - http://localhost:8001"
echo "  - http://localhost:8002"
echo "  - http://localhost:8003"
echo "  - http://localhost:8004"
echo ""
echo "Logs saved in: logs/lobby_*.log"
echo ""

# Start game host (foreground)
cd human
python app.py

# Cleanup when game exits
cleanup
