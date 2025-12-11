#!/bin/bash
# Secure Mafia Game Launcher
# Starts 4 agent lobby servers and the human host

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}   Secure Mafia Game Launcher${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo ""

# Activate virtual environment
echo -e "${YELLOW}[1/6] Activating virtual environment...${NC}"
source venv/bin/activate
echo -e "${GREEN}✓ Virtual environment activated${NC}"
echo ""

# Check if ports are already in use
echo -e "${YELLOW}[2/6] Checking ports availability...${NC}"
for port in 8000 8001 8002 8003 8004; do
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo -e "${RED}✗ Port $port is already in use!${NC}"
        echo -e "${YELLOW}  Kill the process using: kill \$(lsof -ti:$port)${NC}"
        exit 1
    fi
done
echo -e "${GREEN}✓ All ports (8000-8004) are available${NC}"
echo ""

# Function to cleanup background processes on exit
cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down lobby servers...${NC}"
    kill $PID1 $PID2 $PID3 $PID4 $PID5 2>/dev/null || true
    echo -e "${GREEN}✓ All lobby servers stopped${NC}"
}
trap cleanup EXIT INT TERM

# Start Agent Lobby servers
echo -e "${YELLOW}[3/6] Starting Agent Lobby servers...${NC}"

# Create logs directory if it doesn't exist
mkdir -p logs

cd agent

python lobby.py --port 8000 > ../logs/lobby_8000.log 2>&1 &
PID1=$!
echo -e "${GREEN}✓ Lobby 1 started on port 8000 (PID: $PID1)${NC}"

python lobby.py --port 8001 > ../logs/lobby_8001.log 2>&1 &
PID2=$!
echo -e "${GREEN}✓ Lobby 2 started on port 8001 (PID: $PID2)${NC}"

python lobby.py --port 8002 > ../logs/lobby_8002.log 2>&1 &
PID3=$!
echo -e "${GREEN}✓ Lobby 3 started on port 8002 (PID: $PID3)${NC}"

python lobby.py --port 8003 > ../logs/lobby_8003.log 2>&1 &
PID4=$!
echo -e "${GREEN}✓ Lobby 4 started on port 8003 (PID: $PID4)${NC}"

python lobby.py --port 8004 > ../logs/lobby_8004.log 2>&1 &
PID5=$!
echo -e "${GREEN}✓ Lobby 5 started on port 8004 (PID: $PID5)${NC}"

cd ..
echo ""

# Wait for servers to start
echo -e "${YELLOW}[4/6] Waiting for lobby servers to initialize...${NC}"
sleep 2

# Check if all servers are running
echo -e "${YELLOW}[5/6] Verifying lobby servers...${NC}"
all_running=true
for pid in $PID1 $PID2 $PID3 $PID4 $PID5; do
    if ! kill -0 $pid 2>/dev/null; then
        echo -e "${RED}✗ Lobby server (PID: $pid) failed to start${NC}"
        all_running=false
    fi
done

if [ "$all_running" = false ]; then
    echo -e "${RED}Some lobby servers failed to start. Check logs in logs/ directory${NC}"
    exit 1
fi
echo -e "${GREEN}✓ All lobby servers are running${NC}"
echo ""

# Start Human Host with TUI
echo -e "${YELLOW}[6/6] Starting Human Host (TUI app.py)...${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}   Game is starting!${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo ""
echo -e "${GREEN}Lobby servers available at:${NC}"
echo -e "  - http://localhost:8000"
echo -e "  - http://localhost:8001"
echo -e "  - http://localhost:8002"
echo -e "  - http://localhost:8003"
echo -e "  - http://localhost:8004"
echo ""
echo -e "${YELLOW}Logs are saved in: logs/lobby_*.log${NC}"
echo ""

cd human
python app.py

# Cleanup will be called automatically on exit