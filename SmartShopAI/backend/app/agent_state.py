from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentTurnRequest:
    session_id: str
    message: str
    image_id: str | None = None
    current_product_id: str | None = None
    cart_context: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentTurnState:
    request: AgentTurnRequest
    chat_history: list[dict[str, str]] = field(default_factory=list)
    conversation_state: dict[str, Any] = field(default_factory=dict)
    turn_plan: Any | None = None
    parsed_turn: Any | None = None
