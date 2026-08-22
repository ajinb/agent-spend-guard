"""Three controls, one runaway loop.

The agent never converges and always asks for the most capable model. The only variable is
what sits between it and the API.
"""

from agent_spend_guard.sim import runaway_comparison

for arm in runaway_comparison():
    print(f"\n{arm.label}")
    print(f"  calls        {arm.calls}")
    print(f"  spent        ${arm.spent_usd:,.2f}")
    if arm.budget_usd:
        print(f"  budget       ${arm.budget_usd:,.2f}   overrun ${arm.overrun:,.2f}")
    print(f"  models       {arm.models_used}")
    print(f"  stopped by   {arm.stopped_by}")

print(
    "\nObserving spend and controlling it are different products. Every tool in this space "
    "would have reported the first arm accurately, to the cent, while it ran."
)
