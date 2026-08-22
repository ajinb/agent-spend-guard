"""Offline, deterministic scenarios. No network, no API key, no model."""

from .scenarios import ArmResult, runaway_comparison, tier_walk

__all__ = ["ArmResult", "runaway_comparison", "tier_walk"]
