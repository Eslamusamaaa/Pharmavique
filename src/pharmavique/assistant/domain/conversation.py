"""Conversation memory for follow-up questions ("and the 40 mg one?").

The app keeps the conversation and sends the recent turns back with each question; the server
stores nothing (privacy, and any API process can answer). Before the model sees them, turns are
cleaned: only user and assistant roles, citation marks removed, each turn shortened, only the last
few kept (the free model's tokens per minute are limited), and user turns that try to manipulate
the assistant are dropped, so an old message cannot smuggle instructions in.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from pharmavique.assistant.domain.guardrails import looks_like_injection

MAX_TURNS = 6  # three questions and their answers
MAX_TURN_CHARS = 600
ROLES = ("user", "assistant")
_CITATIONS = re.compile(r"\s*[\[【]\d+[\]】]")


@dataclass(frozen=True, slots=True)
class Turn:
    role: str  # "user" or "assistant"
    text: str

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"a turn's role must be one of {ROLES}")


def prepare_history(turns: Sequence[Turn]) -> tuple[Turn, ...]:
    kept: list[Turn] = []
    for turn in turns:
        text = " ".join(_CITATIONS.sub("", turn.text).split())
        if not text:
            continue
        if turn.role == "user" and looks_like_injection(text):
            continue
        if len(text) > MAX_TURN_CHARS:
            text = text[:MAX_TURN_CHARS].rstrip() + "…"
        kept.append(Turn(turn.role, text))
    return tuple(kept[-MAX_TURNS:])
