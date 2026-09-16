"""List prices per million tokens, for the cost figure stored next to every
model output. Update when Anthropic changes pricing; the stored cost is an
estimate for visibility, not a bill.

Cache writes cost 1.25x input, cache reads 0.1x input. Batch API halves
everything.
"""

from __future__ import annotations

PRICES = {
    # model: (input, output) USD per 1M tokens
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def cost_usd(model: str, usage, batch: bool) -> float | None:
    p = PRICES.get(model)
    if p is None:
        return None
    inp, out = p
    tokens_in = getattr(usage, "input_tokens", 0) or 0
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cr = getattr(usage, "cache_read_input_tokens", 0) or 0
    tokens_out = getattr(usage, "output_tokens", 0) or 0
    total = (tokens_in * inp + cw * inp * 1.25 + cr * inp * 0.1 + tokens_out * out) / 1e6
    return total * (0.5 if batch else 1.0)


def usage_dict(usage) -> dict:
    return {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
    }
