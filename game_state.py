"""Game state: a thin wrapper around python-chess with lenient move parsing."""

import chess

WHITE = chess.WHITE
BLACK = chess.BLACK


def color_name(color: bool) -> str:
    return "White" if color == chess.WHITE else "Black"


class GameState:
    def __init__(self, user_color: bool = chess.WHITE, fen: str | None = None):
        """`fen` starts from a given position instead of the standard one."""
        self.start_fen = fen
        self.board = chess.Board(fen) if fen else chess.Board()
        self.user_color = user_color

    def reset(self) -> None:
        """Start the game over from the original position."""
        self.board = chess.Board(self.start_fen) if self.start_fen else chess.Board()

    @property
    def turn(self) -> bool:
        return self.board.turn

    @property
    def is_user_turn(self) -> bool:
        return self.board.turn == self.user_color

    @property
    def is_over(self) -> bool:
        return self.board.is_game_over(claim_draw=True)

    @property
    def move_number(self) -> int:
        return self.board.fullmove_number

    def parse_move(self, text: str) -> chess.Move:
        """Turn user text into a legal move, or raise ValueError with a helpful message."""
        text = text.strip()
        if not text:
            raise ValueError("Please type a move, for example e4 or Nf3.")
        if self.board.is_game_over(claim_draw=False):
            raise ValueError("The game is over. Type 'undo' to take a move back, or 'quit'.")

        candidates = [text]
        compact = text.replace(" ", "")
        if compact != text:
            candidates.append(compact)
        if compact.replace("0", "O") != compact:
            candidates.append(compact.replace("0", "O"))
        if compact[0].lower() in "nbrqk":
            candidates.append(compact[0].upper() + compact[1:])
        if compact.lower() in ("o-o", "o-o-o"):
            candidates.append(compact.upper())

        last_error: Exception | None = None
        for candidate in candidates:
            try:
                return self.board.parse_san(candidate)
            except chess.AmbiguousMoveError:
                raise ValueError(
                    f"'{text}' is ambiguous - more than one piece can do that. "
                    "Add the starting file or rank, like Nbd2."
                )
            except ValueError as error:
                last_error = error
            try:
                move = chess.Move.from_uci(candidate.lower())
                if move in self.board.legal_moves:
                    return move
            except ValueError:
                pass

        raise ValueError(f"'{text}' is not a legal move in this position.") from last_error

    def push_text(self, text: str) -> str:
        """Play a move given as text. Returns the SAN of the move played."""
        move = self.parse_move(text)
        san = self.board.san(move)
        self.board.push(move)
        return san

    def push_move(self, move: chess.Move) -> str:
        """Play an already-parsed legal move (e.g. one inferred from the camera). Returns SAN."""
        san = self.board.san(move)
        self.board.push(move)
        return san

    def undo(self) -> str | None:
        if not self.board.move_stack:
            return None
        move = self.board.pop()
        return move.uci()

    def san_history(self) -> list[str]:
        replay = chess.Board(self.start_fen) if self.start_fen else chess.Board()
        out = []
        for move in self.board.move_stack:
            out.append(replay.san(move))
            replay.push(move)
        return out

    def history_text(self) -> str:
        sans = self.san_history()
        if not sans:
            return "(no moves yet)"
        chunks = []
        for i in range(0, len(sans), 2):
            pair = " ".join(sans[i : i + 2])
            chunks.append(f"{i // 2 + 1}. {pair}")
        return " ".join(chunks)

    def render(self) -> str:
        """ASCII board from the user's point of view."""
        rows = []
        ranks = range(7, -1, -1) if self.user_color == chess.WHITE else range(8)
        files = range(8) if self.user_color == chess.WHITE else range(7, -1, -1)
        for rank in ranks:
            cells = []
            for file in files:
                piece = self.board.piece_at(chess.square(file, rank))
                cells.append(piece.symbol() if piece else ".")
            rows.append(f"{rank + 1}  " + " ".join(cells))
        letters = "abcdefgh" if self.user_color == chess.WHITE else "hgfedcba"
        rows.append("   " + " ".join(letters))
        return "\n".join(rows)

    def result_text(self) -> str | None:
        outcome = self.board.outcome(claim_draw=True)
        if outcome is None:
            return None
        if outcome.winner is None:
            return f"Draw ({outcome.termination.name.replace('_', ' ').lower()})."
        who = "You win" if outcome.winner == self.user_color else "You lose"
        return f"{outcome.termination.name.capitalize()}. {who}."
