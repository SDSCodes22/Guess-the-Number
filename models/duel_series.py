"""Score state for a first-to duel challenge."""


class DuelSeries:
    """Tracks scores and starting-player order across a challenge."""

    __slots__ = ("players", "target_score", "scores", "first_player_idx")

    def __init__(
        self,
        players: tuple[int, int],
        target_score: int,
    ) -> None:
        self.players = players
        self.target_score = target_score
        self.scores = {player_id: 0 for player_id in players}
        self.first_player_idx = 0
