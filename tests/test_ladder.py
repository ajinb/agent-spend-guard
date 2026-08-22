import pytest

from agent_spend_guard.ladder import DegradationLadder, Tier, rank


@pytest.fixture
def ladder():
    return DegradationLadder()


@pytest.mark.parametrize("fraction,expected", [
    (0.0, Tier.FULL), (0.69, Tier.FULL),
    (0.70, Tier.REDUCED), (0.84, Tier.REDUCED),
    (0.85, Tier.MINIMAL), (0.94, Tier.MINIMAL),
    (0.95, Tier.ADVISORY), (0.99, Tier.ADVISORY),
    (1.00, Tier.HALTED), (5.0, Tier.HALTED),
])
def test_thresholds(ladder, fraction, expected):
    assert ladder.tier_for(fraction) is expected


def test_ordering_is_monotonic():
    ranks = [rank(t) for t in (Tier.FULL, Tier.REDUCED, Tier.MINIMAL, Tier.ADVISORY, Tier.HALTED)]
    assert ranks == sorted(ranks)


@pytest.mark.parametrize("tier,may_act", [
    (Tier.FULL, True), (Tier.REDUCED, True), (Tier.MINIMAL, True),
    (Tier.ADVISORY, False), (Tier.HALTED, False),
])
def test_which_tiers_may_act(tier, may_act):
    assert tier.may_act is may_act


def test_only_halted_is_terminal():
    assert Tier.HALTED.is_terminal
    assert not Tier.ADVISORY.is_terminal


@pytest.mark.parametrize("tier,steps", [(Tier.FULL, 0), (Tier.REDUCED, 1), (Tier.MINIMAL, 2)])
def test_downgrade_steps(ladder, tier, steps):
    assert ladder.steps_down(tier) == steps


def test_minimal_also_halves_the_output_allowance(ladder):
    assert ladder.output_multiplier(Tier.FULL) == 1.0
    assert ladder.output_multiplier(Tier.MINIMAL) == 0.5


@pytest.mark.parametrize("tier", [Tier.ADVISORY, Tier.HALTED])
def test_non_acting_tiers_have_no_model_settings(ladder, tier):
    with pytest.raises(ValueError):
        ladder.steps_down(tier)
    with pytest.raises(ValueError):
        ladder.output_multiplier(tier)


def test_thresholds_must_ascend():
    with pytest.raises(ValueError, match="must ascend"):
        DegradationLadder(reduced_at=0.9, minimal_at=0.5)


def test_equal_thresholds_collapse_to_a_hard_stop():
    """Setting every threshold to the ceiling is how you ask for no ladder at all."""
    ladder = DegradationLadder(reduced_at=1.0, minimal_at=1.0, advisory_at=1.0, halt_at=1.0)
    assert ladder.tier_for(0.99) is Tier.FULL
    assert ladder.tier_for(1.0) is Tier.HALTED
