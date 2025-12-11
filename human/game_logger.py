"""
Game Logger - Records decrypted game events to file
Only logs plaintext results after decryption, not encrypted communications
"""
import os
from datetime import datetime
from typing import List, Optional


class GameLogger:
    """Logs decrypted game events to file"""
    
    def __init__(self, game_id: str):
        self.game_id = game_id
        self.log_dir = "logs"
        self.log_file = os.path.join(self.log_dir, f"game.log")
        
        # Create logs directory if not exists
        os.makedirs(self.log_dir, exist_ok=True)
        
        # Initialize/clear log file
        with open(self.log_file, 'w', encoding='utf-8') as f:
            f.write(f"=== Mafia Game Log ===\n")
            f.write(f"Game ID: {game_id}\n")
            f.write(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 50 + "\n\n")
    
    def log(self, message: str):
        """Write a log message with timestamp"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] {message}\n")
    
    def log_section(self, title: str):
        """Write a section header"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write("\n" + "=" * 50 + "\n")
            f.write(f"{title}\n")
            f.write("=" * 50 + "\n")
    
    def log_night_results(self, day: int, killed_vector: List[int], killed_indices: List[int], 
                          num_players: int):
        """Log decrypted night action results"""
        self.log_section(f"Night {day} - Decrypted Results")
        self.log(f"Killed Vector (decrypted): {killed_vector}")
        
        if killed_indices:
            for idx in killed_indices:
                self.log(f"  → Player {idx} was KILLED")
        else:
            self.log("  → No one was killed")
        
        # Log vector breakdown
        self.log("\nVector breakdown:")
        for i in range(num_players):
            status = "KILLED" if killed_vector[i] > 0 else "safe"
            self.log(f"  Player {i}: {killed_vector[i]} ({status})")
    
    def log_vote_results(self, day: int, vote_vector: List[int], voted_out: Optional[int],
                        num_players: int):
        """Log decrypted vote results"""
        self.log_section(f"Day {day} - Vote Results (Decrypted)")
        self.log(f"Vote Vector (decrypted): {vote_vector}")
        
        if voted_out is not None:
            self.log(f"  → Player {voted_out} was VOTED OUT")
        else:
            self.log("  → No one was voted out (tie or no votes)")
        
        # Log vote breakdown
        self.log("\nVote breakdown:")
        for i in range(num_players):
            self.log(f"  Player {i}: {vote_vector[i]} votes received")
    
    def log_game_end(self, winner: str, survivors: List[int], day: int):
        """Log game end state"""
        self.log_section("Game Over")
        self.log(f"Winner: {winner}")
        self.log(f"Final Day: {day}")
        self.log(f"Survivors: {survivors}")
        self.log(f"Ended: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
