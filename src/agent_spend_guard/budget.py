"""Budgets and the running ledger.

The single design commitment here: **the estimate is checked before the call, never after.**
Every existing tool in this space observes spend — LiteLLM, Langfuse, Phoenix, Helicone all
tell you accurately what you spent. Watching an agent burn four thousand dollars is not the
same as stopping it, and the difference is entirely whether the check runs first.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Budget:
    """The ceilings for one agent run.

    `hard_usd`
        The run stops here. Not a target, not an alert — a stop.
    `soft_usd`
        Where graceful degradation starts. Defaults to 70% of hard, which leaves enough
        headroom for the cheaper tiers to actually finish the work.
    `max_calls`
        Step ceiling. Catches loops that are individually cheap and collectively not.
    `max_fanout`
        Ceiling on branches from a single step. A fan-out of 8 with a 2% failure rate is a
        different reliability problem, but it is the same cost problem.
    `max_wall_clock_s`
        Runs that stall still accrue. Sixty-three hours is a long time to not notice.
    """

    hard_usd: float
    soft_usd: float | None = None
    max_calls: int = 100
    max_fanout: int = 8
    max_wall_clock_s: float = 3600.0

    def __post_init__(self) -> None:
        if self.hard_usd <= 0:
            raise ValueError("hard_usd must be positive")
        if self.soft_usd is not None:
            if self.soft_usd <= 0:
                raise ValueError("soft_usd must be positive")
            if self.soft_usd >= self.hard_usd:
                raise ValueError("soft_usd must be below hard_usd")
        for name in ("max_calls", "max_fanout"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be at least 1")
        if self.max_wall_clock_s <= 0:
            raise ValueError("max_wall_clock_s must be positive")

    @property
    def soft_ceiling(self) -> float:
        return self.soft_usd if self.soft_usd is not None else self.hard_usd * 0.7


@dataclass
class Ledger:
    """What this run has actually spent so far."""

    spent_usd: float = 0.0
    #: Spend authorised but not yet reconciled against actual token counts.
    reserved_usd: float = 0.0
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    started_at: float = 0.0
    by_model: dict[str, float] = field(default_factory=dict)

    @property
    def committed_usd(self) -> float:
        """Spent plus reserved — what a ceiling check must be made against.

        Checking against `spent_usd` alone is how a burst of concurrent calls walks straight
        through a budget: each one sees the pre-burst total and every one is admitted.
        """
        return self.spent_usd + self.reserved_usd

    def reserve(self, amount: float) -> None:
        self.reserved_usd += amount

    def settle(self, reserved: float, actual: float, model: str,
               input_tokens: int, output_tokens: int) -> None:
        self.reserved_usd = max(0.0, self.reserved_usd - reserved)
        self.spent_usd += actual
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.by_model[model] = round(self.by_model.get(model, 0.0) + actual, 6)

    def release(self, reserved: float) -> None:
        """Give back a reservation for a call that never happened."""
        self.reserved_usd = max(0.0, self.reserved_usd - reserved)

    def fraction_of(self, budget: Budget) -> float:
        return self.committed_usd / budget.hard_usd if budget.hard_usd else 0.0
