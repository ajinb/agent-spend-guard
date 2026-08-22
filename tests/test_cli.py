import json

import pytest

from agent_spend_guard.cli import main


@pytest.mark.parametrize("argv", [[], ["demo"], ["tiers"], ["prices"]])
def test_commands_exit_zero_and_print_something(argv, capsys):
    assert main(argv) == 0
    assert capsys.readouterr().out.strip()


@pytest.mark.parametrize("argv", [["demo"], ["tiers"], ["prices"]])
def test_json_output_parses(argv, capsys):
    assert main(argv + ["--json"]) == 0
    assert json.loads(capsys.readouterr().out)


def test_prices_command_prints_the_disclaimer(capsys):
    """Anyone reading prices off this tool must see that they are not authoritative."""
    main(["prices"])
    assert "NOT a billing source of truth" in capsys.readouterr().out


def test_demo_reports_all_three_arms(capsys):
    main(["demo"])
    out = capsys.readouterr().out
    for label in ("no guard", "hard stop only", "ladder"):
        assert label in out


def test_unknown_command_is_rejected():
    with pytest.raises(SystemExit):
        main(["nonsense"])
