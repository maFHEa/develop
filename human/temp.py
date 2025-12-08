# --- DKG 기반 역할 분배 및 복호화 시나리오 (주체별 작업 명확화) ---

import random

ROLE_ENCODING = {"citizen": 0, "mafia": 1, "doctor": 2, "police": 3}
ROLES = ["citizen", "mafia", "doctor", "police"]
player_ids = ["human", "agent1", "agent2", "agent3"]

class CryptoContext:
    def __init__(self):
        self.secret_keys = {}
        self.public_key_chain = []
        self.joint_public_key = None

    def keygen(self, player_id, prev_pk_chain=None):
        sk = f"sk_{player_id}"
        pk = f"pk_{player_id}"
        self.secret_keys[player_id] = sk
        pk_chain = (prev_pk_chain or []) + [pk]
        self.public_key_chain = pk_chain
        print(f"[{player_id}] DKG 참여: 비밀키 생성({sk}), 공개키 생성({pk}), pk_chain={pk_chain}")
        return sk, pk_chain

    def finalize_joint_public_key(self):
        self.joint_public_key = "+".join(self.public_key_chain)
        print(f"[Host] 모든 공개키를 합성하여 공동 공개키 생성: {self.joint_public_key}")

    def encrypt(self, pk, role_vector, player_id):
        print(f"[Host] {player_id}의 역할({role_vector})을 공동 공개키로 암호화하여 전달")
        return (pk, tuple(role_vector))

    def multiparty_decrypt_main(self, ciphertext, sk, player_id):
        print(f"[{player_id}] 자신의 비밀키({sk})로 부분 복호화(partial) 생성")
        return f"partial({sk})"

    def multiparty_decrypt_lead(self, ciphertext, sk, player_id):
        print(f"[{player_id}] (리드) 자신의 비밀키({sk})로 부분 복호화(lead_partial) 생성")
        return f"lead_partial({sk})"

    def multiparty_decrypt_fusion(self, partials, player_id):
        print(f"[{player_id}] 모든 partial을 모아 최종 fusion 복호화 수행")
        return f"fusion({', '.join(partials)})"

# --- 1. DKG 분산키 생성 과정 (순차적으로 각자 참여) ---
cc = CryptoContext()
pk_chain = []
print("\n[DKG 단계] 각 플레이어가 순서대로 분산키 생성에 참여")
for pid in player_ids:
    sk, pk_chain = cc.keygen(pid, pk_chain)
cc.finalize_joint_public_key()

# --- 2. Host가 역할 셔플 및 암호화 ---
print("\n[역할 셔플 및 암호화 단계] Host가 역할을 셔플하고 암호화하여 각자에게 전달")
random.shuffle(ROLES)
encrypted_roles = {}
for pid, role in zip(player_ids, ROLES):
    role_vector = [0, 0, 0, 0]
    role_vector[ROLE_ENCODING[role]] = 1
    encrypted_roles[pid] = cc.encrypt(cc.joint_public_key, role_vector, pid)

# --- 3. 각 플레이어가 자신의 역할 복호화 시도 ---
def player_decrypt_role(player_id):
    print(f"\n[{player_id}] 역할 복호화 단계: 자신의 암호화 역할을 복호화하기 위해 모든 partial 요청")
    ciphertext = encrypted_roles[player_id]
    partials = []
    for pid in player_ids:
        if pid == player_id:
            partial = cc.multiparty_decrypt_lead(ciphertext, cc.secret_keys[pid], pid)
        else:
            partial = cc.multiparty_decrypt_main(ciphertext, cc.secret_keys[pid], pid)
        partials.append(partial)
    fusion_result = cc.multiparty_decrypt_fusion(partials, player_id)
    print(f"[{player_id}] 최종 복호화 결과: {fusion_result}")

print("\n[복호화 단계] 각 플레이어가 자신의 역할을 복호화")
for pid in player_ids:
    player_decrypt_role(pid)

print("\n[증명] DKG로 생성된 공동 공개키와 모든 partial이 모여야만 역할 복호화 가능.")
print("누구도 단독으로 역할을 알 수 없음. (human 포함)")