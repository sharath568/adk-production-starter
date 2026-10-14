"""Token and cost tally for one process, with an optional hard cap for eval runs.

Off by default: the cap only applies when EVAL_COST_CAP_USD is set, so a production server never
raises from here. Prices are USD per 1M tokens (Vertex AI, standard tier, checked October 2026).
Check current pricing before relying on them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

PRICES = {  # model prefix: (input, output)
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
}


class BudgetExceeded(RuntimeError):
    pass


def price(model: str) -> tuple[float, float]:
    """Longest matching prefix; an unknown model is priced like the most expensive one listed."""
    match = max((k for k in PRICES if (model or "").startswith(k)), key=len, default=None)
    return PRICES[match] if match else max(PRICES.values())


@dataclass
class Tally:
    calls: int = 0
    by_model: dict[str, list[int]] = field(default_factory=dict)  # model -> [input, output]

    def usd(self) -> float:
        return sum(i / 1e6 * price(m)[0] + o / 1e6 * price(m)[1] for m, (i, o) in self.by_model.items())


TALLY = Tally()


def cap_usd() -> float | None:
    v = os.getenv("EVAL_COST_CAP_USD")
    return float(v) if v else None


def record(meta, model: str) -> None:
    if meta is None:
        return
    io = TALLY.by_model.setdefault(model, [0, 0])
    io[0] += meta.prompt_token_count or 0
    io[1] += (meta.candidates_token_count or 0) + (getattr(meta, "thoughts_token_count", 0) or 0)
    TALLY.calls += 1
    cap = cap_usd()
    if cap is not None and TALLY.usd() > cap:
        raise BudgetExceeded(f"spend ${TALLY.usd():.4f} is over EVAL_COST_CAP_USD=${cap:.2f}")
