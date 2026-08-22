"""Attribution tags.

This is precisely the hole the OpenTelemetry GenAI conventions leave open. They standardise
model, tokens and latency; they do not cover cost, and cost attribution across a compound
system — one request fanning out to several models and tools at different prices — stays
fragmented. Provider-side attribution is worse: a couple of fixed fields, no arbitrary tags,
no `environment=prod`, no `feature=triage`.

So the tags come from you, and travel on every span.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Attribution:
    """Who this spend belongs to."""

    tenant: str | None = None
    feature: str | None = None
    environment: str | None = None
    run_id: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    _RESERVED = ("tenant", "feature", "environment", "run_id")

    def __post_init__(self) -> None:
        clashes = sorted(set(self.extra) & set(self._RESERVED))
        if clashes:
            raise ValueError(f"extra may not shadow reserved keys: {clashes}")

    def as_attributes(self, prefix: str = "spend") -> dict[str, str]:
        """Flatten to span attributes, dropping anything unset."""
        base = {
            f"{prefix}.tenant": self.tenant,
            f"{prefix}.feature": self.feature,
            f"{prefix}.environment": self.environment,
            f"{prefix}.run_id": self.run_id,
        }
        out = {k: v for k, v in base.items() if v is not None}
        out.update({f"{prefix}.{k}": v for k, v in self.extra.items()})
        return out

    def with_run(self, run_id: str) -> Attribution:
        return Attribution(
            tenant=self.tenant, feature=self.feature, environment=self.environment,
            run_id=run_id, extra=dict(self.extra),
        )
