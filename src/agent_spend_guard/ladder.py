"""The degradation ladder.

A budget with only a hard stop has one behaviour: the run dies mid-task, having spent all the
money and produced nothing. The ladder buys the useful thing instead — the run gets cheaper as
it gets closer to the ceiling, so the work has a chance to finish inside the budget.

Demotion is mechanical and immediate. **Promotion within a run is impossible**, deliberately:
money already spent cannot be earned back by behaving well afterwards, so a run that has been
demoted stays demoted. (Authority ladders, where good behaviour genuinely should restore
privileges over time, are a different problem with a different shape.)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Tier(str, Enum):
    """What the run is still allowed to do."""

    #: Requested model, full output allowance.
    FULL = "full"
    #: One step down the price ladder.
    REDUCED = "reduced"
    #: Two steps down, and output allowance halved.
    MINIMAL = "minimal"
    #: May still reason, may not act. No tool calls.
    ADVISORY = "advisory"
    #: Nothing further is authorised.
    HALTED = "halted"

    @property
    def may_act(self) -> bool:
        return self in (Tier.FULL, Tier.REDUCED, Tier.MINIMAL)

    @property
    def is_terminal(self) -> bool:
        return self is Tier.HALTED


#: Ordered worst-last, so `max` over this ordering is monotonic demotion.
_ORDER = (Tier.FULL, Tier.REDUCED, Tier.MINIMAL, Tier.ADVISORY, Tier.HALTED)


def rank(tier: Tier) -> int:
    return _ORDER.index(tier)


@dataclass(frozen=True)
class DegradationLadder:
    """Budget fractions at which each tier takes over.

    Defaults trip at 70% (matching the default soft ceiling), 85%, 95% and 100%. The gaps
    narrow on purpose: the closer to the ceiling, the less room there is to be wrong about
    what the next call will cost.
    """

    reduced_at: float = 0.70
    minimal_at: float = 0.85
    advisory_at: float = 0.95
    halt_at: float = 1.00
    #: Model steps down the price ladder per tier.
    downgrade_steps: tuple[int, int, int] = (0, 1, 2)
    #: Output-token multiplier per tier.
    output_scale: tuple[float, float, float] = (1.0, 1.0, 0.5)

    def __post_init__(self) -> None:
        thresholds = (self.reduced_at, self.minimal_at, self.advisory_at, self.halt_at)
        if list(thresholds) != sorted(thresholds):
            raise ValueError("ladder thresholds must ascend")
        if any(t <= 0 for t in thresholds):
            raise ValueError("ladder thresholds must be positive")

    def tier_for(self, fraction: float) -> Tier:
        """The tier a run at this fraction of its hard budget belongs in."""
        if fraction >= self.halt_at:
            return Tier.HALTED
        if fraction >= self.advisory_at:
            return Tier.ADVISORY
        if fraction >= self.minimal_at:
            return Tier.MINIMAL
        if fraction >= self.reduced_at:
            return Tier.REDUCED
        return Tier.FULL

    def steps_down(self, tier: Tier) -> int:
        if not tier.may_act:
            raise ValueError(f"{tier.value} does not run models")
        return self.downgrade_steps[rank(tier)]

    def output_multiplier(self, tier: Tier) -> float:
        if not tier.may_act:
            raise ValueError(f"{tier.value} does not run models")
        return self.output_scale[rank(tier)]
