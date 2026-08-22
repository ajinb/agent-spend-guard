import pytest

from agent_spend_guard.budget import Budget, Ledger


def test_soft_ceiling_defaults_to_seventy_percent():
    assert Budget(hard_usd=10.0).soft_ceiling == 7.0


def test_explicit_soft_ceiling_is_used():
    assert Budget(hard_usd=10.0, soft_usd=2.0).soft_ceiling == 2.0


@pytest.mark.parametrize("kwargs", [
    {"hard_usd": 0},
    {"hard_usd": -1},
    {"hard_usd": 10.0, "soft_usd": 10.0},
    {"hard_usd": 10.0, "soft_usd": 11.0},
    {"hard_usd": 10.0, "max_calls": 0},
    {"hard_usd": 10.0, "max_fanout": 0},
    {"hard_usd": 10.0, "max_wall_clock_s": 0},
])
def test_invalid_budgets_are_rejected(kwargs):
    with pytest.raises(ValueError):
        Budget(**kwargs)


class TestLedger:
    def test_committed_includes_reservations(self):
        ledger = Ledger(spent_usd=1.0)
        ledger.reserve(0.5)
        assert ledger.committed_usd == 1.5

    def test_settle_moves_reservation_to_spend(self):
        ledger = Ledger()
        ledger.reserve(1.0)
        ledger.settle(reserved=1.0, actual=0.8, model="m", input_tokens=10, output_tokens=5)
        assert ledger.reserved_usd == 0.0
        assert ledger.spent_usd == 0.8
        assert ledger.calls == 1
        assert ledger.by_model == {"m": 0.8}

    def test_settle_accumulates_per_model(self):
        ledger = Ledger()
        for _ in range(3):
            ledger.settle(reserved=0.0, actual=0.5, model="m", input_tokens=1, output_tokens=1)
        assert ledger.by_model["m"] == 1.5
        assert ledger.calls == 3

    def test_release_returns_a_reservation(self):
        ledger = Ledger()
        ledger.reserve(2.0)
        ledger.release(2.0)
        assert ledger.reserved_usd == 0.0

    def test_reservations_never_go_negative(self):
        ledger = Ledger()
        ledger.release(5.0)
        assert ledger.reserved_usd == 0.0

    def test_fraction_of_budget(self):
        ledger = Ledger(spent_usd=2.5)
        assert ledger.fraction_of(Budget(hard_usd=10.0)) == 0.25
