#!/bin/bash

# Secure P2P Mafia Game - Game Launcher
# This script starts the Host Engine + Human Player

echo "================================================"
echo "  Secure P2P Mafia Game"
echo "  Threshold FHE + DKG Edition"
echo "================================================"
echo ""

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
    echo "✓ Virtual environment activated"
else
    echo "❌ Virtual environment not found. Creating..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
fi

# Check Python version
python_version=$(python --version 2>&1 | awk '{print $2}')
echo "Python version: $python_version"
echo ""

# Check if dependencies are installed
echo "Checking dependencies..."
if ! python -c "import openfhe" 2>/dev/null; then
    echo "❌ OpenFHE not found. Installing dependencies..."
    pip install -r requirements.txt
fi

echo "✓ Dependencies OK"
echo ""

# Check if lobby is running
echo "Checking if Agent Lobby is running..."
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✓ Agent Lobby is running"
else
    echo "⚠️  WARNING: Agent Lobby not detected at http://localhost:8000"
    echo "   Please start the lobby first:"
    echo "   cd ../agent && bash start_lobby.sh"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "Starting Game Host..."
echo ""

python app.py
