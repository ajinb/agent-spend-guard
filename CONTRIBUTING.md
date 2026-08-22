# Contributing

Thanks for your interest in agent-spend-guard.

- Run `pip install -e ".[dev]"`, then `pytest -q` and `ruff check src tests examples`.
- **The core takes no runtime dependencies and calls no clock directly.** Time comes in
  through an injectable `clock`; a test that sleeps will be rejected. The OpenTelemetry
  export path is an optional extra and imports lazily.
- **Prices are data, never code.** They live in `prices/example-prices.json`, every entry
  carries `as_of` and `source`, and they are illustrative defaults rather than a billing
  source of truth. Use the **Price update** issue template.
- New ladder tiers go in `ladder.py` with a threshold test in `tests/test_ladder.py`. Keep
  demotion mechanical and promotion impossible mid-run: a run that has spent the money cannot
  earn it back by behaving well afterwards.
- Any change to admission logic must preserve the ceiling property — the estimate is checked
  *before* the call, never after. There is a test that pins this; do not weaken it.
