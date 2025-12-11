"""
Game Memory System - SQLite 기반 게임 이벤트 기록
대화 내용은 OpenAI Conversations API가 관리하고,
이 시스템은 게임 내 중요 이벤트(죽음, 조사, 행동 등)를 기록
"""
import sqlite3
import json
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class GameMemorySession:
    """게임 이벤트를 SQLite에 기록하는 세션"""
    
    def __init__(self, session_id: str, db_path: str = "db/game_memory.db"):
        """
        Args:
            session_id: "gameid_agentid" 형식의 고유 세션 ID
            db_path: SQLite 데이터베이스 파일 경로
        """
        self.session_id = session_id
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_tables()
    
    def _init_tables(self):
        """필요한 테이블들 생성"""
        cursor = self.conn.cursor()
        
        # 게임 이벤트 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS game_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                turn INTEGER NOT NULL,
                phase TEXT NOT NULL,
                event_type TEXT NOT NULL,
                data TEXT,
                description TEXT
            )
        """)
        
        # 죽음 기록 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deaths (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                turn INTEGER NOT NULL,
                player_index INTEGER NOT NULL,
                cause TEXT NOT NULL,
                revealed_role TEXT
            )
        """)
        
        # 행동 기록 테이블 (투표, 공격, 치료 등)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                turn INTEGER NOT NULL,
                phase TEXT NOT NULL,
                action_type TEXT NOT NULL,
                target_index INTEGER,
                reasoning TEXT
            )
        """)
        
        # 조사 결과 테이블 (경찰 전용)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS investigations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                turn INTEGER NOT NULL,
                target_index INTEGER NOT NULL,
                is_mafia BOOLEAN NOT NULL,
                reasoning TEXT
            )
        """)
        
        # 의심 메모 변경 이력
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS suspicion_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                turn INTEGER NOT NULL,
                target_index INTEGER NOT NULL,
                old_level TEXT,
                new_level TEXT NOT NULL,
                reasoning TEXT
            )
        """)
        
        # 인덱스 생성
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_session 
            ON game_events(session_id, turn)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_deaths_session 
            ON deaths(session_id, turn)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_actions_session 
            ON actions(session_id, turn)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_investigations_session 
            ON investigations(session_id, turn)
        """)
        
        self.conn.commit()
    
    def clear_session(self):
        """현재 세션의 모든 데이터 삭제 (새 게임 시작 시)"""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM game_events WHERE session_id = ?", (self.session_id,))
        cursor.execute("DELETE FROM deaths WHERE session_id = ?", (self.session_id,))
        cursor.execute("DELETE FROM actions WHERE session_id = ?", (self.session_id,))
        cursor.execute("DELETE FROM investigations WHERE session_id = ?", (self.session_id,))
        cursor.execute("DELETE FROM suspicion_changes WHERE session_id = ?", (self.session_id,))
        self.conn.commit()
        logger.info(f"🗑️  Cleared all game memory for session {self.session_id}")
    
    def record_event(self, turn: int, phase: str, event_type: str, 
                    data: Optional[Dict[str, Any]] = None, 
                    description: Optional[str] = None):
        """일반 게임 이벤트 기록"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO game_events (session_id, timestamp, turn, phase, event_type, data, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            self.session_id,
            datetime.now().timestamp(),
            turn,
            phase,
            event_type,
            json.dumps(data) if data else None,
            description
        ))
        self.conn.commit()
        logger.debug(f"📝 Event recorded: {event_type} at turn {turn} ({phase})")
    
    def record_death(self, turn: int, player_index: int, cause: str, revealed_role: Optional[str] = None):
        """죽음 기록"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO deaths (session_id, timestamp, turn, player_index, cause, revealed_role)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            self.session_id,
            datetime.now().timestamp(),
            turn,
            player_index,
            cause,
            revealed_role
        ))
        self.conn.commit()
        
        # 이벤트로도 기록
        self.record_event(
            turn=turn,
            phase="death",
            event_type="player_death",
            data={"player_index": player_index, "cause": cause, "role": revealed_role},
            description=f"Player {player_index} died ({cause})" + (f" - Role: {revealed_role}" if revealed_role else "")
        )
        logger.info(f"💀 Death recorded: Player {player_index} at turn {turn} ({cause})")
    
    def record_action(self, turn: int, phase: str, action_type: str, 
                     target_index: Optional[int] = None, reasoning: Optional[str] = None):
        """행동 기록 (투표, 공격, 치료 등)"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO actions (session_id, timestamp, turn, phase, action_type, target_index, reasoning)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            self.session_id,
            datetime.now().timestamp(),
            turn,
            phase,
            action_type,
            target_index,
            reasoning
        ))
        self.conn.commit()
        
        target_str = f"→ Player {target_index}" if target_index is not None else "(no target)"
        logger.info(f"🎯 Action recorded: {action_type} {target_str} at turn {turn}")
    
    def record_investigation(self, turn: int, target_index: int, is_mafia: bool, reasoning: Optional[str] = None):
        """경찰 조사 결과 기록"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO investigations (session_id, timestamp, turn, target_index, is_mafia, reasoning)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            self.session_id,
            datetime.now().timestamp(),
            turn,
            target_index,
            is_mafia,
            reasoning
        ))
        self.conn.commit()
        
        result_str = "MAFIA" if is_mafia else "NOT MAFIA"
        logger.info(f"🔍 Investigation recorded: Player {target_index} is {result_str} at turn {turn}")
    
    def record_suspicion_change(self, turn: int, target_index: int, 
                               old_level: Optional[str], new_level: str, reasoning: str):
        """의심 레벨 변경 기록"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO suspicion_changes (session_id, timestamp, turn, target_index, old_level, new_level, reasoning)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            self.session_id,
            datetime.now().timestamp(),
            turn,
            target_index,
            old_level,
            new_level,
            reasoning
        ))
        self.conn.commit()
        logger.debug(f"🚨 Suspicion change: Player {target_index}: {old_level} → {new_level}")
    
    def get_recent_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        """최근 이벤트 가져오기"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT turn, phase, event_type, data, description, timestamp
            FROM game_events
            WHERE session_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (self.session_id, limit))
        
        events = []
        for row in cursor.fetchall():
            events.append({
                "turn": row[0],
                "phase": row[1],
                "event_type": row[2],
                "data": json.loads(row[3]) if row[3] else None,
                "description": row[4],
                "timestamp": row[5]
            })
        return events
    
    def get_all_deaths(self) -> List[Dict[str, Any]]:
        """모든 죽음 기록 가져오기"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT turn, player_index, cause, revealed_role, timestamp
            FROM deaths
            WHERE session_id = ?
            ORDER BY turn ASC
        """, (self.session_id,))
        
        deaths = []
        for row in cursor.fetchall():
            deaths.append({
                "turn": row[0],
                "player_index": row[1],
                "cause": row[2],
                "revealed_role": row[3],
                "timestamp": row[4]
            })
        return deaths
    
    def get_my_actions(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """내 행동 이력 가져오기"""
        cursor = self.conn.cursor()
        query = """
            SELECT turn, phase, action_type, target_index, reasoning, timestamp
            FROM actions
            WHERE session_id = ?
            ORDER BY turn DESC
        """
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query, (self.session_id,))
        
        actions = []
        for row in cursor.fetchall():
            actions.append({
                "turn": row[0],
                "phase": row[1],
                "action_type": row[2],
                "target_index": row[3],
                "reasoning": row[4],
                "timestamp": row[5]
            })
        return actions
    
    def get_investigations(self) -> List[Dict[str, Any]]:
        """모든 조사 결과 가져오기 (경찰 전용)"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT turn, target_index, is_mafia, reasoning, timestamp
            FROM investigations
            WHERE session_id = ?
            ORDER BY turn ASC
        """, (self.session_id,))
        
        investigations = []
        for row in cursor.fetchall():
            investigations.append({
                "turn": row[0],
                "target_index": row[1],
                "is_mafia": bool(row[2]),
                "reasoning": row[3],
                "timestamp": row[4]
            })
        return investigations
    
    def get_suspicion_history(self, target_index: int) -> List[Dict[str, Any]]:
        """특정 플레이어에 대한 의심 변경 이력"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT turn, old_level, new_level, reasoning, timestamp
            FROM suspicion_changes
            WHERE session_id = ? AND target_index = ?
            ORDER BY turn ASC
        """, (self.session_id, target_index))
        
        history = []
        for row in cursor.fetchall():
            history.append({
                "turn": row[0],
                "old_level": row[1],
                "new_level": row[2],
                "reasoning": row[3],
                "timestamp": row[4]
            })
        return history
    
    def get_game_summary(self) -> str:
        """게임 전체 요약 생성 (AI가 읽을 수 있는 형태)"""
        lines = ["=== GAME MEMORY SUMMARY ===\n"]
        
        # 죽음 타임라인
        deaths = self.get_all_deaths()
        if deaths:
            lines.append("💀 DEATH TIMELINE:")
            for death in deaths:
                role_str = f" ({death['revealed_role']})" if death['revealed_role'] else ""
                lines.append(f"  Turn {death['turn']}: Player {death['player_index']} - {death['cause']}{role_str}")
            lines.append("")
        
        # 내 조사 결과 (경찰인 경우)
        investigations = self.get_investigations()
        if investigations:
            lines.append("🔍 MY INVESTIGATIONS:")
            for inv in investigations:
                result = "MAFIA" if inv['is_mafia'] else "NOT MAFIA"
                lines.append(f"  Turn {inv['turn']}: Player {inv['target_index']} → {result}")
            lines.append("")
        
        # 최근 행동 (최근 5개)
        actions = self.get_my_actions(limit=5)
        if actions:
            lines.append("🎯 MY RECENT ACTIONS:")
            for action in actions:
                target_str = f"→ P{action['target_index']}" if action['target_index'] is not None else ""
                lines.append(f"  Turn {action['turn']} ({action['phase']}): {action['action_type']} {target_str}")
            lines.append("")
        
        # 최근 이벤트
        events = self.get_recent_events(limit=10)
        if events:
            lines.append("📝 RECENT EVENTS:")
            for event in events[-5:]:  # 최근 5개만
                if event['description']:
                    lines.append(f"  Turn {event['turn']}: {event['description']}")
        
        return "\n".join(lines)
    
    def get_smart_context_for_phase(self, phase: str, role: str) -> str:
        """Phase와 역할에 맞는 스마트한 컨텍스트 생성"""
        lines = []
        
        # 기본 게임 상황
        deaths = self.get_all_deaths()
        alive_players = []  # Will be filled from outside
        
        if deaths:
            lines.append("💀 사망자:")
            for death in deaths[-3:]:  # 최근 3명만
                role_str = f"({death['revealed_role']})" if death['revealed_role'] else ""
                lines.append(f"  P{death['player_index']} {role_str}")
        
        # 역할별 중요 정보
        if role == "police":
            investigations = self.get_investigations()
            if investigations:
                lines.append("\n🔍 내 조사 결과:")
                mafia_found = [inv for inv in investigations if inv['is_mafia']]
                innocent_found = [inv for inv in investigations if not inv['is_mafia']]
                
                if mafia_found:
                    lines.append(f"  🎭 마피아 확정: {[inv['target_index'] for inv in mafia_found]}")
                if innocent_found:
                    lines.append(f"  ✅ 무죄: {[inv['target_index'] for inv in innocent_found]}")
        
        # Phase별 전략 힌트
        if phase == "vote":
            lines.append("\n🗳️ 투표 전략:")
            if role == "police":
                investigations = self.get_investigations()
                mafia_found = [inv['target_index'] for inv in investigations if inv['is_mafia']]
                if mafia_found:
                    lines.append(f"  → Player {mafia_found[0]}는 마피아! 이 사람 투표!")
                else:
                    lines.append("  → 조사 결과 참고해서 의심되는 사람 투표")
            else:
                lines.append("  → 의심스러운 행동 했던 사람")
                lines.append("  → 말이 많이 바뀐 사람")
        
        elif phase == "night":
            my_actions = self.get_my_actions(limit=3)
            if role == "mafia":
                lines.append("\n🔪 마피아 전략:")
                lines.append("  → 위협적인 사람 제거 (말 잘하는 사람, 경찰/의사 의심)")
            elif role == "doctor":
                lines.append("\n💊 의사 전략:")
                lines.append("  → 마피아가 노릴 만한 사람 보호")
                if my_actions:
                    last_heal = next((a for a in my_actions if a['action_type'] == 'heal'), None)
                    if last_heal:
                        lines.append(f"  → 지난번에 P{last_heal['target_index']} 치료함")
            elif role == "police":
                lines.append("\n🔍 경찰 전략:")
                lines.append("  → 수상한 사람부터 조사")
                investigated = [inv['target_index'] for inv in self.get_investigations()]
                if investigated:
                    lines.append(f"  → 이미 조사한 사람: {investigated}")
        
        return "\n".join(lines) if lines else ""
    
    def close(self):
        """데이터베이스 연결 종료"""
        if self.conn:
            self.conn.close()
    
    def __del__(self):
        """소멸자에서 연결 종료"""
        self.close()
