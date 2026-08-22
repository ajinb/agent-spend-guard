import pytest

from agent_spend_guard.prices import ModelPrice, PriceTable, UnknownModel


@pytest.fixture
def table():
    return PriceTable.example()


def _price(**kw):
    base = {
        "model": "m", "provider": "p", "input_usd_per_mtok": 10.0,
        "output_usd_per_mtok": 30.0, "as_of": "2026-08-01", "source": "https://example.test",
    }
    base.update(kw)
    return ModelPrice(**base)


def test_cost_is_per_million_tokens():
    assert _price().cost(1_000_000, 0) == 10.0
    assert _price().cost(0, 1_000_000) == 30.0
    assert _price().cost(500_000, 500_000) == 20.0


def test_zero_tokens_is_free():
    assert _price().cost(0, 0) == 0.0


def test_negative_tokens_are_rejected():
    with pytest.raises(ValueError):
        _price().cost(-1, 0)


def test_bundled_table_loads(table):
    assert "claude-opus-5" in table.prices
    assert table.degradation_order[0] == "claude-opus-5"


def test_every_bundled_entry_is_dated_and_sourced(table):
    """A price without provenance is a number someone will trust and should not."""
    for price in table.prices.values():
        assert price.as_of
        assert price.source.startswith("https://")


def test_bundled_table_says_it_is_not_authoritative(table):
    assert "NOT a billing source of truth" in table.note


def test_unknown_model_raises_rather_than_defaulting_to_zero(table):
    """Pricing an unknown model at zero reports a draining budget as healthy."""
    with pytest.raises(UnknownModel):
        table.cost("gpt-nonexistent", 100, 100)


def test_degradation_walks_down_then_stops(table):
    assert table.cheaper_than("claude-opus-5") == "claude-sonnet-5"
    assert table.cheaper_than("claude-sonnet-5") == "claude-haiku-4-5"
    assert table.cheaper_than("claude-haiku-4-5") is None


def test_cheaper_than_an_unlisted_model_is_none(table):
    assert table.cheaper_than("not-in-the-order") is None


def test_degradation_order_must_be_priced():
    with pytest.raises(ValueError, match="unpriced models"):
        PriceTable.from_dict({
            "models": [{"model": "a", "provider": "p", "input_usd_per_mtok": 1.0,
                        "output_usd_per_mtok": 1.0, "as_of": "2026-01-01",
                        "source": "https://x.test"}],
            "degradation_order": ["a", "ghost"],
        })


def test_cheaper_models_really_are_cheaper(table):
    """The ladder is only useful if walking down it actually saves money."""
    costs = [table.cost(m, 10_000, 1_000) for m in table.degradation_order]
    assert costs == sorted(costs, reverse=True)
