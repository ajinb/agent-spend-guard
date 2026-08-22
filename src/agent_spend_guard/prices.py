"""The price table.

Prices are **data, never code**. They ship as JSON with an `as_of` date and a `source` URL on
every entry, because a hardcoded price is a lie with a half-life — and a cost guard built on a
stale number fails in the direction that costs money.

The bundled table is explicitly illustrative. Point `PriceTable.from_file()` at your own
negotiated rates before using any of this to make a money decision.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

MTOK = 1_000_000


class UnknownModel(KeyError):
    """Raised when a model has no price entry.

    Deliberately fatal rather than defaulting to zero. A guard that silently prices an unknown
    model at nothing is worse than no guard: it reports a budget as healthy while it drains.
    """


@dataclass(frozen=True)
class ModelPrice:
    model: str
    provider: str
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    as_of: str
    source: str

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts cannot be negative")
        return (
            input_tokens * self.input_usd_per_mtok
            + output_tokens * self.output_usd_per_mtok
        ) / MTOK


@dataclass(frozen=True)
class PriceTable:
    prices: dict[str, ModelPrice]
    #: Most to least capable. The degradation ladder walks down this list.
    degradation_order: tuple[str, ...]
    note: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> PriceTable:
        prices = {}
        for entry in data["models"]:
            price = ModelPrice(**{k: v for k, v in entry.items()})
            prices[price.model] = price

        order = tuple(data.get("degradation_order", ()))
        unknown = [m for m in order if m not in prices]
        if unknown:
            raise ValueError(f"degradation_order names unpriced models: {unknown}")

        return cls(prices=prices, degradation_order=order, note=data.get("note", ""))

    @classmethod
    def from_file(cls, path: Path | str) -> PriceTable:
        return cls.from_dict(json.loads(Path(path).read_text()))

    @classmethod
    def example(cls) -> PriceTable:
        """The bundled illustrative table. Not for billing decisions."""
        return cls.from_file(_bundled_path())

    def get(self, model: str) -> ModelPrice:
        try:
            return self.prices[model]
        except KeyError as exc:
            raise UnknownModel(
                f"no price for {model!r}; known models: {sorted(self.prices)}"
            ) from exc

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        return self.get(model).cost(input_tokens, output_tokens)

    def cheaper_than(self, model: str) -> str | None:
        """The next model down the degradation ladder, or None at the bottom."""
        if model not in self.degradation_order:
            return None
        index = self.degradation_order.index(model)
        if index + 1 >= len(self.degradation_order):
            return None
        return self.degradation_order[index + 1]

    @property
    def stalest(self) -> str:
        return min(p.as_of for p in self.prices.values())


def _bundled_path() -> Path:
    here = Path(__file__).resolve()
    for candidate in (
        here.parents[2] / "prices" / "example-prices.json",
        here.parent / "prices" / "example-prices.json",
    ):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("could not locate prices/example-prices.json")
