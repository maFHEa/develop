# 🧪 QA Test Checklist - Mafia Game with Threshold FHE

## 📋 목적
모든 역할(Human/Agent)과 모든 게임 상황에서 버그 없이 정상 작동하는지 검증

---

## 🧑 Human QA

### 1. CITIZEN (시민)

#### 1.1 초기화 & 역할 할당
- [v] DKG 프로토콜 정상 완료
- [v] 역할 "CITIZEN" 할당 확인
- [v] 암호화된 역할 벡터 수신 확인
- [v] 게임 시작 메시지 수신

#### 1.2 Night Phase
- [v] "Your Role: CITIZEN" 표시
- [v] "You have no action this phase" 메시지
- [v] Zero vector 자동 제출 (실제 행동 없음)
- [v] 다음 페이즈로 정상 전환

#### 1.3 Day Phase
- [v] 채팅 메시지 수신 가능
- [v] 채팅 메시지 전송 가능
- [v] 다른 플레이어 메시지 확인

#### 1.4 Vote Phase
- [v] 생존자 목록 정확히 표시
- [v] 자신(Human)을 제외한 타겟 선택 가능
- [v] 유효한 투표 제출 확인
- [v] 투표 결과 집계 정상 (득표수 확인)

#### 1.5 사망 시나리오
- [v] Mafia에게 공격받아 사망
- [v] 투표로 처형당해 사망
- [v] 사망 후 행동 불가 (Zero vector만 제출)
- [v] 게임 종료까지 관전

---

### 2. DOCTOR (의사)

#### 2.1 초기화 & 역할 할당
- [v] 역할 "DOCTOR" 할당 확인
- [v] 치료 능력 설명 확인

#### 2.2 Night Phase
- [v] "Your Role: DOCTOR" 표시
- [v] 생존자 목록에서 타겟 선택
- [v] 암호화된 One-hot vector 생성 및 제출
- [v] 치료 대상이 공격받았을 때 생존 확인

#### 2.3 치료 성공 케이스
- [v] Mafia가 공격한 플레이어를 정확히 치료
- [v] 해당 플레이어 생존 확인
- [v] "No one died" 메시지 확인

#### 2.4 치료 실패 케이스
- [v] 공격받지 않은 플레이어 치료
- [v] 다른 플레이어가 사망
- [v] 의미 없는 치료였지만 오류 없음

#### 2.5 사망 후
- [v] 사망 후 치료 능력 상실
- [v] Zero vector만 제출

---

### 3. MAFIA (마피아)

#### 3.1 초기화 & 역할 할당
- [v] 역할 "MAFIA" 할당 확인
- [v] 살인 능력 설명 확인

#### 3.2 Night Phase - 공격 수행
- [v] "Your Role: MAFIA" 표시
- [v] 생존자 목록에서 타겟 선택
- [v] 유효한 타겟 선택 (자신 제외)
- [ ] 암호화된 One-hot vector 생성 및 제출
- [v] 공격 성공 시 타겟 사망 확인 (치료받지 않은 경우)

#### 3.3 Night Phase - 공격 실패 (Doctor 치료)
- [v] 공격한 타겟이 의사의 치료를 받음
- [v] 타겟 생존 확인
- [v] "No one died" 메시지

#### 3.4 Day/Vote Phase - 위장 전략
- [v] 일반 시민처럼 채팅 가능
- [v] 투표 참여 가능
- [v] 다른 플레이어 의심 회피

#### 3.5 승리 조건
- [v] Mafia 수 >= Citizen 수 → Mafia 승리
- [v] 게임 종료 메시지 확인

#### 3.6 패배 조건
- [v] 모든 Mafia 사망 → Citizen 승리
- [v] 투표로 처형당할 때 역할 공개

---

### 4. POLICE (경찰)

#### 4.1 초기화 & 역할 할당
- [ ] 역할 "POLICE" 할당 확인
- [ ] 조사 능력 설명 확인
- [ ] 경찰 전용 suspicion notes 초기화

#### 4.2 Night Phase - 조사 수행 (Mafia 타겟)
- [ ] "Your Role: POLICE" 표시
- [ ] 생존자 목록에서 조사 대상 선택
- [ ] 유효한 타겟 선택 (자신 제외)
- [ ] Homomorphic dot product 계산 (role · [0,1,0,0])
- [ ] **Parallel threshold decryption 수행**
  - [ ] 자신의 partial decrypt (partial_decrypt_main)
  - [ ] 다른 모든 플레이어에게 partial 요청
  - [ ] Fusion decrypt
- [ ] 결과 확인: **"MAFIA" 판정**
- [ ] 조사 결과가 비밀로 유지 (다른 플레이어는 모름)
- [ ] Suspicion note에 "CONFIRMED_MAFIA" 기록

#### 4.3 Night Phase - 조사 수행 (비 Mafia 타겟)
- [ ] 조사 대상이 Citizen/Doctor/Police
- [ ] 결과 확인: **"NOT MAFIA" 판정**
- [ ] Suspicion note에 "CONFIRMED_CITIZEN" 기록

#### 4.4 조사 결과 활용 - Day Phase
- [ ] 확인된 Mafia 정보를 기반으로 채팅
- [ ] 다른 플레이어 설득 시도
- [ ] Vote phase에서 확인된 Mafia에게 투표

#### 4.5 복호화 정확성 검증
- [ ] 디버그 로그 확인: `Decrypted vector (first 4): [0, 1, 0, 0]` (Mafia)
- [ ] 디버그 로그 확인: `Decrypted vector (first 4): [0, 0, 0, 0]` (비 Mafia)
- [ ] Sum 값이 1 또는 0으로 정확히 계산됨
- [ ] **쓰레기 값이 나오지 않음** (예: `[-25786, 18282, ...]`)

#### 4.6 Human이 Player 0일 때 (Lead)
- [ ] `partial_decrypt_lead` 사용 확인
- [ ] 다른 플레이어들에게 `/investigate_parallel` 요청
- [ ] 모든 partial 수집 후 fusion decrypt

#### 4.7 Human이 Player 0이 아닐 때 (Main)
- [ ] ⚠️ **현재 Human은 항상 Player 0**
- [ ] (향후) Player 0이 아닌 경우 `partial_decrypt_main` 사용해야 함

#### 4.8 조사 에러 케이스
- [ ] 자신을 조사하려 할 때 에러 처리
- [ ] 죽은 플레이어 조사 시도 시 에러 처리
- [ ] 네트워크 오류 시 재시도 또는 실패 처리

---

## 🤖 Agent Player

### 5. CITIZEN (시민)

#### 5.1 초기화 & 역할 할당
- [ ] DKG 참여 성공
- [o] 역할 "CITIZEN" 수신 확인
- [o] AI Agent 초기화 (personality 할당)

#### 5.2 Night Phase - 자동 행동
- [ ] AI가 `submit_night_action(-1)` 호출 (행동 없음)
- [o] Zero vector 제출
- [ ] 타임아웃 없이 완료

#### 5.3 Day Phase - 채팅 및 추론
- [o] 다른 플레이어 메시지 읽기
- [ ] 의심되는 플레이어에 대한 채팅 전송
- [ ] Suspicion notes 업데이트

#### 5.4 Vote Phase - 자동 투표
- [ ] `get_game_status()` 호출하여 상태 확인
- [ ] 의심 수준 기반 투표 대상 선택
- [ ] `submit_vote(target_index)` 호출
- [ ] 유효한 투표 제출

#### 5.5 사망 후
- [ ] 사망 후 행동 제출하지 않음
- [ ] Zero vector만 제출

---

### 6. DOCTOR (의사)

#### 6.1 초기화
- [ ] 역할 "DOCTOR" 수신
- [ ] AI에게 역할별 지시사항 전달

#### 6.2 Night Phase - 치료 대상 선택
- [o] AI가 `submit_night_action(target_index)` 호출
- [o] 유효한 타겟 선택
- [o] One-hot vector 생성 및 암호화
- [o] 제출 완료

#### 6.3 치료 전략
- [ ] AI가 의심받는 플레이어 보호
- [ ] 랜덤 선택이 아닌 전략적 선택 (AI 판단)
- [ ] 매 턴 다른 플레이어 선택 가능
- [o] 자기 자신 선택 가능

#### 6.4 치료 성공 확인
- [ ] Mafia의 공격과 일치하는 경우 생존 확인
- [ ] "No one died" 메시지

---

### 7. MAFIA (마피아)

#### 7.1 초기화
- [o] 역할 "MAFIA" 수신
- [ ] AI에게 Mafia 역할 지시사항 전달

#### 7.2 Night Phase - 공격 대상 선택
- [ ] AI가 `submit_night_action(target_index)` 호출
- [ ] 유효한 타겟 선택 (자신 제외)
- [ ] One-hot vector 생성 및 암호화
- [ ] 제출 완료

#### 7.3 공격 전략
- [ ] AI가 의심받지 않는 전략적 선택
- [ ] Doctor/Police 우선 제거 시도
- [ ] 매 턴 공격 수행

#### 7.4 Day Phase - 위장
- [ ] 일반 시민처럼 행동
- [ ] 다른 플레이어 의심하며 주의 분산
- [ ] 자연스러운 채팅

#### 7.5 Vote Phase
- [ ] 자신에게 의심을 두지 않도록 투표
- [ ] Citizen에게 투표하여 수 감소

---

### 8. POLICE (경찰)

#### 8.1 초기화
- [ ] 역할 "POLICE" 수신
- [ ] PoliceNoteManager 초기화 (확장된 suspicion notes)
- [ ] AI에게 Police 역할 지시사항 전달

#### 8.2 Night Phase - 조사 수행 (중요!)
- [ ] AI가 `submit_night_action(target_index)` 호출
- [ ] **Agent가 자신의 partial decrypt 수행**
  - [ ] ⚠️ **`partial_decrypt_main` 사용 (NOT partial_decrypt_lead)**
  - [ ] `partial_decrypt_lead`는 Player 0 (Human) 전용
- [ ] 다른 모든 플레이어에게 `/investigate_parallel` 요청
  - [ ] Human (Player 0) 포함
  - [ ] 다른 Agent들 포함
- [ ] 모든 partial 수집
- [ ] Fusion decrypt 수행
- [o] 결과 해석: `sum >= 1` → Mafia, `sum < 1` → 비 Mafia

#### 8.3 조사 결과 정확성 검증 (핵심!)
- [o] **Mafia 조사 시**: `[0, 1, 0, 0]` 복호화 → "MAFIA" 판정
- [o] **비 Mafia 조사 시**: `[0, 0, 0, 0]` 복호화 → "NOT MAFIA" 판정
- [o] **절대 쓰레기 값이 나오면 안 됨!**
  - ❌ `[-7627, 17797, -29831, -8432]` 같은 값
  - ❌ Sum이 음수 또는 이상한 값
- [o] 디버그 로그 확인:
  ```
  🔍 DEBUG - Decrypted vector (first 4): [0, 1, 0, 0]
  🔍 DEBUG - Sum: 1
  ✅ Investigation complete: Player X is 🔴 MAFIA
  ```

#### 8.4 조사 결과 저장
- [ ] `add_investigation_result()` 호출
- [ ] Suspicion note에 "CONFIRMED_MAFIA" 또는 "CONFIRMED_CITIZEN" 기록
- [ ] `is_confirmed=True` 플래그 설정 (수정 불가)
- [ ] Turn 번호 기록

#### 8.5 Day Phase - 정보 활용
- [ ] 확인된 Mafia를 채팅에서 공개
- [ ] 다른 플레이어 설득
- [ ] 전략적 정보 공유 (또는 숨김)

#### 8.6 Vote Phase
- [ ] 확인된 Mafia에게 투표
- [ ] `get_confirmed_mafia()` 활용

#### 8.7 에러 케이스
- [ ] 자신 조사 시도 → 에러 처리
- [ ] 네트워크 실패 시 재시도 또는 fallback
- [ ] Timeout 처리

---

## 🔐 Threshold FHE 시스템 테스트

### 9. DKG (Distributed Key Generation)

#### 9.1 Round 1: Public Key Chain
- [ ] Human이 `dkg_keygen_lead` 수행
- [ ] Public key serialize 및 브로드캐스트
- [ ] Agent 1-4가 순차적으로 `dkg_keygen_join`
- [ ] 각 Agent가 이전 key를 extend
- [ ] 최종 joint public key 생성 확인

#### 9.2 Round 2: KeySwitch Keys
- [ ] Human이 `MultiKeySwitchGen` 생성
- [ ] Agent 1-4가 각각 KeySwitch key 생성
- [ ] 모든 key 수집 및 결합
- [ ] Combined KeySwitch key 생성

#### 9.3 Round 3: Multiplication Keys
- [ ] Human이 `MultiMultEvalKey` 생성
- [ ] Combined KeySwitch key 사용
- [ ] Agent 1-4가 각각 MultiMult key 생성
- [ ] 모든 key 수집 및 결합
- [ ] **최종 multiplication key를 context에 `InsertEvalMultKey`**
- [ ] ✅ "Threshold multiplication key installed!" 메시지 확인

#### 9.4 Context 공유 검증
- [ ] Human과 모든 Agent가 **동일한 PlaintextModulus** 사용
- [ ] MultiplicativeDepth 일치 (기본 2)
- [ ] Ring dimension 일치
- [ ] **Multiplication key가 모든 context에 설치됨**

---

### 10. Role Assignment (Blind Protocol)

#### 10.1 역할 암호화
- [ ] Human이 역할 리스트 셔플 (secure random)
- [ ] 각 역할을 One-hot vector로 변환
  - Citizen: `[1, 0, 0, 0]`
  - Mafia: `[0, 1, 0, 0]`
  - Doctor: `[0, 0, 1, 0]`
  - Police: `[0, 0, 0, 1]`
- [ ] Joint public key로 암호화
- [ ] 암호화된 역할 벡터 각 플레이어에게 전송

#### 10.2 Blind Threshold Decryption
- [ ] 각 플레이어가 자신의 역할만 복호화
- [ ] Human: `partial_decrypt_lead` 사용
- [ ] Agent: `partial_decrypt_main` 사용
- [ ] 모든 partial 수집
- [ ] Fusion decrypt로 최종 역할 복호화
- [ ] 복호화된 벡터에서 역할 추출 (argmax)

#### 10.3 비밀성 검증
- [ ] 다른 플레이어의 역할을 알 수 없음
- [ ] 암호화된 역할 벡터만 공유됨
- [ ] Partial decrypt만으로는 정보 누출 없음

---

### 11. Night Phase - Blind Aggregation

#### 11.1 3-Vector Protocol
- [ ] 각 플레이어가 3개 벡터 생성:
  - Attack vector (Mafia만 사용)
  - Heal vector (Doctor만 사용)
  - Investigate vector (Police만 사용)
- [ ] 역할에 따라 해당 벡터만 유효, 나머지는 Zero vector

#### 11.2 Attack Vector Aggregation
- [ ] Mafia의 attack vector 수집
- [ ] `aggregate_encrypted_vectors` 호출
- [ ] 동형 덧셈으로 결합
- [ ] 복호화 없이 암호화 상태 유지

#### 11.3 Heal Vector Aggregation
- [ ] Doctor의 heal vector 수집
- [ ] 동형 덧셈으로 결합

#### 11.4 Kill Computation (Homomorphic)
- [ ] `compute_killed_vector` 호출
- [ ] `attack_vector - heal_vector` (동형 연산)
- [ ] 결과가 양수인 플레이어 사망
- [ ] **복호화 전까지 개인 행동 비밀 유지**

#### 11.5 Threshold Decryption
- [ ] Kill vector를 threshold decrypt
- [ ] Human이 `partial_decrypt_lead`
- [ ] Agent들이 `partial_decrypt_main`
- [ ] Fusion decrypt로 최종 결과
- [ ] 사망자 확인

---

### 12. Police Investigation (Homomorphic Dot Product)

#### 12.1 Dot Product 계산
- [ ] Target의 암호화된 역할 벡터: `role_enc`
- [ ] Mafia check vector: `[0, 1, 0, 0]`
- [ ] `homomorphic_dot_product(cc, role_enc, [0,1,0,0])`
- [ ] **EvalMult 사용 → Multiplication key 필수!**

#### 12.2 Multiplication Key 검증
- [ ] Context에 mult key가 설치되어 있어야 함
- [ ] `InsertEvalMultKey` 이후에만 EvalMult 가능
- [ ] Key 없으면 **복호화 결과가 쓰레기 값**

#### 12.3 Parallel Threshold Decryption
- [ ] 조사자(경찰)가 자신의 partial decrypt 먼저
  - Human (Player 0): `partial_decrypt_lead`
  - Agent (Player 1-4): **`partial_decrypt_main`**
- [ ] 다른 모든 플레이어에게 `/investigate_parallel` 요청
- [ ] 각 플레이어가 partial 반환
- [ ] Fusion decrypt
- [ ] **결과 검증**: `[0, 1, 0, 0]` (Mafia) 또는 `[0, 0, 0, 0]` (비 Mafia)

#### 12.4 결과 해석
- [ ] `sum(decrypted_vector[:4]) >= 1` → Mafia
- [ ] `sum(decrypted_vector[:4]) < 1` → 비 Mafia
- [ ] 조사자에게만 결과 통보 (비밀)

---

### 13. Vote Phase - Threshold Decryption

#### 13.1 투표 수집
- [ ] 각 플레이어가 투표 대상 One-hot vector 생성
- [ ] 암호화하여 제출

#### 13.2 투표 집계 (Homomorphic Sum)
- [ ] 모든 투표 벡터를 동형 덧셈
- [ ] `aggregate_encrypted_vectors` 사용

#### 13.3 Threshold Decryption
- [ ] 집계된 벡터 복호화
- [ ] 각 플레이어의 득표수 확인
- [ ] 최다 득표자 처형

---

## 🐛 버그 체크리스트

### 14. 알려진 버그 수정 확인

#### 14.1 Police Investigation 복호화 실패 (CRITICAL)
- [ ] **Agent가 `partial_decrypt_lead` 사용하는 버그** → `partial_decrypt_main`으로 수정
  - 파일: `/agent/agent_logic.py`
  - Line 441: `my_partial = partial_decrypt_main(...)`
- [ ] Import 수정: `from service.crypto.threshold_decryption import partial_decrypt_main, fusion_decrypt`
- [ ] 테스트: Agent Police가 조사 시 정확한 복호화 결과 확인

#### 14.2 Multiplication Key 설치 누락
- [ ] DKG Round 3 완료 후 `InsertEvalMultKey` 호출 확인
- [ ] Human/Agent 모두 mult key 설치됨
- [ ] EvalMult 연산 전에 key 존재 여부 검증

#### 14.3 Player Addresses 저장 누락
- [ ] `blind_role_assignment`에서 `player_addresses` 저장
- [ ] Agent state에 저장되어 있는지 확인
- [ ] 조사 시 올바른 주소로 요청

#### 14.4 네트워크 연결 실패
- [ ] "All connection attempts failed" 에러 발생하지 않음
- [ ] Retry 로직 작동
- [ ] Timeout 적절히 설정 (10초)

---

## 🎮 전체 게임 플로우 통합 테스트

### 15. 완전한 게임 실행

#### 15.1 Setup Phase
- [ ] 5명 플레이어 초기화
- [ ] DKG 완료 (모든 라운드)
- [ ] 역할 할당 (blind protocol)
- [ ] 게임 시작

#### 15.2 Night 1
- [ ] Mafia 공격
- [ ] Doctor 치료
- [ ] Police 조사
- [ ] 사망자 발표

#### 15.3 Day 1
- [ ] 채팅 활성화
- [ ] AI들 추론 및 대화

#### 15.4 Vote 1
- [ ] 모든 플레이어 투표
- [ ] 득표수 집계
- [ ] 최다 득표자 처형

#### 15.5 반복 (Night 2, Day 2, ...)
- [ ] 게임 종료 조건까지 반복

#### 15.6 승리 조건 확인
- [ ] Mafia 모두 사망 → Citizen 승리
- [ ] Mafia >= 나머지 → Mafia 승리
- [ ] 최종 역할 공개

---

## 📊 성능 및 안정성 테스트

### 16. 성능 테스트

#### 16.1 Threshold Decryption 속도
- [ ] Role decryption: 각 플레이어 < 5초
- [ ] Night phase aggregation: < 10초
- [ ] Police investigation: < 10초
- [ ] Vote decryption: < 5초

#### 16.2 네트워크 안정성
- [ ] 모든 HTTP 요청 성공률 > 95%
- [ ] Timeout으로 인한 실패 없음
- [ ] Retry 시 성공

#### 16.3 메모리 사용
- [ ] 메모리 누수 없음
- [ ] 게임 종료 후 리소스 해제

---

## 🔍 Edge Cases

### 17. 특수 상황 테스트

#### 17.1 동점 투표
- [ ] 2명 이상이 같은 득표수
- [ ] 처리 방법 확인 (무작위 선택 또는 재투표)

#### 17.2 모두 기권
- [ ] 모든 플레이어가 `-1` 투표
- [ ] "No one executed" 처리

#### 17.3 마지막 2명
- [ ] Mafia 1명 vs Citizen 1명
- [ ] 즉시 Mafia 승리

#### 17.4 Police 사망 후
- [ ] 더 이상 조사 불가
- [ ] Zero vector만 제출

#### 17.5 Doctor 사망 후
- [ ] 더 이상 치료 불가
- [ ] Zero vector만 제출

---

## ✅ 최종 승인 체크리스트

### 18. 배포 전 최종 확인

- [ ] 모든 Human 역할 테스트 통과
- [ ] 모든 Agent 역할 테스트 통과
- [ ] Police investigation 정확성 100%
- [ ] Threshold FHE 프로토콜 정상 작동
- [ ] 네트워크 안정성 검증
- [ ] 알려진 버그 모두 수정
- [ ] 로그 출력 적절함 (디버그 정보 포함)
- [ ] 게임 종료 시 올바른 승자 판정
- [ ] 성능 요구사항 충족
- [ ] 코드 리뷰 완료
- [ ] 문서 업데이트 완료

---

## 📝 테스트 실행 방법

### 19. 테스트 실행 가이드

#### 단계별 실행
1. **환경 준비**
   ```bash
   # Terminal 1-4: Agent Lobby
   cd agent && python lobby.py --port 8000
   cd agent && python lobby.py --port 8001
   cd agent && python lobby.py --port 8002
   cd agent && python lobby.py --port 8003
   
   # Terminal 5: Human
   cd human && python app.py
   ```

2. **역할별 테스트**
   - 각 역할마다 별도 게임 세션 시작
   - 로그 저장: `logs/test_[role]_[timestamp].log`
   - 체크리스트 항목별로 수동 확인

3. **버그 기록**
   - 실패한 항목은 이슈 트래커에 등록
   - 재현 가능한 시나리오 작성
   - 로그 파일 첨부

4. **자동화 (향후)**
   - 단위 테스트 작성
   - Integration test 스크립트
   - CI/CD 파이프라인 구축

---

## 🎯 우선순위

### P0 (Critical - 반드시 수정)
- ✅ Agent Police investigation 복호화 버그 수정
- Multiplication key 설치 확인
- 모든 역할의 기본 동작

### P1 (High - 게임 진행에 영향)
- Vote phase 정확성
- Night phase aggregation
- 승리 조건 판정

### P2 (Medium - UX 개선)
- 에러 메시지 명확화
- 로그 출력 개선
- Timeout 최적화

### P3 (Low - Nice to have)
- AI 전략 개선
- 채팅 품질
- 성능 최적화

---

**작성일**: 2025-12-07  
**버전**: 1.0  
**최종 업데이트**: Police investigation 복호화 버그 수정 후
