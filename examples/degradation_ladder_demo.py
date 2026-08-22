"""Watch a run get cheaper instead of dying.

A hard stop alone kills the run mid-task with the money already spent. The ladder trades
capability for headroom on the way down, so the work has a chance to finish inside the budget.
"""

from agent_spend_guard.sim import tier_walk

print(f"{'call':>6}{'tier':>12}{'model':>22}{'spent':>10}{'budget':>9}")
for step in tier_walk():
    print(f"{step.call:>6}{step.tier:>12}{step.model:>22}"
          f"{step.cumulative_usd:>10.4f}{step.fraction:>9.0%}")

print(
    "\nDemotion is mechanical and one-way: a run never climbs back up on money it has "
    "already spent."
)
