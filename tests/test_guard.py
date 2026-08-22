import pytest

from agent_spend_guard import (
    Attribution,
    Budget,
    BudgetExhausted,
    DegradationLadder,
    FakeClock,
    ListSink,
    PriceTable,
    SpendGuard,
    Tier,
)
from agent_spend_guard.otel import GEN_AI_COST_USD, GEN_AI_RESPONSE_MODEL

MODEL = "claude-opus-5"
IN_TOK, OUT_TOK = 8_000, 1_200


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def sink():
    return ListSink()


def make_guard(clock, sink, **kw):
    budget = kw.pop("budget", Budget(hard_usd=5.0, max_calls=500, max_wall_clock_s=1e9))
    return SpendGuard(
        budget=budget, prices=PriceTable.example(), sink=sink, clock=clock,
        attribution=Attribution(tenant="acme", feature="triage", environment="prod"), **kw
    )


class TestAdmission:
    def test_a_fresh_run_is_full_tier(self, clock, sink):
        with make_guard(clock, sink).run("r") as run:
            decision = run.authorize(MODEL, IN_TOK, OUT_TOK)
            assert decision.allowed
            assert decision.tier is Tier.FULL
            assert decision.model == MODEL
            assert not decision.downgraded

    def test_the_ceiling_is_checked_before_the_call_not_after(self, clock, sink):
        """The property the whole package exists for."""
        guard = make_guard(clock, sink, budget=Budget(hard_usd=0.10, max_wall_clock_s=1e9))
        with guard.run("r") as run:
            decision = run.authorize(MODEL, IN_TOK, OUT_TOK)
            assert not decision.allowed
            assert run.spent_usd == 0.0
            assert "would breach" in decision.reason

    def test_reservations_hold_a_burst_under_the_ceiling(self, clock, sink):
        """Checking against settled spend alone lets a burst walk straight through.

        Five authorisations before any of them completes: every one sees the same zero
        settled spend, so only the reservation can keep the total honest.
        """
        guard = make_guard(clock, sink, budget=Budget(hard_usd=0.50, max_wall_clock_s=1e9))
        with guard.run("r") as run:
            [run.authorize(MODEL, IN_TOK, OUT_TOK) for _ in range(5)]
            assert run.spent_usd == 0.0, "nothing has actually been called yet"
            assert run.ledger.committed_usd <= guard.budget.hard_usd

    def test_without_a_ladder_a_burst_is_refused_rather_than_downgraded(self, clock, sink):
        """With degradation switched off, admission is the only lever left."""
        hard_stop = DegradationLadder(reduced_at=1.0, minimal_at=1.0, advisory_at=1.0,
                                      halt_at=1.0)
        guard = make_guard(clock, sink, ladder=hard_stop,
                           budget=Budget(hard_usd=0.50, max_wall_clock_s=1e9))
        with guard.run("r") as run:
            admitted = [run.authorize(MODEL, IN_TOK, OUT_TOK) for _ in range(5)]
            assert sum(d.allowed for d in admitted) == 2
            assert run.ledger.committed_usd <= guard.budget.hard_usd

    def test_abandon_returns_the_reservation(self, clock, sink):
        with make_guard(clock, sink).run("r") as run:
            decision = run.authorize(MODEL, IN_TOK, OUT_TOK)
            before = run.ledger.reserved_usd
            run.abandon(decision)
            assert run.ledger.reserved_usd < before
            assert run.ledger.reserved_usd == 0.0

    def test_fanout_ceiling(self, clock, sink):
        with make_guard(clock, sink).run("r") as run:
            decision = run.authorize(MODEL, 10, 10, fanout=99)
            assert not decision.allowed
            assert "fan-out" in decision.reason

    def test_fanout_multiplies_the_estimate(self, clock, sink):
        with make_guard(clock, sink).run("r") as run:
            one = run.authorize(MODEL, IN_TOK, OUT_TOK, fanout=1)
            run.abandon(one)
            four = run.authorize(MODEL, IN_TOK, OUT_TOK, fanout=4)
            assert four.estimated_usd == pytest.approx(one.estimated_usd * 4)

    def test_zero_fanout_is_rejected(self, clock, sink):
        with make_guard(clock, sink).run("r") as run, pytest.raises(ValueError):
            run.authorize(MODEL, 10, 10, fanout=0)

    def test_call_ceiling_halts_the_run(self, clock, sink):
        guard = make_guard(clock, sink, budget=Budget(hard_usd=1e6, max_calls=3,
                                                      max_wall_clock_s=1e9))
        with guard.run("r") as run:
            for _ in range(3):
                run.record(run.authorize(MODEL, 100, 100), 100, 100)
            decision = run.authorize(MODEL, 100, 100)
            assert not decision.allowed
            assert "call ceiling" in decision.reason

    def test_wall_clock_ceiling_halts_the_run(self, clock, sink):
        guard = make_guard(clock, sink, budget=Budget(hard_usd=1e6, max_wall_clock_s=60.0))
        with guard.run("r") as run:
            assert run.authorize(MODEL, 100, 100).allowed
            clock.advance(61)
            decision = run.authorize(MODEL, 100, 100)
            assert not decision.allowed
            assert "wall-clock" in decision.reason


class TestDegradation:
    def test_crossing_the_soft_ceiling_downgrades_the_model(self, clock, sink):
        with make_guard(clock, sink).run("r") as run:
            for _ in range(60):
                decision = run.authorize(MODEL, IN_TOK, OUT_TOK)
                if not decision.allowed:
                    break
                if decision.downgraded:
                    assert decision.model != MODEL
                    assert decision.tier is not Tier.FULL
                    return
                run.record(decision, IN_TOK, decision.max_output_tokens)
        pytest.fail("the run never downgraded")

    def test_minimal_tier_halves_the_output_allowance(self, clock, sink):
        with make_guard(clock, sink).run("r") as run:
            for _ in range(200):
                decision = run.authorize(MODEL, IN_TOK, OUT_TOK)
                if not decision.allowed:
                    break
                if decision.tier is Tier.MINIMAL:
                    assert decision.max_output_tokens == OUT_TOK // 2
                    return
                run.record(decision, IN_TOK, decision.max_output_tokens)
        pytest.fail("the run never reached the minimal tier")

    def test_tiers_ratchet_and_never_recover(self, clock, sink):
        """Money already spent cannot be earned back by behaving well afterwards."""
        with make_guard(clock, sink).run("r") as run:
            seen = []
            for _ in range(200):
                decision = run.authorize(MODEL, IN_TOK, OUT_TOK)
                seen.append(decision.tier)
                if not decision.allowed:
                    break
                run.record(decision, IN_TOK, decision.max_output_tokens)
            from agent_spend_guard.ladder import rank
            ranks = [rank(t) for t in seen]
            assert ranks == sorted(ranks), f"tier recovered mid-run: {seen}"

    def test_the_ladder_completes_more_work_than_a_bare_hard_stop(self, clock, sink):
        hard_stop = DegradationLadder(reduced_at=1.0, minimal_at=1.0, advisory_at=1.0,
                                      halt_at=1.0)
        counts = {}
        for label, ladder in (("hard", hard_stop), ("ladder", DegradationLadder())):
            guard = make_guard(FakeClock(), ListSink(), ladder=ladder)
            with guard.run("r") as run:
                for _ in range(500):
                    decision = run.authorize(MODEL, IN_TOK, OUT_TOK)
                    if not decision.allowed:
                        break
                    run.record(decision, IN_TOK, decision.max_output_tokens)
                counts[label] = run.ledger.calls
        assert counts["ladder"] > counts["hard"]

    def test_no_arm_ever_exceeds_the_hard_ceiling(self, clock, sink):
        guard = make_guard(clock, sink)
        with guard.run("r") as run:
            for _ in range(500):
                decision = run.authorize(MODEL, IN_TOK, OUT_TOK)
                if not decision.allowed:
                    break
                run.record(decision, IN_TOK, decision.max_output_tokens)
            assert run.spent_usd <= guard.budget.hard_usd


class TestRecording:
    def test_record_settles_against_actuals(self, clock, sink):
        with make_guard(clock, sink).run("r") as run:
            decision = run.authorize(MODEL, IN_TOK, OUT_TOK)
            # The call came back far cheaper than estimated.
            actual = run.record(decision, 100, 10)
            assert actual < decision.estimated_usd
            assert run.spent_usd == actual
            assert run.ledger.reserved_usd == 0.0

    def test_recording_an_unauthorized_call_is_an_error(self, clock, sink):
        broke = make_guard(clock, sink, budget=Budget(hard_usd=0.001, max_wall_clock_s=1e9))
        with broke.run("broke") as tiny:
            refused = tiny.authorize(MODEL, IN_TOK, OUT_TOK)
        assert not refused.allowed

        with make_guard(clock, sink).run("r") as run, pytest.raises(ValueError,
                                                                    match="not authorized"):
            run.record(refused, 10, 10)

    def test_require_raises_instead_of_refusing(self, clock, sink):
        guard = make_guard(clock, sink, budget=Budget(hard_usd=0.001, max_wall_clock_s=1e9))
        with guard.run("r") as run, pytest.raises(BudgetExhausted):
            run.require(MODEL, IN_TOK, OUT_TOK)

    def test_summary_reports_per_model_spend(self, clock, sink):
        with make_guard(clock, sink).run("r") as run:
            for _ in range(40):
                decision = run.authorize(MODEL, IN_TOK, OUT_TOK)
                if not decision.allowed:
                    break
                run.record(decision, IN_TOK, decision.max_output_tokens)
            summary = run.summary()
            assert summary["calls"] == run.ledger.calls
            assert sum(summary["by_model"].values()) == pytest.approx(run.spent_usd, abs=1e-4)


class TestSpans:
    def test_a_span_is_emitted_per_recorded_call(self, clock, sink):
        with make_guard(clock, sink).run("r") as run:
            run.record(run.authorize(MODEL, IN_TOK, OUT_TOK), IN_TOK, OUT_TOK)
        assert len(sink) == 1

    def test_span_carries_genai_conventions_and_the_cost_extension(self, clock, sink):
        with make_guard(clock, sink).run("r") as run:
            run.record(run.authorize(MODEL, IN_TOK, OUT_TOK), IN_TOK, OUT_TOK)
        attrs = sink.spans[0]["attributes"]
        assert attrs["gen_ai.operation.name"] == "chat"
        assert attrs["gen_ai.provider.name"] == "anthropic"
        assert attrs["gen_ai.request.model"] == MODEL
        assert attrs[GEN_AI_RESPONSE_MODEL] == MODEL
        assert attrs["gen_ai.usage.input_tokens"] == IN_TOK
        assert attrs[GEN_AI_COST_USD] > 0

    def test_span_name_follows_the_operation_model_convention(self, clock, sink):
        with make_guard(clock, sink).run("r") as run:
            run.record(run.authorize(MODEL, IN_TOK, OUT_TOK), IN_TOK, OUT_TOK)
        assert sink.spans[0]["name"] == f"chat {MODEL}"

    def test_span_carries_attribution_tags(self, clock, sink):
        with make_guard(clock, sink).run("r") as run:
            run.record(run.authorize(MODEL, IN_TOK, OUT_TOK), IN_TOK, OUT_TOK)
        attrs = sink.spans[0]["attributes"]
        assert attrs["spend.tenant"] == "acme"
        assert attrs["spend.feature"] == "triage"
        assert attrs["spend.environment"] == "prod"
        assert attrs["spend.run_id"]

    def test_sink_total_agrees_with_the_ledger(self, clock, sink):
        with make_guard(clock, sink).run("r") as run:
            for _ in range(20):
                decision = run.authorize(MODEL, IN_TOK, OUT_TOK)
                if not decision.allowed:
                    break
                run.record(decision, IN_TOK, decision.max_output_tokens)
            assert sink.total_cost() == pytest.approx(run.spent_usd, abs=1e-6)

    def test_a_downgraded_call_records_both_models(self, clock, sink):
        with make_guard(clock, sink).run("r") as run:
            for _ in range(60):
                decision = run.authorize(MODEL, IN_TOK, OUT_TOK)
                if not decision.allowed:
                    break
                run.record(decision, IN_TOK, decision.max_output_tokens)
                if decision.downgraded:
                    attrs = sink.spans[-1]["attributes"]
                    assert attrs["gen_ai.request.model"] == MODEL
                    assert attrs[GEN_AI_RESPONSE_MODEL] != MODEL
                    assert attrs["spend.decision"] == "downgraded"
                    return
        pytest.fail("no downgraded call was recorded")


def test_a_supplied_sink_is_not_discarded_when_empty(clock):
    """Regression: an empty ListSink is falsy, so `sink or NullSink()` silently dropped it."""
    sink = ListSink()
    assert not sink, "this test is meaningless if an empty sink is truthy"
    guard = make_guard(clock, sink)
    assert guard.sink is sink


def test_runs_are_isolated_from_each_other(clock, sink):
    guard = make_guard(clock, sink)
    with guard.run("a") as first:
        first.record(first.authorize(MODEL, IN_TOK, OUT_TOK), IN_TOK, OUT_TOK)
        spent = first.spent_usd
    with guard.run("b") as second:
        assert second.spent_usd == 0.0
        assert second.tier is Tier.FULL
    assert spent > 0
