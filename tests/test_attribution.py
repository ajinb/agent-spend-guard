import pytest

from agent_spend_guard.attribution import Attribution


def test_unset_fields_are_dropped():
    assert Attribution(tenant="acme").as_attributes() == {"spend.tenant": "acme"}


def test_all_fields_are_prefixed():
    attrs = Attribution(
        tenant="acme", feature="triage", environment="prod", run_id="r1"
    ).as_attributes()
    assert attrs == {
        "spend.tenant": "acme", "spend.feature": "triage",
        "spend.environment": "prod", "spend.run_id": "r1",
    }


def test_extra_tags_are_carried():
    """The arbitrary tags no provider-side attribution gives you."""
    attrs = Attribution(tenant="acme", extra={"team": "sre", "cost_center": "42"})
    assert attrs.as_attributes()["spend.team"] == "sre"
    assert attrs.as_attributes()["spend.cost_center"] == "42"


def test_extra_may_not_shadow_reserved_keys():
    with pytest.raises(ValueError, match="shadow reserved keys"):
        Attribution(extra={"tenant": "sneaky"})


def test_prefix_is_configurable():
    assert "billing.tenant" in Attribution(tenant="a").as_attributes(prefix="billing")


def test_with_run_returns_a_copy():
    original = Attribution(tenant="acme", extra={"team": "sre"})
    stamped = original.with_run("run-1")
    assert stamped.run_id == "run-1"
    assert stamped.tenant == "acme"
    assert stamped.extra == {"team": "sre"}
    assert original.run_id is None
