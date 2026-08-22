"""agent-spend-guard command-line interface."""

from __future__ import annotations

import argparse
import json
import sys

from .prices import PriceTable
from .sim import runaway_comparison, tier_walk


def cmd_demo(args) -> int:
    arms = runaway_comparison()
    if args.json:
        print(json.dumps([{**a.__dict__, "curve": list(a.curve)} for a in arms], indent=2))
        return 0

    print("agent-spend-guard — one non-converging agent loop, 200 steps, $5.00 ceiling\n")
    print(f"{'control':<18}{'calls':>7}{'spent':>10}{'over':>8}  stopped by")
    for arm in arms:
        budget = f"${arm.spent_usd:,.2f}"
        over = f"${arm.overrun:,.2f}" if arm.budget_usd else "—"
        print(f"{arm.label:<18}{arm.calls:>7}{budget:>10}{over:>8}  {arm.stopped_by[:44]}")

    ladder = arms[-1]
    hard = arms[1]
    print(f"\nThe ladder does {ladder.calls / hard.calls:.1f}x the work of a bare hard stop "
          f"for the same money — it gets cheaper instead of dying.")
    print(f"models served: {ladder.models_used}")
    return 0


def cmd_tiers(args) -> int:
    steps = tier_walk()
    if args.json:
        print(json.dumps([s.__dict__ for s in steps], indent=2))
        return 0
    print("tier transitions over one run\n")
    print(f"{'call':>6}{'tier':>12}{'model':>22}{'spent':>10}{'budget':>9}")
    for step in steps:
        print(f"{step.call:>6}{step.tier:>12}{step.model:>22}"
              f"{step.cumulative_usd:>10.4f}{step.fraction:>9.0%}")
    return 0


def cmd_prices(args) -> int:
    table = PriceTable.example()
    if args.json:
        print(json.dumps({m: p.__dict__ for m, p in table.prices.items()}, indent=2))
        return 0

    print(f"{'model':<24}{'provider':<12}{'in $/Mtok':>11}{'out $/Mtok':>12}{'as of':>12}")
    for model in table.degradation_order:
        p = table.get(model)
        print(f"{p.model:<24}{p.provider:<12}{p.input_usd_per_mtok:>11.2f}"
              f"{p.output_usd_per_mtok:>12.2f}{p.as_of:>12}")
    print(f"\ndegradation order: {' -> '.join(table.degradation_order)}")
    print(f"\n{table.note}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="machine-readable output")

    parser = argparse.ArgumentParser(
        prog="agent-spend-guard",
        description="A runtime spend circuit breaker for agent trajectories. Demos run offline.",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("demo", parents=[common], help="three controls, one runaway loop (default)")
    sub.add_parser("tiers", parents=[common], help="watch the degradation ladder step down")
    sub.add_parser("prices", parents=[common], help="show the bundled example price table")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.json = getattr(args, "json", False)
    handlers = {"demo": cmd_demo, "tiers": cmd_tiers, "prices": cmd_prices, None: cmd_demo}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
