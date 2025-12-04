# Secure P2P Mafia Game with Homomorphic Encryption

A cryptographically secure implementation of the Mafia social deduction game using **Homomorphic Encryption (TenSEAL)** and **AI Agents (OpenAI)**.

## 🔐 Core Security Features

### Homomorphic Encryption (BFV Scheme)
- **Blind Computation**: The game engine aggregates encrypted actions without ever seeing individual player choices
- **Secret Key Management**: Only the host holds the secret key, acting as a Trusted Execution Environment
- **Parameters**: 
  - Scheme: BFV (Fan-Vercauteren)
  - Polynomial Modulus Degree: 8192 (enables multiplication depth for complex operations)
  - Plain Modulus: 1032193

### Uniform Action Protocol (Anti-Traffic-Analysis)
- **Critical Security Requirement**: EVERY player sends identical-sized encrypted packets every turn
- **Dummy Data**: Players with no action (e.g., Citizens at night) send encrypted zero vectors
- **Prevention**: Eliminates network traffic analysis attacks that could reveal player roles

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    HUMAN HOST SYSTEM                        │
│  ┌────────────────────────────────────────────────────┐     │
│  │  Game Engine (Server)                              │     │
│  │  - Aggregates encrypted vectors blindly            │     │
│  │  - Computes:Enc(Killed) = Enc(Attack)*(1-Enc(Heal))│     │
│  │  - Decrypts ONLY final results                     │     │
│  └────────────────────────────────────────────────────┘     │
│  ┌────────────────────────────────────────────────────┐     │
│  │  Human Player Interface                            │     │
│  │  - Participates as Player 0                        │     │
│  │  - Encrypts own actions locally                    │     │
│  └────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ P2P Network
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
┌───────▼────────┐  ┌───────▼────────┐  ┌──────▼─────────┐
│  AI Agent 1    │  │  AI Agent 2    │  │  AI Agent N    │
│                │  │                │  │                │
│ - OpenAI LLM   │  │ - OpenAI LLM   │  │ - OpenAI LLM   │
│ - Autonomous   │  │ - Autonomous   │  │ - Autonomous   │
│ - Encrypts     │  │ - Encrypts     │  │ - Encrypts     │
│   locally      │  │   locally      │  │   locally      │
└────────────────┘  └────────────────┘  └────────────────┘
```

## 📁 Directory Structure

```
mafia/
│
├── agent/                      # AI Agent System
│   ├── lobby.py               # Spawner server (FastAPI)
│   ├── player.py              # Autonomous AI agent instance
│   ├── security.py            # HE & serialization utilities
│   └── requirements.txt       # Agent dependencies
│
├── human/                     # Human Host System
│   ├── main.py               # Game engine + human player
│   ├── config.py             # Game configuration
│   └── requirements.txt      # Host dependencies
│
└── README.md                 # This file
```

## 🎮 Game Roles

- **Mafia**: Eliminate citizens at night
- **Doctor**: Save one player from death each night
- **Police**: Investigate one player each night (learns if Mafia)
- **Citizen**: No night action, participates in voting

## 🚀 Setup & Installation

### Prerequisites
- Python 3.8+
- OpenAI API Key
- Linux/macOS (Windows may require WSL for TenSEAL)

### Installation

1. **Install Agent Dependencies**
```bash
cd agent
pip install -r requirements.txt
```

2. **Install Host Dependencies**
```bash
cd human
pip install -r requirements.txt
```

### Important: TenSEAL Installation

TenSEAL may require compilation. If you encounter issues:

```bash
# Install build dependencies (Ubuntu/Debian)
sudo apt-get install build-essential cmake

# Or use pre-built wheel (if available for your platform)
pip install tenseal --find-links https://github.com/OpenMined/TenSEAL/releases
```

## 🎯 How to Run

### Step 1: Start the Agent Lobby (Terminal 1)

```bash
cd agent
python lobby.py
```

This starts the spawner server on port 8000. It waits for spawn requests.

### Step 2: Run the Game (Terminal 2)

```bash
cd human
python main.py
```

You'll be prompted for:
1. **OpenAI API Key**: Your API key for AI agents
2. **Number of AI Agents**: Choose 3-9 AI opponents

The system will:
1. Spawn AI agents via the lobby
2. Create homomorphic encryption context
3. Distribute encrypted roles
4. Start the game loop

### Step 3: Play!

- **Night Phase**: You'll be prompted to choose a target (if your role allows)
- **Day Phase**: Discussion (press Enter to continue)
- **Vote Phase**: Choose who to eliminate

## 🔬 Cryptographic Operations

### Night Phase Computation

```python
# All operations done on encrypted data
Enc(Net_Attack) = Sum(Enc(Mafia_Action_i))
Enc(Net_Heal) = Sum(Enc(Doctor_Action_i))
Enc(Is_Killed) = Enc(Net_Attack) * (1 - Enc(Net_Heal))

# ONLY the final result is decrypted
Killed = Decrypt(Enc(Is_Killed))
```

### Police Investigation

```python
# Dot product on encrypted data
Enc(Target_Query) = [0, 0, 1, 0, 0]  # One-hot vector
Enc(Role_Vector) = [0, 1, 0, 1, 0]    # 1=Mafia, 0=Other

Enc(Result) = Enc(Target_Query) ⊙ Enc(Role_Vector)
Is_Mafia = Decrypt(Enc(Result))
```

### Traffic Analysis Defense

```python
# EVERY player sends data every turn
if can_act:
    send(Encrypt([0, 0, 1, 0]))  # Real action
else:
    send(Encrypt([0, 0, 0, 0]))  # Dummy packet

# Network observer CANNOT distinguish roles
```

## 🛠️ Technical Implementation

### Key Components

1. **security.py**: Core cryptographic functions
   - `create_tenseal_context()`: Initialize BFV context
   - `create_one_hot_vector()`: Encrypt target selection
   - `create_zero_vector()`: Generate dummy traffic
   - `aggregate_encrypted_vectors()`: Homomorphic addition
   - `compute_killed_vector()`: Homomorphic multiplication

2. **player.py**: AI Agent
   - Uses OpenAI GPT-4 for decision-making
   - Maintains conversation thread
   - Implements `execute_night_action()` tool
   - Autonomous target selection

3. **main.py**: Game Engine
   - Manages game state machine
   - Collects encrypted actions
   - Performs blind aggregation
   - Decrypts only final results

## 🔒 Security Guarantees

### What the Host CANNOT See
- ❌ Individual player actions
- ❌ Who attacked whom
- ❌ Who healed whom
- ❌ Specific votes before aggregation

### What the Host CAN See
- ✅ Aggregated results (who died)
- ✅ Vote counts (after aggregation)
- ✅ Game state (alive/dead players)

### Threat Model
- **Honest-but-Curious Server**: The host follows the protocol but might try to extract information
- **Network Observer**: Cannot infer roles from traffic patterns (Uniform Action Protocol)
- **Malicious Players**: Cannot forge or tamper with encrypted data without detection

## 🧪 Testing

### Manual Test
```bash
# Terminal 1
cd agent && python lobby.py

# Terminal 2
cd human && python main.py
# Enter test API key and spawn 3 agents
```

### Security Test
Check that all players send data:
```python
# In main.py, add logging:
print(f"[DEBUG] Received {len(encrypted_actions)} encrypted packets")
# Should always equal num_players
```

## 📊 Game Configuration

Edit `human/config.py`:

```python
GAME_CONFIG = {
    "min_players": 4,
    "max_players": 10,
    "role_distribution": {
        4: {"mafia": 1, "doctor": 1, "police": 1, "citizen": 1},
        # ... customize role ratios
    },
    "night_phase_timeout": 60,  # seconds
    "vote_phase_timeout": 60,
}
```

## 🐛 Troubleshooting

### TenSEAL Installation Fails
```bash
# Try building from source
git clone https://github.com/OpenMined/TenSEAL.git
cd TenSEAL
pip install .
```

### Agent Connection Timeout
- Increase `connection_timeout` in `config.py`
- Check firewall settings for localhost connections

### OpenAI Rate Limits
- Use smaller number of agents
- Add delays between API calls in `player.py`

## 📚 References

- **TenSEAL**: https://github.com/OpenMined/TenSEAL
- **BFV Scheme**: Fan & Vercauteren (2012) - Somewhat Practical Fully Homomorphic Encryption
- **OpenAI Agents**: https://platform.openai.com/docs/guides/agents
- **Mafia Game**: https://en.wikipedia.org/wiki/Mafia_(party_game)

## 🎓 Learning Objectives

This project demonstrates:
1. **Secure Multi-Party Computation (SMPC)** in practice
2. **Homomorphic Encryption** for blind computation
3. **Traffic Analysis Resistance** via uniform protocols
4. **AI Agent Orchestration** with stateful LLMs
5. **P2P Game Architecture** with cryptographic security

## 📜 License

MIT License - Educational purposes only

## 🙏 Acknowledgments

Built with:
- TenSEAL (OpenMined Foundation)
- OpenAI GPT-4
- FastAPI
- Python asyncio

---

**Security Notice**: This is an educational implementation. For production use, add:
- Formal security audit
- Network layer encryption (TLS)
- Authentication & authorization
- Byzantine fault tolerance
- Verifiable computation proofs
