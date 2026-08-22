"""The scenarios must keep making the claims the README makes."""

import pytest

from agent_spend_guard.sim import runaway_comparison, tier_walk


@pytest.fixture(scope="module")
def arms():
    return runaway_comparison()


def test_three_arms(arms):
    assert [a.label for a in arms] == ["no guard", "hard stop only", "ladder"]


def test_the_unguarded_arm_massively_overspends(arms):
    unguarded, _, ladder = arms
    assert unguarded.spent_usd > 8 * ladder.budget_usd


def test_both_guarded_arms_stay_under_the_ceiling(arms):
    for arm in arms[1:]:
        assert arm.spent_usd <= arm.budget_usd
        assert arm.overrun == 0.0


def test_the_ladder_does_more_work_for_the_same_money(arms):
    _, hard_stop, ladder = arms
    assert ladder.calls > hard_stop.calls
    assert ladder.spent_usd <= hard_stop.budget_usd


def test_the_hard_stop_arm_never_leaves_the_expensive_model(arms):
    assert set(arms[1].models_used) == {"claude-opus-5"}


def test_the_ladder_arm_uses_progressively_cheaper_models(arms):
    assert len(arms[2].models_used) > 1


def test_the_curve_is_monotonic(arms):
    for arm in arms:
        assert list(arm.curve) == sorted(arm.curve)


def test_scenarios_are_deterministic():
    assert runaway_comparison() == runaway_comparison()
    assert tier_walk() == tier_walk()


class TestTierWalk:
    def test_it_starts_full_and_ends_stopped(self):
        steps = tier_walk()
        assert steps[0].tier == "full"
        assert steps[-1].tier in ("advisory", "halted")

    def test_every_tier_transition_is_downward(self):
        from agent_spend_guard.ladder import Tier, rank
        ranks = [rank(Tier(s.tier)) for s in tier_walk()]
        assert ranks == sorted(ranks)
        assert len(set(ranks)) > 2, "the walk should pass through several tiers"

    def test_spend_only_rises(self):
        spend = [s.cumulative_usd for s in tier_walk()]
        assert spend == sorted(spend)
