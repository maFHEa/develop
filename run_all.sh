#!/bin/bash

# Secure P2P Mafia Game - Full Launcher
# This script starts 4 lobbies + the game host

echo "================================================"
echo "  Secure P2P Mafia Game"
echo "  Full Game Launcher"
echo "================================================"
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

# Check directories
if [ ! -d "agent" ] || [ ! -d "human" ]; then
    echo "Error: Please run this script from the project root directory"
    echo "Expected directories: agent/, human/"
    exit 1
fi

# Start 4 lobby servers
echo "Starting 4 Agent Lobbies..."
echo ""

for i in 0 1 2 3; do
    PORT=$((8000 + i))
    echo "Starting Lobby $i on port $PORT..."

    cd agent
    source venv/bin/activate 2>/dev/null || true
    python lobby.py --port $PORT > /dev/null 2>&1 &
    LOBBY_PIDS+=($!)
    cd ..

    sleep 0.5
done

echo ""
echo "Waiting for lobbies to initialize..."
sleep 2

# Check if lobbies are running
echo ""
echo "Checking lobby status..."
ALL_OK=true
for i in 0 1 2 3; do
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
echo "  Starting Game Host..."
echo "  Press Ctrl+C to stop all processes"
echo "================================================"
echo ""

# Start game host (foreground)
cd human
source venv/bin/activate 2>/dev/null || true
python app.py

# Cleanup when game exits
cleanup
