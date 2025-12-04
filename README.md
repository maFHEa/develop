# maFHEa: Mafia Game with Threshold FHE

OpenFHE 기반 **Threshold Fully Homomorphic Encryption**을 사용한 안전한 마피아 게임 구현

## 개요

이 프로젝트는 마피아 게임의 역할 배분을 **분산 키 생성(DKG)**과 **Threshold 복호화**를 통해 안전하게 수행합니다. 어떤 단일 참가자도 다른 플레이어의 역할을 알 수 없으며, 모든 플레이어가 협력해야만 역할이 공개됩니다.

## 핵심 보안 특성

| 특성 | 설명 |
|------|------|
| **분산 키 생성 (DKG)** | 공개키는 공유, 비밀키는 각 플레이어가 일부만 보유 |
| **n-of-n Threshold** | 모든 플레이어가 참여해야 복호화 가능 |
| **NOISE_FLOODING** | 부분 복호화 시 정보 누출 방지 |
| **개별 역할 복호화** | 각 플레이어는 자신의 역할만 알 수 있음 |
| **Uniform Action Protocol** | 모든 플레이어가 동일 크기 패킷 전송 (트래픽 분석 방지) |

## 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                         Game Flow                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   Human Host (Lead)          AI Agents                          │
│   ┌──────────────┐     ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│   │   main.py    │     │ Agent 1  │ │ Agent 2  │ │ Agent 3  │  │
│   │              │     │ player.py│ │ player.py│ │ player.py│  │
│   └──────┬───────┘     └────┬─────┘ └────┬─────┘ └────┬─────┘  │
│          │                  │            │            │         │
│          │    1. DKG Protocol (Sequential Key Chain)            │
│          ├─────────────────▶├───────────▶├───────────▶│         │
│          │                  │            │            │         │
│          │    2. Encrypted Role Assignment                      │
│          │    Enc(roles, pk_joint)                              │
│          │                  │            │            │         │
│          │    3. Threshold Decryption (All parties)             │
│          ├─────────────────▶├───────────▶├───────────▶│         │
│          │◀─────────────────┤◀───────────┤◀───────────┤         │
│          │                  │            │            │         │
│          │    4. Fusion → Individual Roles                      │
│          │                                                      │
└─────────────────────────────────────────────────────────────────┘
```

## DKG (Distributed Key Generation) 프로토콜

### 1단계: CryptoContext 생성 및 배포

```
Human Host가 OpenFHE CryptoContext 생성
  ↓
모든 Agent에게 CryptoContext 전송 (/dkg_setup)
```

### 2단계: 순차적 키 체인 생성 

```
Round 0: Human (Lead)
    kp0 = cc.KeyGen()
    pk_chain = kp0.publicKey
    sk0 저장 (로컬)

Round 1: Agent 1
    kp1 = cc.MultipartyKeyGen(pk_chain)
    pk_chain = kp1.publicKey
    sk1 저장 (로컬)

Round 2: Agent 2
    kp2 = cc.MultipartyKeyGen(pk_chain)
    pk_chain = kp2.publicKey
    sk2 저장 (로컬)

Round 3: Agent 3
    kp3 = cc.MultipartyKeyGen(pk_chain)
    pk_chain = kp3.publicKey
    sk3 저장 (로컬)

Round 4: Agent 4
    kp4 = cc.MultipartyKeyGen(pk_chain)
    pk_joint = kp4.publicKey  ← 최종 공동 공개키
    sk4 저장 (로컬)
```

**보안 포인트**: 각 참가자는 자신의 비밀키(sk_i)만 알고, 완전한 비밀키는 누구도 알 수 없습니다.

### 3단계: 역할 암호화

```python
# Host가 역할 셔플 후 암호화
roles = ["citizen", "mafia", "doctor", "police"]
random.shuffle(roles)

for player_idx, role in enumerate(roles):
    role_vector = [0, 0, 0, 0]  # [citizen, mafia, doctor, police]
    role_vector[ROLE_ENCODING[role]] = 1

    encrypted_role = cc.Encrypt(pk_joint, role_vector)
```

### 4단계: Threshold 복호화 

```
각 플레이어의 암호화된 역할에 대해:

    Human (Lead): partial_0 = cc.MultipartyDecryptLead(ciphertext, sk0)
        ↓
    Agent 1:      partial_1 = cc.MultipartyDecryptMain(ciphertext, sk1)
        ↓
    Agent 2:      partial_2 = cc.MultipartyDecryptMain(ciphertext, sk2)
        ↓
    Agent 3:      partial_3 = cc.MultipartyDecryptMain(ciphertext, sk3)
        ↓
    Agent 4:      partial_4 = cc.MultipartyDecryptMain(ciphertext, sk4)
        ↓
    Fusion:       plaintext = cc.MultipartyDecryptFusion([partial_0..4])
        ↓
    역할 확정:     role = decode(plaintext)  # [0,1,0,0,0] → "mafia"
```

## 디렉토리 구조

```
maFHEa/
├── mafia_launcher.py     # 게임 런처 (로비 서버 + 게임 시작)
├── README.md
│
├── human/                # Human Host (게임 진행자)
│   ├── main.py          # 메인 게임 로직, DKG 조율
│   ├── config.py        # 게임/네트워크/암호화 설정
│   ├── requirements.txt
│   └── start_game.sh
│
└── agent/                # AI Agent (플레이어)
    ├── lobby.py         # Agent 생성 서버
    ├── player.py        # Agent 플레이어 로직
    ├── security.py      # OpenFHE 암호화 모듈
    ├── models.py        # Pydantic 모델
    └── venv/            # Python 가상환경
```

## 설치 및 실행

### 요구사항

- Python 3.10+
- Ubuntu 22.04/24.04 (OpenFHE 지원)
- OpenAI API Key

### 설치

```bash
# Human 환경
cd human
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# Agent 환경
cd ../agent
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

### 실행

```bash
# .env 파일에 API 키 설정
echo "OPENAI_API_KEY=your-key-here" > human/.env

# 게임 실행
python3 mafia_launcher.py
```

## 암호화 파라미터

```python
CRYPTO_CONFIG = {
    "scheme": "BFVrns",              # BFV with RNS
    "plaintext_modulus": 65537,      # 충분히 큰 소수
    "multiplicative_depth": 2,        # 곱셈 깊이
    "multiparty_mode": "NOISE_FLOODING_MULTIPARTY"  # 가장 안전한 모드
}
```

### NOISE_FLOODING_MULTIPARTY

부분 복호화 시 노이즈를 추가하여 비밀키 정보 누출을 방지합니다. 이는 악의적인 참가자가 부분 복호화 결과를 분석해도 다른 참가자의 비밀키를 추론할 수 없게 합니다.

## API 엔드포인트

### Agent (player.py)

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/health` | GET | 헬스 체크 |
| `/init` | POST | 게임 초기화 |
| `/dkg_setup` | POST | CryptoContext 수신 |
| `/dkg_round` | POST | DKG 라운드 참여 (키 생성) |
| `/partial_decrypt` | POST | 부분 복호화 수행 |
| `/role_assignment` | POST | 역할 수신 |
| `/request_action` | POST | 행동 요청 (투표, 능력 사용) |

### Lobby (lobby.py)

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/health` | GET | 헬스 체크 |
| `/spawn_agent` | POST | 새 Agent 생성 |
| `/agent/{id}` | DELETE | Agent 종료 |

## 게임 내 암호화 연산

### Night Phase 계산

```python
# 모든 연산은 암호화된 상태로 수행
Enc(Net_Attack) = Sum(Enc(Mafia_Action_i))
Enc(Net_Heal) = Sum(Enc(Doctor_Action_i))
Enc(Is_Killed) = Enc(Net_Attack) * (1 - Enc(Net_Heal))

# 최종 결과만 복호화
Killed = Decrypt(Enc(Is_Killed))
```

### 경찰 조사

```python
# 암호화 상태로 내적 연산
Enc(Target_Query) = [0, 0, 1, 0, 0]  # 원-핫 벡터
Enc(Role_Vector) = [0, 1, 0, 1, 0]    # 1=마피아, 0=기타

Enc(Result) = Enc(Target_Query) ⊙ Enc(Role_Vector)
Is_Mafia = Decrypt(Enc(Result))
```

### 트래픽 분석 방어

```python
# 모든 플레이어가 매 턴 데이터 전송
if can_act:
    send(Encrypt([0, 0, 1, 0]))  # 실제 행동
else:
    send(Encrypt([0, 0, 0, 0]))  # 더미 패킷

# 네트워크 관찰자는 역할 구분 불가
```

## 보안 분석

### 안전한 부분

| 기능 | 보안 메커니즘 |
|------|--------------|
| 역할 배분 | Threshold 복호화 (n-of-n) |
| 투표 | 개별 투표 암호화, 합산 결과만 복호화 |
| 마피아 공격 | 암호화된 타겟, 합산 결과만 공개 |
| 의사 치료 | 암호화된 선택, 결과만 공개 |
| 경찰 조사 | 암호화된 조사, 개인 결과만 복호화 |

### Threat Model

| 공격자 유형 | 보호 수준 |
|------------|-----------|
| Honest-but-Curious Host | 개별 행동 알 수 없음 |
| Network Observer | 트래픽 패턴으로 역할 추론 불가 |
| Malicious Player | 암호문 위조/변조 불가 |

### 주의 사항

- 게임 진행 패턴 분석으로 역할 추론 가능 (메타 정보)
- n-of-n 스킴이므로 한 명이라도 불참하면 복호화 불가

## 역할 인코딩

```python
ROLE_ENCODING = {
    "citizen": 0,
    "mafia": 1,
    "doctor": 2,
    "police": 3
}

# 원-핫 벡터로 표현
# citizen = [1, 0, 0, 0]
# mafia   = [0, 1, 0, 0]
# doctor  = [0, 0, 1, 0]
# police  = [0, 0, 0, 1]
```

## 게임 설정

`human/config.py` 수정:

```python
GAME_CONFIG = {
    "min_players": 4,
    "max_players": 10,
    "role_distribution": {
        4: {"mafia": 1, "doctor": 1, "police": 1, "citizen": 1},
        5: {"mafia": 1, "doctor": 1, "police": 1, "citizen": 2},
        # ...
    },
    "night_phase_timeout": 60,
    "vote_phase_timeout": 60,
}
```

## 트러블슈팅

### OpenFHE 설치 실패

```bash
# Ubuntu 22.04/24.04에서 pip로 설치
pip install openfhe

# 설치 확인
python -c "import openfhe; print(openfhe.__version__)"
```

### Agent 연결 타임아웃

- `config.py`의 `connection_timeout` 증가
- 로컬호스트 방화벽 설정 확인

### OpenAI Rate Limit

- Agent 수 감소
- `player.py`에서 API 호출 간 딜레이 추가

## 라이선스

MIT License

## 참고 자료

- [OpenFHE Documentation](https://openfhe-development.readthedocs.io/)
- [Threshold FHE Tutorial](https://openfhe-development.readthedocs.io/en/latest/sphinx_rsts/intro/tutorials/threshold.html)
- [BFV Scheme Paper](https://eprint.iacr.org/2012/144.pdf)
- [Mafia Game](https://en.wikipedia.org/wiki/Mafia_(party_game))

---

**보안 공지**: 이 구현은 교육 목적입니다. 프로덕션 사용 시 추가 필요:
- 정식 보안 감사
- 네트워크 계층 암호화 (TLS)
- 인증 및 권한 관리
- Byzantine fault tolerance
- 검증 가능한 연산 증명
