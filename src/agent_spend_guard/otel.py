"""OpenTelemetry GenAI span emission.

Attribute names follow the GenAI semantic conventions so the spans land in whatever already
consumes OTLP — Langfuse, Phoenix, Datadog, Bedrock AgentCore.

**`gen_ai.cost.usd` is not part of those conventions.** It is this project's extension, and it
exists because the conventions explicitly do not cover cost attribution. It is namespaced under
`gen_ai.` on purpose — that is where a consumer will look for it — but do not mistake it for
something standardised.

The core has no OpenTelemetry dependency. Spans are plain dicts handed to a sink; `OTelSink`
imports the SDK lazily and is available through the `otel` extra.
"""

from __future__ import annotations

from typing import Any, Protocol

# Conventional attribute keys.
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_PROVIDER_NAME = "gen_ai.provider.name"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"

# This project's extensions. Not standardised — see the module docstring.
GEN_AI_COST_USD = "gen_ai.cost.usd"
SPEND_TIER = "spend.tier"
SPEND_RUN_COST_USD = "spend.run.cost_usd"
SPEND_RUN_FRACTION = "spend.run.budget_fraction"
SPEND_DECISION = "spend.decision"


class SpanSink(Protocol):
    def emit(self, span: dict[str, Any]) -> None: ...


class NullSink:
    """Discards everything. The default, so the guard is silent unless you ask."""

    def emit(self, span: dict[str, Any]) -> None:
        return None


class ListSink:
    """Collects spans in memory. What the tests and the demo use."""

    def __init__(self) -> None:
        self.spans: list[dict[str, Any]] = []

    def emit(self, span: dict[str, Any]) -> None:
        self.spans.append(span)

    def total_cost(self) -> float:
        return round(sum(s["attributes"].get(GEN_AI_COST_USD, 0.0) for s in self.spans), 6)

    def __len__(self) -> int:
        return len(self.spans)


class ConsoleSink:
    """One line per call. Useful when you want to watch a run without a collector."""

    def emit(self, span: dict[str, Any]) -> None:
        attrs = span["attributes"]
        print(
            f"{span['name']:<34} "
            f"${attrs.get(GEN_AI_COST_USD, 0.0):>8.4f}  "
            f"run=${attrs.get(SPEND_RUN_COST_USD, 0.0):>8.4f}  "
            f"{attrs.get(SPEND_RUN_FRACTION, 0.0):>5.0%}  "
            f"{attrs.get(SPEND_TIER, '')}"
        )


class OTelSink:
    """Bridges to a real tracer. Requires the `otel` extra."""

    def __init__(self, tracer: Any = None) -> None:
        if tracer is None:
            try:
                from opentelemetry import trace
            except ImportError as exc:  # pragma: no cover - exercised only without the extra
                raise ImportError(
                    "OTelSink needs opentelemetry-api; install agent-spend-guard[otel]"
                ) from exc
            tracer = trace.get_tracer("agent-spend-guard")
        self._tracer = tracer

    def emit(self, span: dict[str, Any]) -> None:
        with self._tracer.start_as_current_span(span["name"]) as otel_span:
            for key, value in span["attributes"].items():
                otel_span.set_attribute(key, value)


def build_span(
    *,
    operation: str,
    provider: str,
    requested_model: str,
    served_model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    tier: str,
    decision: str,
    run_cost_usd: float,
    run_fraction: float,
    attribution: dict[str, str],
) -> dict[str, Any]:
    """Assemble one GenAI-conformant span, plus the cost attributes the conventions omit."""
    return {
        # Conventional span naming: "{operation} {model}".
        "name": f"{operation} {served_model}",
        "attributes": {
            GEN_AI_OPERATION_NAME: operation,
            GEN_AI_PROVIDER_NAME: provider,
            GEN_AI_REQUEST_MODEL: requested_model,
            GEN_AI_RESPONSE_MODEL: served_model,
            GEN_AI_USAGE_INPUT_TOKENS: input_tokens,
            GEN_AI_USAGE_OUTPUT_TOKENS: output_tokens,
            GEN_AI_COST_USD: round(cost_usd, 6),
            SPEND_TIER: tier,
            SPEND_DECISION: decision,
            SPEND_RUN_COST_USD: round(run_cost_usd, 6),
            SPEND_RUN_FRACTION: round(run_fraction, 4),
            **attribution,
        },
    }
