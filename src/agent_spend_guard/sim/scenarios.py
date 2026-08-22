"""A runaway agent, run three ways.

The agent is the same in all three arms: a loop that never converges, asking for the most
capable model every time, 8,000 input and 1,200 output tokens per call. Only the control
around it changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..attribution import Attribution
from ..budget import Budget
from ..clock import FakeClock
from ..guard import SpendGuard
from ..ladder import DegradationLadder
from ..otel import ListSink
from ..prices import PriceTable

MODEL = "claude-opus-5"
INPUT_TOKENS = 8_000
OUTPUT_TOKENS = 1_200
SECONDS_PER_CALL = 12.0


@dataclass(frozen=True)
class ArmResult:
    """One arm of the comparison."""

    label: str
    calls: int
    spent_usd: float
    budget_usd: float | None
    stopped_by: str
    curve: tuple[float, ...]
    models_used: dict[str, int]

    @property
    def overrun(self) -> float:
        if self.budget_usd is None:
            return 0.0
        return max(0.0, self.spent_usd - self.budget_usd)


def _unguarded(steps: int, prices: PriceTable) -> ArmResult:
    """No control at all. This is what every incident in the wild was running."""
    per_call = prices.cost(MODEL, INPUT_TOKENS, OUTPUT_TOKENS)
    curve = tuple(round(per_call * (n + 1), 6) for n in range(steps))
    return ArmResult(
        label="no guard", calls=steps, spent_usd=round(per_call * steps, 6), budget_usd=None,
        stopped_by="nothing — the loop ended because the demo did",
        curve=curve, models_used={MODEL: steps},
    )


def _guarded(steps: int, prices: PriceTable, budget: Budget,
             ladder: DegradationLadder, label: str) -> ArmResult:
    clock = FakeClock()
    guard = SpendGuard(
        budget=budget, prices=prices, ladder=ladder, sink=ListSink(), clock=clock,
        attribution=Attribution(tenant="acme", feature="incident-triage", environment="prod"),
    )

    curve: list[float] = []
    models: dict[str, int] = {}
    stopped_by = "loop finished inside budget"

    with guard.run("runaway-triage") as run:
        for _ in range(steps):
            decision = run.authorize(MODEL, INPUT_TOKENS, OUTPUT_TOKENS)
            if not decision.allowed:
                stopped_by = decision.reason
                break
            run.record(decision, INPUT_TOKENS, decision.max_output_tokens)
            models[decision.model] = models.get(decision.model, 0) + 1
            curve.append(round(run.spent_usd, 6))
            clock.advance(SECONDS_PER_CALL)

        return ArmResult(
            label=label, calls=run.ledger.calls, spent_usd=run.spent_usd,
            budget_usd=budget.hard_usd, stopped_by=stopped_by,
            curve=tuple(curve), models_used=models,
        )


def runaway_comparison(steps: int = 200, hard_usd: float = 5.0) -> list[ArmResult]:
    """The same non-converging loop under no control, a hard stop, and the full ladder."""
    prices = PriceTable.example()
    budget = Budget(hard_usd=hard_usd, max_calls=steps + 1, max_wall_clock_s=1e9)

    # A hard stop and nothing else: every threshold sits at the ceiling, so the run stays on
    # the expensive model right up until it dies.
    hard_stop_only = DegradationLadder(
        reduced_at=1.0, minimal_at=1.0, advisory_at=1.0, halt_at=1.0
    )

    return [
        _unguarded(steps, prices),
        _guarded(steps, prices, budget, hard_stop_only, "hard stop only"),
        _guarded(steps, prices, budget, DegradationLadder(), "ladder"),
    ]


@dataclass(frozen=True)
class TierStep:
    call: int
    tier: str
    model: str
    cumulative_usd: float
    fraction: float


def tier_walk(steps: int = 200, hard_usd: float = 5.0) -> list[TierStep]:
    """Every point at which the ladder changed what the agent was allowed to do."""
    prices = PriceTable.example()
    clock = FakeClock()
    guard = SpendGuard(
        budget=Budget(hard_usd=hard_usd, max_calls=steps + 1, max_wall_clock_s=1e9),
        prices=prices, sink=ListSink(), clock=clock,
    )

    transitions: list[TierStep] = []
    previous = None

    with guard.run("tier-walk") as run:
        for n in range(steps):
            decision = run.authorize(MODEL, INPUT_TOKENS, OUTPUT_TOKENS)
            if decision.tier.value != previous:
                transitions.append(TierStep(
                    call=n + 1, tier=decision.tier.value,
                    model=decision.model or "—",
                    cumulative_usd=run.spent_usd, fraction=round(run.fraction, 4),
                ))
                previous = decision.tier.value
            if not decision.allowed:
                break
            run.record(decision, INPUT_TOKENS, decision.max_output_tokens)
            clock.advance(SECONDS_PER_CALL)

    return transitions
