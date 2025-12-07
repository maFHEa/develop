# 🤖 Mafia AI Agent 시스템 완벽 가이드

## 📋 목차
1. [전체 구조](#전체-구조)
2. [Phase별 Tools & Prompts](#phase별-tools--prompts)
3. [역할별 차이점](#역할별-차이점)
4. [성격 시스템](#성격-시스템)
5. [AI 호출 흐름](#ai-호출-흐름)

---

## 🏗️ 전체 구조

### Agent 생성 (`create_mafia_agent`)
```python
Agent(
    name=f"MafiaPlayer{player_index}",
    instructions=instructions,  # 역할 + 성격 + 금지사항
    tools=create_agent_tools(state, phase),  # Phase별 동적 변경
    model="gpt-4o-mini"
)
```

**핵심 원칙:**
- 각 에이전트는 **고유한 성격**을 가짐 (게임 ID + 플레이어 인덱스 기반 시드)
- Tools는 **Phase별로 동적 변경** (setup → chat → night → vote)
- 모든 에이전트는 **OpenAI Conversations**로 대화 기록 유지

---

## 🎮 Phase별 Tools & Prompts

### 1️⃣ **SETUP Phase** (게임 시작 전)

**제공 Tools:**
```python
- write_suspicion_note()    # 의심 메모 작성
- view_suspicion_notes()    # 메모 조회
```

**특징:**
- 아직 게임이 시작 안됨
- 역할 할당 대기 중
- 기본 tools만 제공

---

### 2️⃣ **CHAT Phase** (낮 토론)

**제공 Tools:** (가장 많음 - 10개)
```python
# 📬 대화 Tools
- read_chat_messages(start_id?)   # 새 메시지 읽기
- send_chat_message(message)      # 메시지 전송 (3초 딜레이)

# 📝 메모 Tools  
- write_suspicion_note(player_index, level, reasoning)
- view_suspicion_notes()

# 🧠 전략 분석 Tools
- analyze_player_behavior(player_index)     # 특정 플레이어 분석
- get_strategic_overview()                  # 전체 상황 분석
- record_observation(observation)           # 관찰 기록
- analyze_voting_patterns()                 # 투표 패턴 분석
- predict_next_target(perspective)          # 다음 타겟 예측
- detect_lies_and_contradictions(player_index)  # 모순 감지
```

**Prompt 구조:**
```
토론 시간 (Day {turn}) {시간 힌트}

생존: [랜덤 순서]
사망: [...]

{호스트 메시지}

{상황별 힌트}
- 첫날: "첫날이라 정보가 없어. 일단 분위기 봐."
- 사망자 발생: "밤사이 누가 죽었어. 반응해."
- 3명 이하: "몇 명 안 남았어. 신중하게."

할 일:
1. read_chat_messages() - 남들 뭐라 하는지 확인
2. 대화에 참여하거나 관찰
3. 의심되는 사람 있으면 말해도 되고 눈치봐도 됨

팁:
- 매번 말할 필요 없어. 할 말 있을 때만 해.
- 다른 사람 말에 반응해. 무시하면 이상해.
- 질문받으면 대답해.
```

**특징:**
- **백그라운드 루프**: 채팅이 계속 반복 (2초 간격)
- **시간 제한**: remaining_time 기반으로 종료
- **메시지 딜레이**: 최소 3초 간격 (사람처럼 보이도록)
- **자동 종료**: 시간 5초 미만이면 루프 종료

---

### 3️⃣ **NIGHT Phase** (밤 행동)

**제공 Tools:** (역할별로 다름)

#### 🔴 Mafia
```python
- mafia_kill(target_index)      # PRIMARY - 반드시 호출
- view_suspicion_notes()        # 메모 확인
- get_strategic_overview()      # 빠른 상황 파악
```

#### 💊 Doctor
```python
- doctor_heal(target_index)     # PRIMARY - 반드시 호출 (자기 자신 가능!)
- view_suspicion_notes()
- get_strategic_overview()
```

#### 🔍 Police
```python
- police_investigate(target_index)  # PRIMARY - 즉시 결과 반환!
- view_suspicion_notes()
- get_strategic_overview()
```

#### 👥 Citizen
```python
- (No tools)  # 아무것도 안함
```

**Prompt 구조:**
```
밤 단계 (Day {turn})

생존: [...]
사망: [...]

{호스트 메시지}

{역할별 힌트}
- Mafia: "누구 죽일지 골라. 뻔한 선택 말고 생각해봐."
- Doctor: "누구 살릴지 골라. 자기 자신도 가능."
- Police: "누구 조사할지 골라. 결과 바로 알려줌."

⚠️ 반드시 {action_tool}(숫자) 호출해야 함!
```

**특수 처리:**
- **Citizen**: AI 호출 안함, 1~2.5초 딜레이 후 자동 종료
- **Police**: `police_investigate()` 호출 시 **즉시 결과 반환** (서버에서 병렬 복호화)
- **모든 역할**: Dummy investigation packet 전송 (네트워크 obfuscation)

---

### 4️⃣ **VOTE Phase** (투표)

**제공 Tools:**
```python
- submit_vote(target_index)           # PRIMARY - 반드시 호출 (-1 = 기권)
- view_suspicion_notes()              # 메모 확인
- get_strategic_overview()            # 상황 파악
- analyze_player_behavior(player_index)  # 특정인 분석
```

**Prompt 구조:**
```
투표 단계 (Day {turn})

생존: [...]
사망: [...]

{호스트 메시지}

누가 마피아 같아? 투표해.

🧠 투표하기 전에:
1. 지금까지의 대화 내용을 떠올려봐
2. 경찰 조사 결과가 있었는지 생각해봐
3. 의심스러운 발언이나 행동이 있었는지 기억해봐
4. 투표 이유를 논리적으로 설명할 수 있어야 해

중요한 정보를 놓치지 마! 특히:
- 경찰이 마피아라고 밝힌 사람
- 변명이 이상했던 사람
- 투표 패턴이 수상한 사람

⚠️ 반드시 submit_vote(숫자) 호출해야 함!
```

**특징:**
- **대화 내용 강조**: 경찰 조사 결과, 의심 발언 등 기억하도록 유도
- **논리적 근거**: 투표 이유 설명 요구
- **기권 가능**: `submit_vote(-1)` 또는 None

---

## 👤 역할별 차이점

### 🔴 Mafia (마피아)

**Instructions 추가:**
```
=== 마피아 전용 ===
• 절대 티내지 마 - 자연스럽게 시민인 척 해
• 다른 사람 의심하면서 자연스럽게 물타기
• 너무 조용하면 의심받고, 너무 나서도 의심받음
• 밤에 죽인 사람 얘기 나오면 자연스럽게 반응해
• 다른 마피아 있으면 티 안나게 도와줘
```

**Night Action:**
- `mafia_kill(target_index)` → 암호화된 attack vector 생성
- 로그: `🔪 Mafia → P{target}`

**전략:**
- 시민인 척 적극 토론 참여
- 다른 사람 의심하며 어그로 분산
- 동료 마피아 보호 (티 안나게)

---

### 💊 Doctor (의사)

**Instructions 추가:**
```
=== 의사 전용 ===
• 역할 들키면 마피아한테 죽음 - 절대 비밀
• 누구 살렸는지도 비밀로 해
• 경찰처럼 확신있게 말하면 안됨
```

**Night Action:**
- `doctor_heal(target_index)` → 암호화된 heal vector 생성
- **자기 자신 치료 가능!** (중요)
- 로그: `💊 Doctor → P{target}` 또는 `💊 Doctor → SELF`

**전략:**
- 역할 숨기기
- 누가 죽을 것 같은지 예측해서 살림
- 자신이 위험하면 self-heal

---

### 🔍 Police (경찰)

**Instructions 추가:**
```
=== 경찰 전용 ===
• 조사 결과 바로 말하면 죽음 - 타이밍 중요
• 확실할 때만 조심스럽게 흘려
• 역할 들키지 않게 조심
```

**Night Action:**
- `police_investigate(target_index)` → **즉시 결과 반환!**
  ```
  ✅ Investigation Result:
  Player {target} is MAFIA / NOT MAFIA
  ```
- 결과는 `suspicion_notes`에 자동 기록 (변경 불가)
- 로그: `🔍 [P{index}] INVESTIGATE → P{target}`

**조사 프로토콜:**
1. 경찰이 `police_investigate()` 호출
2. 서버가 모든 플레이어에게 병렬로 partial decryption 요청
3. Fusion decrypt로 최종 결과 획득
4. 경찰 에이전트에게만 결과 반환

**전략:**
- 조사 결과 즉시 말하지 않기 (마피아에게 죽음)
- 타이밍 맞춰 조심스럽게 힌트
- 확실한 마피아 찾으면 투표 때 공개

---

### 👥 Citizen (시민)

**Instructions 추가:**
```
=== 시민 전용 ===
(별도 추가 없음)
```

**Night Action:**
- AI 호출 **안함**
- 1~2.5초 딜레이만 추가 (obfuscation)
- Zero vector 반환

**전략:**
- 토론으로 마피아 찾기
- 경찰/의사 보호
- 투표로만 기여 가능

---

## 🎭 성격 시스템

### 성격 생성 (`generate_personality`)

**시드 기반 일관성:**
```python
seed = hash(f"{game_id}_{player_index}")
# → 같은 게임에서 같은 플레이어는 항상 같은 성격
```

**4가지 성격 축:**

#### 1. Communication Style (의사소통 스타일)
```
- 직설적이고 단도직입적
- 조용하고 관찰하는 스타일
- 수다스럽고 활발함
- 논리적이고 분석적
- 감정적이고 직관적
- 냉소적이고 의심 많음
- 친근하고 사교적
- 신중하고 조심스러움
```

#### 2. Reaction Pattern (반응 패턴)
```
- 위기 상황에서 침착함
- 공격받으면 격하게 반응
- 유머로 상황을 넘기려 함
- 팩트 체크하며 반박
- 질문으로 되묻기
- 남 탓하며 회피
```

#### 3. Speech Habit (말버릇)
```
- 말 끝을 흐림 (...)
- 강조어 많이 씀 (진짜, 마, 완전)
- 이모티콘/ㅋㅋ 자주 씀
- 반어법 즐겨 씀
- 짧게 끊어서 말함
- 한 번에 길게 말함
```

#### 4. Strategic Tendency (전략 성향)
```
- 적극적으로 의심하고 몰아붙임
- 수비적으로 살피다가 확신 있을 때만 발언
- 동맹을 만들려고 시도
- 여론 흐름을 따라감
- 독자적 판단 고수
- 상대 심리 읽으려 함
```

### Speech Pattern 예시

#### Direct (직설적)
```python
agree: ["ㅇㅇ", "맞음", "인정", "그거임", "팩트"]
disagree: ["아닌데", "ㄴㄴ", "아님", "그건 아니지", "뭔 소리야"]
suspect: ["얘 수상함", "걔 마피아임", "확실함", "봐봐 걔가", "딱봐도"]
```

#### Quiet (조용한)
```python
agree: ["음...", "그런가", "...그렇네", "..."]
suspect: ["좀 이상한듯", "...의심됨", "뭔가"]
```

#### Chatty (수다쟁이)
```python
agree: ["아 ㅋㅋ 맞아맞아", "완전 인정ㅋㅋ", "그니까요~", "ㅇㅈㅇㅈ"]
suspect: ["야 진짜 걔 수상해ㅋㅋ", "걔 마피아 아님? ㅋㅋ", "봐봐 ㅋㅋㅋ"]
```

#### Logical (논리적)
```python
agree: ["동의함", "논리적임", "맞는 말임", "그게 합리적"]
suspect: ["정황상 의심됨", "행동 패턴이 수상함", "일관성이 없음"]
```

---

## 🔄 AI 호출 흐름

### 1. Phase Handler (`action_handlers.py`)

```python
# Night
await handle_night_phase(state, request)
  ↓ (Citizen은 여기서 종료)
  ↓
await call_ai_with_retry(state, prompt)

# Vote
await handle_vote_phase(state, request)
  ↓
await call_ai_with_retry(state, prompt)

# Chat (백그라운드)
await handle_chat_phase(state, request)
  ↓
async run_chat_loop():
    while time_left > 5:
        await Runner.run(...)
        await asyncio.sleep(2)
```

### 2. AI 호출 with Retry (`call_ai_with_retry`)

```python
# Step 1: Initial Call (최대 3번 retry - conversation lock)
for attempt in range(3):
    try:
        result = await Runner.run(
            starting_agent=state.agent,
            input=prompt,
            session=state.session,  # OpenAI Conversations
            max_turns=20
        )
        break
    except "conversation_lock_failed":
        await asyncio.sleep((attempt + 1) * 0.5)  # 0.5s, 1s, 1.5s
        
# Step 2: Check Action Submitted
if state.action_submitted:
    return True

# Step 3: Urgent Reminder (action 안했을 때)
retry_result = await Runner.run(
    input="🚨 URGENT: You MUST submit your action NOW!",
    max_turns=3
)

# Step 4: Fallback
if still not submitted:
    state.pending_action_target = None  # Abstain
```

### 3. Tool 실행

```python
# Example: submit_vote
@function_tool
def submit_vote(target_index: int) -> str:
    logger.info(f"🗳️ [P{state.player_index}] VOTED → P{target_index}")
    state.pending_action_target = target_index
    state.action_submitted = True
    return f"Vote submitted: Player {target_index}"
```

### 4. Vector 생성

```python
# generate_night_work_vectors()
if phase == "vote":
    vote_vec = create_one_hot_vector(target_index)  # [0,0,1,0,0]
    attack_vec = zero
    heal_vec = zero
    
elif phase == "night":
    if role == "mafia":
        attack_vec = create_one_hot_vector(target_index)
    elif role == "doctor":
        heal_vec = create_one_hot_vector(target_index)
    # Police는 서버에 zero vector만 전송 (조사는 client-side)
```

---

## 🔐 보안 & 프라이버시

### Blind Protocol
- **각 에이전트는 자기 역할만 앎**
- 다른 플레이어 역할은 암호화 상태
- 서버도 역할을 평문으로 알 수 없음

### Network Obfuscation
- **모든 플레이어가 dummy investigation packet 전송**
- 경찰의 실제 조사와 구별 불가
- 딜레이: 0.5~1.5초 랜덤

### Conversation Lock
- OpenAI Conversations는 동시 쓰기 불가
- 최대 3번 재시도 (0.5s 간격)
- 실패 시 에러 발생

---

## 📊 로깅

### 간소화된 로그 포맷

```
🎮 Game ID: {game_id}
🎭 Role: {ROLE}
🎭 Agent {index} 성격: {communication}, {speech_style}

📖 [P{index}] READ: [P{sender}] {message}
💬 [P{index}] SENT: {message}
📝 [P{index}] Suspects P{target}: {level}

🗳️ [P{index}] VOTED → P{target}
🗳️ [P{index}] ABSTAINED

🔪 Mafia → P{target}
💊 Doctor → P{target}
🔍 [P{index}] INVESTIGATE → P{target}
```

---

## 🎯 핵심 포인트 요약

### Phase별 목적
1. **CHAT**: 자유로운 토론, 정보 수집, 의심 표명
2. **VOTE**: 가장 의심스러운 사람 투표
3. **NIGHT**: 역할 능력 사용 (Mafia 죽이기, Doctor 살리기, Police 조사)

### 역할별 전략
- **Mafia**: 시민인 척, 어그로 분산, 동료 보호
- **Doctor**: 역할 숨기기, 중요 인물 보호, 필요시 자가 치료
- **Police**: 조사 결과 신중히 공개, 타이밍 중요
- **Citizen**: 토론과 투표로 마피아 찾기

### AI 에이전트 특징
- **성격 일관성**: 게임 전체에서 같은 말투/행동 패턴
- **자연스러운 대화**: 사람처럼 말하도록 프롬프팅
- **전략적 사고**: 분석 도구 활용 (투표 패턴, 모순 감지 등)
- **적응적 행동**: 상황에 따라 공격적/수비적 전환

---

**끝!** 🎉
