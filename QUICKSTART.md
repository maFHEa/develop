# 🎮 Secure Mafia Game - 실행 가이드

## 📋 사전 준비

### 1. 의존성 설치

```bash
# Agent 의존성 설치
cd /home/rocknroll1397/mafia/agent
pip install -r requirements.txt

# Human Host 의존성 설치
cd /home/rocknroll1397/mafia/human
pip install -r requirements.txt
```

### 2. OpenAI API Key 준비
- OpenAI API 키가 필요합니다
- https://platform.openai.com/api-keys 에서 발급

---

## 🚀 게임 실행 방법

### 아키텍처 개요
- **각 게임 세션마다 독립적인 Agent 서버 1개**
- Human Host가 시작 시 Agent 서버 주소 리스트를 입력
- 여러 게임을 동시에 진행하려면 각각 다른 포트에 Agent 서버를 띄움

---

### 방법 1: Lobby를 통해 Agent Spawn (권장)

#### Step 1: 필요한 만큼 Lobby 서버들을 띄우기

```bash
# Lobby 1 - 게임 1용
cd /home/rocknroll1397/mafia/agent
python lobby.py --port 8000

# Lobby 2 - 게임 2용 (다른 터미널)
python lobby.py --port 8100

# Lobby 3 - 게임 3용 (다른 터미널)
python lobby.py --port 8200
```

**출력 예시:**
```
[Lobby] Starting Agent Lobby Server on port 8000...
[Lobby] Ready to spawn AI agents on demand
INFO:     Uvicorn running on http://0.0.0.0:8000
```

#### Step 2: 각 Lobby에서 Agent Spawn

```bash
# Lobby 1에서 Agent 생성
curl -X POST http://localhost:8000/spawn_agent \
  -H "Content-Type: application/json" \
  -d '{"openai_api_key": "YOUR_API_KEY", "game_session_id": "game1"}'

# 응답 예시:
# {"agent_id":1,"address":"http://localhost:8001","port":8001}
```

또는 Python으로:
```python
import httpx
response = httpx.post(
    "http://localhost:8000/spawn_agent",
    json={"openai_api_key": "sk-...", "game_session_id": "game1"}
)
print(response.json())  # {"address": "http://localhost:8001", ...}
```

#### Step 3: Human Host 시작 및 Agent 주소 입력

```bash
cd /home/rocknroll1397/mafia/human
python main.py
```

**대화형 설정:**
```
AGENT CONFIGURATION
Enter AI agent server addresses (one per line).
Each agent should be a separate server running on different ports.
Example: http://localhost:8001
Press Enter on an empty line when done.
Min agents: 3, Max agents: 9

Agent #1 address (or Enter to finish): http://localhost:8001
[Setup] Checking connection to http://localhost:8001...
[Setup] ✓ Agent #1 connected

Agent #2 address (or Enter to finish): http://localhost:8002
[Setup] ✓ Agent #2 connected

Agent #3 address (or Enter to finish): http://localhost:8003
[Setup] ✓ Agent #3 connected

Agent #4 address (or Enter to finish): [Enter로 완료]

[Setup] Configured 3 AI agents
```

---

### 방법 2: Agent를 직접 실행 (고급)

여러 터미널에서 Agent를 직접 띄우기:

```bash
# Terminal 1 - Agent 1
cd /home/rocknroll1397/mafia/agent
python player.py --port 8001 --api-key YOUR_OPENAI_KEY --agent-id 1

# Terminal 2 - Agent 2
python player.py --port 8002 --api-key YOUR_OPENAI_KEY --agent-id 2

# Terminal 3 - Agent 3
python player.py --port 8003 --api-key YOUR_OPENAI_KEY --agent-id 3
```

그 다음 Human Host에서 위와 동일하게 주소 입력.

---

## 🎯 전체 실행 예시 (4명 게임)

### 시나리오: 3개의 Agent + 1명의 Human

```bash
# === Terminal 1: Lobby ===
cd /home/rocknroll1397/mafia/agent
python lobby.py --port 8000

# === Terminal 2-4: Spawn Agents (또는 API 호출) ===
# 방법 A: curl로 spawn
curl -X POST http://localhost:8000/spawn_agent \
  -H "Content-Type: application/json" \
  -d '{"openai_api_key": "sk-YOUR-KEY"}'
# → Agent 8001에 생성됨

curl -X POST http://localhost:8000/spawn_agent \
  -H "Content-Type: application/json" \
  -d '{"openai_api_key": "sk-YOUR-KEY"}'
# → Agent 8002에 생성됨

curl -X POST http://localhost:8000/spawn_agent \
  -H "Content-Type: application/json" \
  -d '{"openai_api_key": "sk-YOUR-KEY"}'
# → Agent 8003에 생성됨

# === Terminal 5: Human Host ===
cd /home/rocknroll1397/mafia/human
python main.py

# 입력:
# Agent #1: http://localhost:8001
# Agent #2: http://localhost:8002
# Agent #3: http://localhost:8003
# [Enter]
```

---

## 🎯 게임 플레이 흐름

### 게임 초기화
```
1. Host가 AI Agent들을 Lobby를 통해 생성
2. 각 Agent에게 역할(Mafia/Doctor/Police/Citizen) 암호화 전송
3. 모든 플레이어가 준비되면 게임 시작
```

### Night Phase (밤)
```
1. Host: "Night Phase" 메시지 브로드캐스트
2. 각 Agent: 
   - view_new_chat_messages() 호출하여 새 메시지 확인
   - get_game_status() 로 상태 확인
   - submit_night_action(target_index) 로 행동 제출
3. Human Player: 터미널에서 타겟 선택
4. Host: 암호화된 액션 집계 → 결과 계산 (누가 죽었는지)
```

### Day Phase (낮)
```
1. Host: 밤 결과 발표 (누가 죽었는지)
2. Players: 자유 토론 시간 (Press Enter to continue)
3. AI Agents: send_chat_message() 로 메시지 전송 가능
```

### Vote Phase (투표)
```
1. Host: "Vote Phase" 시작
2. 각 Agent:
   - view_new_chat_messages() 로 토론 내용 확인
   - view_phase_history('day') 로 낮 대화 분석
   - submit_vote(target_index) 로 투표
3. Human Player: 터미널에서 투표
4. Host: 암호화된 투표 집계 → 최다 득표자 제거
```

### Win Condition Check
```
- Mafia 전멸 → Citizens 승리
- Mafia 수 >= Citizen 수 → Mafia 승리
```

---

## 🤖 AI Agent 작동 방식

### Function Tools
각 AI Agent는 다음 tools를 사용할 수 있습니다:

#### 1. **view_new_chat_messages()**
- 마지막 확인 이후 **새로운 메시지만** 보여줌
- 자동으로 읽음 처리 (last_read_msg_id 업데이트)

#### 2. **view_chat_from_position(from_msg_id, limit)**
- 특정 메시지 ID부터 읽기
- 이전 대화 재검토 가능

#### 3. **get_chat_reading_status()**
- 현재까지 읽은 위치 확인
- 안 읽은 메시지 수 확인

#### 4. **view_phase_history(phase)**
- 특정 phase의 모든 대화 조회
- 예: "day" phase 대화만 필터링

#### 5. **get_game_status()**
- 현재 phase, 역할, 생존 상태 등

#### 6. **send_chat_message(message)**
- 다른 플레이어에게 메시지 전송

#### 7. **submit_night_action(target_index)** ⚠️ REQUIRED
- Night phase에서 필수 호출
- Citizen은 -1 전송

#### 8. **submit_vote(target_index)** ⚠️ REQUIRED
- Vote phase에서 필수 호출
- 투표 거부는 -1

### 대화 추적 메커니즘

```python
# Agent 내부 상태
state.last_read_msg_id = -1  # 마지막으로 읽은 메시지 ID

# 새 메시지 조회
view_new_chat_messages()  
# → ID 5, 6, 7 반환 + last_read_msg_id = 7로 업데이트

# 다시 호출하면?
view_new_chat_messages()  
# → "No new chat messages" (이미 읽음)

# 이전 대화 재검토
view_chat_from_position(from_msg_id=0, limit=10)
# → 처음 10개 메시지 조회 (읽음 상태는 변경 안 됨)
```

---

## 🔐 보안 특징

### Homomorphic Encryption
```
- 모든 게임 액션은 암호화되어 전송
- Host는 개별 액션을 볼 수 없음
- 집계된 결과만 복호화
```

### Uniform Action Protocol
```
- 모든 플레이어가 매 phase마다 데이터 전송
- 역할 없는 플레이어도 zero vector 전송
- 네트워크 트래픽 분석 방지
```

---

## 📊 예제 실행 시나리오

### 4명 플레이어 게임

**역할 분배:**
- Player 0 (Human): Mafia
- Player 1 (AI): Doctor
- Player 2 (AI): Police
- Player 3 (AI): Citizen

**Night 1:**
```
[Engine] Night 1 has begun
[Agent 1] Running autonomous decision-making...
[Agent 1] Calling: view_new_chat_messages()
[Agent 1] Calling: get_game_status()
[Agent 1] Calling: submit_night_action(0)  # Protect Player 0
[Agent 2] Calling: submit_night_action(1)  # Investigate Player 1
[Agent 3] Calling: submit_night_action(-1) # Citizen, no action

[You] Your turn - NIGHT PHASE
[You] Your Role: MAFIA
[You] Valid targets: [1, 2, 3]
Enter player index to target: 3

[Engine] Computing blind aggregation...
[Engine] Player 3 was killed during the night!
```

**Day 1:**
```
[Agent 2] Calling: send_chat_message("I think Player 1 is suspicious")
[You can send message or press Enter to proceed to voting]
```

**Vote 1:**
```
[Agent 1] Calling: view_new_chat_messages()
[Agent 1] Calling: view_phase_history('day')
[Agent 1] Calling: submit_vote(2)  # Vote Player 2

[You] Enter player index to vote for: 2
[Engine] Player 2 eliminated with 2 votes
```

---

## 🐛 트러블슈팅

### 1. "Failed to spawn agent"
```bash
# Lobby가 실행 중인지 확인
curl http://localhost:8000/health

# 포트 충돌 확인
netstat -tulpn | grep 800
```

### 2. "Agent did not submit action"
```
Agent가 submit_night_action() 또는 submit_vote()를 호출하지 않음
→ max_turns를 늘리거나 instructions 수정
```

### 3. TenSEAL 설치 실패
```bash
# 빌드 도구 설치
sudo apt-get install build-essential cmake

# 또는 미리 빌드된 wheel 사용
pip install tenseal --find-links https://github.com/OpenMined/TenSEAL/releases
```

### 4. OpenAI API Rate Limit
```
→ Agent 수를 줄이거나
→ time.sleep() 추가하여 요청 속도 조절
```

---

## 📈 성능 최적화

### Agent 응답 시간
```python
# player.py에서 조정 가능
result = await Runner.run(
    starting_agent=state.agent,
    input=messages,
    max_turns=15  # 줄이면 빨라지지만 판단력 감소
)
```

### 대화 히스토리 제한
```python
# 메시지 제한으로 context 크기 감소
view_chat_from_position(from_msg_id=50, limit=30)
```

---

## 🎓 고급 사용법

### 커스텀 역할 분배
```python
# human/config.py 수정
"role_distribution": {
    4: {"mafia": 2, "doctor": 1, "police": 0, "citizen": 1},  # Mafia 우세
}
```

### Agent 전략 수정
```python
# agent/player.py의 create_mafia_agent() 함수에서
# role_instructions 수정
```

### 타임아웃 조정
```python
# human/config.py
GAME_CONFIG = {
    "night_phase_timeout": 120,  # 2분
    "vote_phase_timeout": 180,   # 3분
}
```

---

## 📝 로그 확인

### Agent 로그
```
[Agent 1] Running autonomous decision-making...
[Agent 1] Decision: Target=2, Reasoning=...
[Agent 1] Agent response: I've submitted my action
```

### Host 로그
```
[Engine] Collecting encrypted actions from all players...
[Engine] Computing blind aggregation (no individual decryption)...
[Engine] Decrypting aggregated result...
[Engine] Player 3 was killed during the night!
```

---

## 🎉 게임 종료

```
GAME OVER - CITIZENS WIN!

FINAL ROLES:
  Player 0 (Human): MAFIA - DEAD
  Player 1 (AI Agent 1): DOCTOR - ALIVE
  Player 2 (AI Agent 2): POLICE - DEAD
  Player 3 (AI Agent 3): CITIZEN - ALIVE

Game ended: citizens win!
```

---

## 🔗 참고 자료

- **OpenAI Agents SDK**: https://github.com/openai/openai-agents-python
- **TenSEAL**: https://github.com/OpenMined/TenSEAL
- **Mafia Rules**: https://en.wikipedia.org/wiki/Mafia_(party_game)

---

## 📧 문제 보고

이슈 발생 시:
1. 터미널 로그 캡처
2. OpenAI API 사용량 확인
3. 네트워크 연결 상태 확인
