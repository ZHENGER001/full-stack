from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .agentic_rag import retrieve_products_for_turn
from .bounded_agent_tools import execute_bounded_turn
from .bundle_recommendation import retrieve_bundle_recommendations


ToolHandler = Callable[..., Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    handler: ToolHandler
    route_scope: tuple[str, ...]
    is_mutation: bool = False
    requires_confirmation: bool = False


@dataclass
class ToolRegistry:
    _tools: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown agent tool: {name}") from exc

    def call(self, name: str, **kwargs) -> Any:
        return self.get(name).handler(**kwargs)

    def names(self) -> list[str]:
        return sorted(self._tools)


def build_default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="search_products",
            handler=lambda *, conn, query, known_brands, turn_plan: retrieve_products_for_turn(
                conn,
                query,
                known_brands,
                turn_plan,
            ),
            route_scope=("direct_tool",),
        )
    )
    registry.register(
        ToolSpec(
            name="bounded_agent",
            handler=lambda *, conn, parsed_turn, conversation_state: execute_bounded_turn(
                conn,
                parsed_turn,
                conversation_state,
            ),
            route_scope=("bounded_react",),
            is_mutation=True,
        )
    )
    registry.register(
        ToolSpec(
            name="bundle_recommendation",
            handler=lambda *, conn, message, top_k_per_slot=1, bundle_slots=None: retrieve_bundle_recommendations(
                conn,
                message,
                top_k_per_slot=top_k_per_slot,
                bundle_slots=bundle_slots,
            ),
            route_scope=("direct_tool",),
        )
    )
    return registry


DEFAULT_TOOL_REGISTRY = build_default_tool_registry()
