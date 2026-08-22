"""agent-spend-guard — cost as a controlled SLI, not a monthly surprise."""

from .attribution import Attribution
from .budget import Budget, Ledger
from .clock import FakeClock
from .guard import BudgetExhausted, CallDecision, Run, SpendGuard
from .ladder import DegradationLadder, Tier
from .otel import ConsoleSink, ListSink, NullSink, OTelSink, SpanSink, build_span
from .prices import ModelPrice, PriceTable, UnknownModel

__version__ = "0.1.0"

__all__ = [
    "Attribution", "Budget", "BudgetExhausted", "CallDecision", "ConsoleSink",
    "DegradationLadder", "FakeClock", "Ledger", "ListSink", "ModelPrice", "NullSink",
    "OTelSink", "PriceTable", "Run", "SpanSink", "SpendGuard", "Tier", "UnknownModel",
    "build_span",
]
