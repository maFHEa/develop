#!/usr/bin/env python3
"""Convenience launcher that starts four lobby servers and runs start_game.sh."""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
import signal
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent
AGENT_DIR = ROOT / "agent"
HUMAN_DIR = ROOT / "human"
AGENT_PYTHON = AGENT_DIR / "venv" / "bin" / "python"
START_GAME_SCRIPT = HUMAN_DIR / "start_game.sh"
LOBBY_PORTS: List[int] = [8000, 8001, 8002, 8003]
HEALTH_TIMEOUT = 30  # seconds to wait for each lobby


def ensure_prerequisites() -> None:
    """Validate that required files exist before running anything."""
    missing = []
    if not AGENT_PYTHON.exists():
        missing.append(str(AGENT_PYTHON))
    if not (AGENT_DIR / "lobby.py").exists():
        missing.append(str(AGENT_DIR / "lobby.py"))
    if not START_GAME_SCRIPT.exists():
        missing.append(str(START_GAME_SCRIPT))

    if missing:
        message = "Missing required files:\n" + "\n".join(f" - {path}" for path in missing)
        raise FileNotFoundError(message)


def start_lobby(port: int) -> Tuple[subprocess.Popen, object]:
    """Launch a single lobby process on the requested port."""
    log_path = AGENT_DIR / f"lobby_{port}.log"
    log_handle = log_path.open("w")
    proc = subprocess.Popen(
        [str(AGENT_PYTHON), "lobby.py", "--port", str(port)],
        cwd=str(AGENT_DIR),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    return proc, log_handle


def wait_for_lobby(port: int) -> bool:
    """Poll the lobby health endpoint until it responds or timeout."""
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + HEALTH_TIMEOUT
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, urllib.error.HTTPError):
            pass
        time.sleep(1)
    return False


def stop_process(proc: subprocess.Popen) -> None:
    """Terminate a spawned process cleanly."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def run_start_game() -> int:
    """Launch the human/start_game.sh script and wait for it to finish."""
    print("[TestGame] Launching start_game.sh (press Ctrl+C to abort)...")
    proc = subprocess.Popen(["bash", str(START_GAME_SCRIPT)], cwd=str(HUMAN_DIR))
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.send_signal(signal.SIGINT)
        raise


def main() -> int:
    ensure_prerequisites()

    lobby_processes: List[subprocess.Popen] = []
    log_handles: List[object] = []

    try:
        for port in LOBBY_PORTS:
            print(f"[TestGame] Starting lobby on port {port}...")
            proc, log_handle = start_lobby(port)
            lobby_processes.append(proc)
            log_handles.append(log_handle)

            if not wait_for_lobby(port):
                raise RuntimeError(f"Lobby on port {port} failed to start in time")
            print(f"[TestGame] Lobby {port} is healthy")

        print("[TestGame] All lobbies ready. Running the game launcher now.\n")
        result = run_start_game()
        if result == 0:
            print("[TestGame] Game finished successfully.")
        else:
            print(f"[TestGame] start_game.sh exited with status {result}.")
        return result

    except KeyboardInterrupt:
        print("\n[TestGame] Interrupted by user. Shutting down...")
        return 1
    finally:
        for proc in lobby_processes:
            stop_process(proc)
        for handle in log_handles:
            try:
                handle.close()
            except Exception:
                pass
        print("[TestGame] Lobby processes terminated.")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FileNotFoundError as exc:
        print(f"[TestGame] {exc}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as exc:
        print(f"[TestGame] {exc}", file=sys.stderr)
        sys.exit(1)
