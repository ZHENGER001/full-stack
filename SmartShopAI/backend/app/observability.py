from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.requests import Request
    from starlette.responses import Response as StarletteResponse

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
except ImportError:  # pragma: no cover - keeps local dev usable before pip install.
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    Counter = None
    Gauge = None
    Histogram = None
    generate_latest = None


METRICS_AVAILABLE = Counter is not None and Gauge is not None and Histogram is not None and generate_latest is not None

if METRICS_AVAILABLE:
    HTTP_REQUESTS_TOTAL = Counter(
        "smartshop_http_requests_total",
        "Total HTTP requests handled by SmartShopAI.",
        ["method", "path", "status"],
    )
    HTTP_REQUEST_DURATION_SECONDS = Histogram(
        "smartshop_http_request_duration_seconds",
        "HTTP request duration in seconds.",
        ["method", "path"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
    )
    AGENT_TURNS_TOTAL = Counter(
        "smartshop_agent_turns_total",
        "Total agent conversation turns.",
    )
    AGENT_ERRORS_TOTAL = Counter(
        "smartshop_agent_errors_total",
        "Total agent turns that emitted an error event.",
    )
    AGENT_FIRST_DELTA_SECONDS = Histogram(
        "smartshop_agent_first_delta_seconds",
        "Seconds until the first streamed delta event in an agent turn.",
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
    )
    AGENT_TOTAL_DURATION_SECONDS = Histogram(
        "smartshop_agent_total_duration_seconds",
        "Total duration of an agent turn in seconds.",
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
    )
    AGENT_RETRIEVED_PRODUCTS_COUNT = Gauge(
        "smartshop_agent_retrieved_products_count",
        "Number of visible products returned by the latest agent retrieval turn.",
    )
    AGENT_CACHE_HITS_TOTAL = Counter(
        "smartshop_agent_cache_hits_total",
        "Total agent turns or generation steps served from cache.",
        ["level"],
    )
    AGENT_CLARIFICATION_TOTAL = Counter(
        "smartshop_agent_clarification_total",
        "Total agent turns that asked a clarification question.",
    )
    AGENT_TOOL_CALLS_TOTAL = Counter(
        "smartshop_agent_tool_calls_total",
        "Total agent tool-like events emitted.",
        ["tool"],
    )
    AGENT_NO_RESULT_TOTAL = Counter(
        "smartshop_agent_no_result_total",
        "Total product-search turns with no visible products or alternatives.",
    )
    ASR_REQUESTS_TOTAL = Counter(
        "smartshop_asr_requests_total",
        "Total ASR transcription requests.",
        ["provider", "status"],
    )
    IMAGE_ANALYZE_TOTAL = Counter(
        "smartshop_image_analyze_total",
        "Total image analysis requests.",
        ["status"],
    )
else:
    HTTP_REQUESTS_TOTAL = None
    HTTP_REQUEST_DURATION_SECONDS = None
    AGENT_TURNS_TOTAL = None
    AGENT_ERRORS_TOTAL = None
    AGENT_FIRST_DELTA_SECONDS = None
    AGENT_TOTAL_DURATION_SECONDS = None
    AGENT_RETRIEVED_PRODUCTS_COUNT = None
    AGENT_CACHE_HITS_TOTAL = None
    AGENT_CLARIFICATION_TOTAL = None
    AGENT_TOOL_CALLS_TOTAL = None
    AGENT_NO_RESULT_TOTAL = None
    ASR_REQUESTS_TOTAL = None
    IMAGE_ANALYZE_TOTAL = None


class AgentTurnMetrics:
    def __init__(self) -> None:
        self.started_at = time.perf_counter()
        self.first_delta_recorded = False
        self.error_recorded = False
        self.clarification_recorded = False
        self.cache_hit_recorded = False
        self.saw_retrieval = False
        self.saw_visible_products = False
        self.visible_product_count = 0
        if METRICS_AVAILABLE:
            AGENT_TURNS_TOTAL.inc()

    def observe_sse_chunk(self, chunk: str) -> None:
        event, payload = _parse_sse_chunk(chunk)
        if not event:
            return

        if event == "delta" and not self.first_delta_recorded:
            self.first_delta_recorded = True
            if METRICS_AVAILABLE:
                AGENT_FIRST_DELTA_SECONDS.observe(time.perf_counter() - self.started_at)

        if event == "error" and not self.error_recorded:
            self.error_recorded = True
            if METRICS_AVAILABLE:
                AGENT_ERRORS_TOTAL.inc()

        if event == "retrieval_status":
            self.saw_retrieval = True
            turn = payload.get("turn") if isinstance(payload, dict) else {}
            if isinstance(turn, dict) and turn.get("needs_clarification"):
                self._record_clarification()
            self._record_tool_call("search_products")

        if event in {"products", "alternatives"}:
            products = payload.get("products") if isinstance(payload, dict) else []
            count = len(products) if isinstance(products, list) else 0
            self.visible_product_count = max(self.visible_product_count, count)
            if count:
                self.saw_visible_products = True

        if event == "llm_status":
            mode = str(payload.get("mode") or payload.get("level") or "") if isinstance(payload, dict) else ""
            if "cache" in mode.lower():
                self._record_cache_hit(mode or "unknown")

        if event == "actions" and not self.saw_visible_products and not self.saw_retrieval:
            self._record_clarification()

        if event in {"cart", "checkout_confirmation", "order_success", "comparison", "batch_cart"}:
            self._record_tool_call(event)

    def finish(self) -> None:
        if not METRICS_AVAILABLE:
            return
        AGENT_TOTAL_DURATION_SECONDS.observe(time.perf_counter() - self.started_at)
        AGENT_RETRIEVED_PRODUCTS_COUNT.set(self.visible_product_count)
        if self.saw_retrieval and not self.saw_visible_products and not self.error_recorded:
            AGENT_NO_RESULT_TOTAL.inc()

    def _record_cache_hit(self, level: str) -> None:
        if self.cache_hit_recorded:
            return
        self.cache_hit_recorded = True
        if METRICS_AVAILABLE:
            AGENT_CACHE_HITS_TOTAL.labels(level or "unknown").inc()

    def _record_clarification(self) -> None:
        if self.clarification_recorded:
            return
        self.clarification_recorded = True
        if METRICS_AVAILABLE:
            AGENT_CLARIFICATION_TOTAL.inc()

    def _record_tool_call(self, tool: str) -> None:
        if METRICS_AVAILABLE:
            AGENT_TOOL_CALLS_TOTAL.labels(tool).inc()


def record_asr_request(provider: str, success: bool) -> None:
    if METRICS_AVAILABLE:
        ASR_REQUESTS_TOTAL.labels(provider or "unknown", "success" if success else "failed").inc()


def record_image_analyze(success: bool) -> None:
    if METRICS_AVAILABLE:
        IMAGE_ANALYZE_TOTAL.labels("success" if success else "failed").inc()


def _parse_sse_chunk(chunk: str) -> tuple[str | None, dict[str, Any]]:
    event: str | None = None
    data_lines: list[str] = []
    for line in chunk.splitlines():
        if line.startswith("event:"):
            event = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
    if not event:
        return None, {}
    data = "\n".join(data_lines).strip()
    if not data:
        return event, {}
    try:
        parsed = json.loads(data)
        return event, parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return event, {}


def install_metrics(app: "FastAPI") -> None:
    from fastapi import Response

    @app.middleware("http")
    async def prometheus_metrics_middleware(
        request: "Request",
        call_next: Callable[["Request"], Awaitable["StarletteResponse"]],
    ) -> "StarletteResponse":
        if not METRICS_AVAILABLE or request.url.path == "/metrics":
            return await call_next(request)

        started_at = time.perf_counter()
        status = "500"
        try:
            response = await call_next(request)
            status = str(response.status_code)
            return response
        finally:
            elapsed = time.perf_counter() - started_at
            path = _route_path(request)
            HTTP_REQUESTS_TOTAL.labels(request.method, path, status).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(request.method, path).observe(elapsed)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        if not METRICS_AVAILABLE:
            return Response(
                "prometheus_client is not installed. Run: pip install -r requirements.txt\n",
                media_type="text/plain",
                status_code=503,
            )
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or request.url.path
