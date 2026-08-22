# agent-spend-guard

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![OTel GenAI](https://img.shields.io/badge/OTel-GenAI_semconv-425cc7.svg)](https://opentelemetry.io/blog/2026/genai-observability/)

> A runtime **spend circuit breaker** for agent trajectories: per-run budgets, fan-out and
> wall-clock caps, a graceful degradation ladder, and the cost attribution the OpenTelemetry
> GenAI conventions leave out.

LiteLLM, Langfuse, Phoenix and Helicone all measure agent spend, accurately, to the cent.
**Watching an agent burn $4,200 in 63 hours is not the same as stopping it.** Every one of
those tools would have reported the runaway below correctly while it ran.

The difference is one ordering decision: the estimate is checked *before* the call, never
after. That is the whole package.

## The 30-second demo (offline, no API key, no model)

```bash
agent-spend-guard demo
```

```
agent-spend-guard — one non-converging agent loop, 200 steps, $5.00 ceiling

control             calls     spent    over  stopped by
no guard              200    $42.00       —  nothing — the loop ended because the demo di
hard stop only         23     $4.83   $0.00  estimated $0.2100 would breach the $5.00 cei
ladder                 77     $4.76   $0.00  95% of budget committed

The ladder does 3.3x the work of a bare hard stop for the same money — it gets cheaper instead of dying.
models served: {'claude-opus-5': 17, 'claude-sonnet-5': 17, 'claude-haiku-4-5': 43}
```

Same agent in all three arms. The only variable is what sits between it and the API.

**The middle row is why a hard stop alone is not enough.** It dies mid-task at call 23 with
the money spent and nothing to show. The ladder gets 3.3× the work out of the same budget by
becoming cheaper as it approaches the ceiling.

## The ladder

```bash
agent-spend-guard tiers
```

```
  call        tier                 model     spent   budget
     1        full         claude-opus-5    0.0000       4%
    18     reduced       claude-sonnet-5    3.5700      72%
    35     minimal      claude-haiku-4-5    4.2840      86%
    78    advisory                     —    4.7570      95%
```

| Tier | At | What the run may do |
|---|---|---|
| `full` | — | Requested model, full output allowance |
| `reduced` | 70% | One step down the price ladder |
| `minimal` | 85% | Two steps down, output allowance halved |
| `advisory` | 95% | May still reason. **May not act** — no tool calls |
| `halted` | 100% | Nothing further is authorised |

Demotion is mechanical and immediate. **Promotion within a run is impossible**, deliberately:
money already spent cannot be earned back by behaving well afterwards. (Authority ladders,
where good behaviour genuinely should restore privileges over time, are a different problem
with a different shape.)

## Using it

```python
from agent_spend_guard import Attribution, Budget, ConsoleSink, SpendGuard

guard = SpendGuard(
    budget=Budget(hard_usd=5.00, max_calls=100, max_fanout=8, max_wall_clock_s=1800),
    attribution=Attribution(tenant="acme", feature="incident-triage", environment="prod"),
    sink=ConsoleSink(),
)

with guard.run("triage-INC-4471") as run:
    while not run.halted:
        decision = run.authorize("claude-opus-5", estimated_input_tokens=8_000,
                                 estimated_output_tokens=1_200)
        if not decision.allowed:
            log.warning("spend guard stopped the run: %s", decision.reason)
            break

        # decision.model may be cheaper than what you asked for.
        response = call_model(decision.model, max_tokens=decision.max_output_tokens)

        run.record(decision, response.input_tokens, response.output_tokens)
```

Two calls per invocation. `authorize` reserves the estimate so a burst of concurrent calls
cannot each read the same pre-burst total and all be admitted; `record` settles the
reservation against actuals. If a call fails, use `run.abandon(decision)` — otherwise the
reservation leaks and the run throttles itself for nothing.

Prefer exceptions? `run.require(...)` raises `BudgetExhausted` instead of returning a refusal.

## Cost attribution

The GenAI semantic conventions standardise model, tokens and latency across six layers.
**They do not cover cost**, and cost attribution across a compound system — one request
fanning out to several models at different prices — stays fragmented. Provider-side
attribution is thinner still: a couple of fixed fields, no arbitrary tags.

So every recorded call emits a conventional span plus the attributes that are missing:

```python
{
  "name": "chat claude-sonnet-5",
  "attributes": {
    "gen_ai.operation.name":       "chat",
    "gen_ai.provider.name":        "anthropic",
    "gen_ai.request.model":        "claude-opus-5",     # what was asked for
    "gen_ai.response.model":       "claude-sonnet-5",   # what the ladder served
    "gen_ai.usage.input_tokens":   8000,
    "gen_ai.usage.output_tokens":  1200,

    "gen_ai.cost.usd":             0.042,               # ← extension, not a convention
    "spend.tier":                  "reduced",
    "spend.decision":              "downgraded",
    "spend.run.cost_usd":          3.612,
    "spend.run.budget_fraction":   0.7224,
    "spend.tenant":                "acme",
    "spend.feature":               "incident-triage",
    "spend.environment":           "prod"
  }
}
```

`gen_ai.cost.usd` is **this project's extension**, namespaced under `gen_ai.` because that is
where a consumer will look for it. Do not mistake it for something standardised — it exists
precisely because the conventions do not cover cost.

The core has no OpenTelemetry dependency. Spans are plain dicts handed to a sink
(`NullSink`, `ListSink`, `ConsoleSink`); `OTelSink` imports the SDK lazily and ships in the
`otel` extra.

## Prices are data, never code

```bash
agent-spend-guard prices
```

Prices live in [`prices/example-prices.json`](prices/example-prices.json) with an `as_of` date
and a `source` URL on every entry. **They are illustrative defaults for the demo, not a
billing source of truth** — a hardcoded price is a lie with a half-life, and a cost guard
built on a stale number fails in the direction that costs money. Point
`PriceTable.from_file()` at your own negotiated rates.

An unknown model raises `UnknownModel` rather than pricing at zero. A guard that silently
prices something at nothing is worse than no guard: it reports a budget as healthy while it
drains.

## Where this sits

Cost is one currency an agent can overspend. Authority is another — `autonomy-budget` applies
the same error-budget semantics to how much an agent is allowed to *do*, rather than how much
it is allowed to *spend*. Same ladder shape, different ledger.

This is also not `cloud-cost-ai`: that one finds anomalies in a cloud bill after the fact.
This is a control loop inside the run, and by the time a bill exists it has already failed.

## Design notes

- **Nothing calls `time` directly.** Clocks are injected, so 105 tests and both demos run in a
  tenth of a second and produce identical output everywhere.
- **Ceilings are checked against committed spend** — settled *plus* reserved. Checking settled
  spend alone is how a burst of concurrent calls walks straight through a budget.
- **Zero runtime dependencies.**

## Status

**v0.1.** The control loop is complete and tested; the demo numbers above are reproduced by
the test suite. Adapters that wrap a real SDK client (so `authorize`/`record` happen without
you writing them) are the v0.2 milestone.

```bash
pytest -q                       # 105 tests
ruff check src tests examples
agent-spend-guard demo
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Prices go through the **Price update** issue template
and must carry a provider-owned source URL.

## License

Apache 2.0. More at [cloudandsre.com](https://cloudandsre.com).
