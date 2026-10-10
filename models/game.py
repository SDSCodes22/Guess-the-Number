"""Game state model for Higher or Lower."""

import asyncio
from typing import Optional

from models.duel_series import DuelSeries


class Game:
    """Represents an active Higher or Lower game in a single channel."""

    __slots__ = (
        "mode",
        "target",
        "min_val",
        "max_val",
        "players",
        "current_turn_idx",
        "channel_id",
        "active",
        "chooser",
        "starter_id",
        "timeout_task",
        "series",
    )

    def __init__(
        self,
        mode: str,
        target: int,
        min_val: int,
        max_val: int,
        players: list[int],
        channel_id: int,
        starter_id: int,
        chooser: Optional[int] = None,
        series: Optional[DuelSeries] = None,
    ) -> None:
        self.mode = mode
        self.target = target
        self.min_val = min_val
        self.max_val = max_val
        self.players = players
        self.current_turn_idx = 0
        self.channel_id = channel_id
        self.active = True
        self.chooser = chooser
        self.starter_id = starter_id
        self.timeout_task: Optional[asyncio.Task] = None
        self.series = series
