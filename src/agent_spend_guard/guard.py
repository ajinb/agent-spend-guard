"""The guard itself — a control loop over a run's spend.

Two calls per model invocation:

    decision = run.authorize(model, est_input, est_output)   # before you spend anything
    if decision.allowed:
        ...                                                   # make the call
        run.record(decision, input_tokens, output_tokens)     # reconcile with actuals

`authorize` reserves the estimate, so concurrent calls cannot each see the same pre-burst
total and all be admitted. `record` settles the reservation against what actually happened.
Skip `record` on a call that failed and use `abandon` instead, or the reservation leaks and
the run throttles itself for no reason.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from types import TracebackType

from .attribution import Attribution
from .budget import Budget, Ledger
from .ladder import DegradationLadder, Tier, rank
from .otel import NullSink, SpanSink, build_span
from .prices import PriceTable


class BudgetExhausted(RuntimeError):
    """Raised by `require()` when the run may not continue."""


@dataclass(frozen=True)
class CallDecision:
    """The answer to "may I make this call, and on what terms?"."""

    allowed: bool
    tier: Tier
    reason: str
    #: The model you should actually call — possibly a cheaper one than you asked for.
    model: str = ""
    requested_model: str = ""
    max_output_tokens: int = 0
    reservation_usd: float = 0.0
    estimated_usd: float = 0.0

    @property
    def downgraded(self) -> bool:
        return bool(self.model) and self.model != self.requested_model


@dataclass
class Run:
    """One agent trajectory, with a ledger and a tier that only ever ratchets down."""

    name: str
    budget: Budget
    prices: PriceTable
    ladder: DegradationLadder
    attribution: Attribution
    sink: SpanSink
    clock: Callable[[], float]
    ledger: Ledger = field(default_factory=Ledger)
    _tier: Tier = Tier.FULL

    def __post_init__(self) -> None:
        self.ledger.started_at = self.clock()

    # ---- state ----------------------------------------------------------------------

    @property
    def tier(self) -> Tier:
        return self._tier

    @property
    def spent_usd(self) -> float:
        return round(self.ledger.spent_usd, 6)

    @property
    def fraction(self) -> float:
        return self.ledger.fraction_of(self.budget)

    @property
    def elapsed_s(self) -> float:
        return self.clock() - self.ledger.started_at

    @property
    def halted(self) -> bool:
        return self._tier.is_terminal

    def _demote_to(self, tier: Tier) -> Tier:
        """Tiers ratchet: a run never climbs back up on money it has already spent."""
        if rank(tier) > rank(self._tier):
            self._tier = tier
        return self._tier

    def _assess(self) -> tuple[Tier, str]:
        """Re-evaluate the tier against every ceiling. Worst answer wins."""
        if self.ledger.calls >= self.budget.max_calls:
            return Tier.HALTED, f"call ceiling reached ({self.budget.max_calls})"
        if self.elapsed_s >= self.budget.max_wall_clock_s:
            return Tier.HALTED, f"wall-clock ceiling reached ({self.budget.max_wall_clock_s:g}s)"
        tier = self.ladder.tier_for(self.fraction)
        if tier is Tier.HALTED:
            return tier, f"hard budget reached (${self.budget.hard_usd:,.2f})"
        return tier, f"{self.fraction:.0%} of budget committed"

    # ---- the two calls --------------------------------------------------------------

    def authorize(
        self,
        model: str,
        estimated_input_tokens: int,
        estimated_output_tokens: int,
        *,
        fanout: int = 1,
    ) -> CallDecision:
        """Decide before the money is spent. This ordering is the whole point."""
        if fanout < 1:
            raise ValueError("fanout must be at least 1")

        tier, reason = self._assess()
        self._demote_to(tier)
        tier = self._tier

        if fanout > self.budget.max_fanout:
            return CallDecision(
                allowed=False, tier=tier, requested_model=model,
                reason=f"fan-out {fanout} exceeds ceiling {self.budget.max_fanout}",
            )

        if not tier.may_act:
            return CallDecision(allowed=False, tier=tier, requested_model=model, reason=reason)

        served = self._downgrade(model, self.ladder.steps_down(tier))
        max_output = max(1, int(estimated_output_tokens * self.ladder.output_multiplier(tier)))
        estimate = self.prices.cost(served, estimated_input_tokens, max_output) * fanout

        # The ceiling check happens against committed spend — settled plus reserved — so a
        # burst of concurrent authorisations cannot all read the same pre-burst total.
        if self.ledger.committed_usd + estimate > self.budget.hard_usd:
            self._demote_to(Tier.HALTED)
            return CallDecision(
                allowed=False, tier=Tier.HALTED, requested_model=model,
                reason=(f"estimated ${estimate:,.4f} would breach the "
                        f"${self.budget.hard_usd:,.2f} ceiling"),
                estimated_usd=estimate,
            )

        self.ledger.reserve(estimate)
        return CallDecision(
            allowed=True, tier=tier, reason=reason, model=served, requested_model=model,
            max_output_tokens=max_output, reservation_usd=estimate, estimated_usd=estimate,
        )

    def record(
        self, decision: CallDecision, input_tokens: int, output_tokens: int
    ) -> float:
        """Reconcile a completed call against its reservation, and emit a span."""
        if not decision.allowed:
            raise ValueError("cannot record a call that was not authorized")

        price = self.prices.get(decision.model)
        actual = price.cost(input_tokens, output_tokens)
        self.ledger.settle(
            reserved=decision.reservation_usd, actual=actual, model=decision.model,
            input_tokens=input_tokens, output_tokens=output_tokens,
        )

        tier, _ = self._assess()
        self._demote_to(tier)

        self.sink.emit(build_span(
            operation="chat",
            provider=price.provider,
            requested_model=decision.requested_model,
            served_model=decision.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=actual,
            tier=decision.tier.value,
            decision="downgraded" if decision.downgraded else "allowed",
            run_cost_usd=self.ledger.spent_usd,
            run_fraction=self.fraction,
            attribution=self.attribution.as_attributes(),
        ))
        return round(actual, 6)

    def abandon(self, decision: CallDecision) -> None:
        """Release a reservation for a call that never happened."""
        if decision.allowed:
            self.ledger.release(decision.reservation_usd)

    def require(self, model: str, estimated_input_tokens: int,
                estimated_output_tokens: int) -> CallDecision:
        """`authorize`, but raises instead of returning a refusal."""
        decision = self.authorize(model, estimated_input_tokens, estimated_output_tokens)
        if not decision.allowed:
            raise BudgetExhausted(f"{self.name}: {decision.reason}")
        return decision

    def _downgrade(self, model: str, steps: int) -> str:
        current = model
        for _ in range(steps):
            cheaper = self.prices.cheaper_than(current)
            if cheaper is None:
                break
            current = cheaper
        return current

    def summary(self) -> dict[str, object]:
        return {
            "run": self.name,
            "tier": self._tier.value,
            "spent_usd": self.spent_usd,
            "budget_usd": self.budget.hard_usd,
            "fraction": round(self.fraction, 4),
            "calls": self.ledger.calls,
            "input_tokens": self.ledger.input_tokens,
            "output_tokens": self.ledger.output_tokens,
            "by_model": dict(self.ledger.by_model),
        }


class SpendGuard:
    """Factory for runs. Configure once, open a `run()` per trajectory."""

    def __init__(
        self,
        budget: Budget,
        prices: PriceTable | None = None,
        *,
        ladder: DegradationLadder | None = None,
        attribution: Attribution | None = None,
        sink: SpanSink | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.budget = budget
        # `x or Default()` is wrong here: an empty ListSink has __len__ == 0 and is therefore
        # falsy, so `sink or NullSink()` silently throws away a perfectly good sink and the
        # guard goes quiet. Compare against None explicitly.
        self.prices = prices if prices is not None else PriceTable.example()
        self.ladder = ladder if ladder is not None else DegradationLadder()
        self.attribution = attribution if attribution is not None else Attribution()
        self.sink = sink if sink is not None else NullSink()
        self.clock = clock

    def run(self, name: str, *, run_id: str | None = None) -> _RunContext:
        return _RunContext(self, name, run_id or uuid.uuid4().hex[:12])


class _RunContext:
    """`with guard.run("triage") as run:`"""

    def __init__(self, guard: SpendGuard, name: str, run_id: str) -> None:
        self._guard = guard
        self._run = Run(
            name=name,
            budget=guard.budget,
            prices=guard.prices,
            ladder=guard.ladder,
            attribution=guard.attribution.with_run(run_id),
            sink=guard.sink,
            clock=guard.clock,
        )

    def __enter__(self) -> Run:
        return self._run

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        # Suppress nothing; a budget breach that reached `require` is a real error.
        return False
