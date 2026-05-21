import threading
from dataclasses import dataclass


# Pricing per 1M tokens (USD) as of 2026
PRICING = {
    "gemini-2.5-flash": {"input": 0.10, "output": 0.40},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
}


@dataclass
class CallRecord:
    label: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        p = PRICING.get(self.model, {"input": 0, "output": 0})
        return (self.input_tokens * p["input"] + self.output_tokens * p["output"]) / 1_000_000


class TokenTracker:
    def __init__(self):
        self._calls: list[CallRecord] = []
        self._lock = threading.Lock()

    def track_gemini(self, label: str, response) -> None:
        u = response.usage_metadata
        record = CallRecord(
            label=label,
            model="gemini-2.5-flash",
            input_tokens=getattr(u, "prompt_token_count", 0),
            output_tokens=getattr(u, "candidates_token_count", 0),
        )
        with self._lock:
            self._calls.append(record)

    def track_claude(self, label: str, response) -> None:
        u = response.usage
        record = CallRecord(
            label=label,
            model="claude-sonnet-4-6",
            input_tokens=getattr(u, "input_tokens", 0),
            output_tokens=getattr(u, "output_tokens", 0),
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0),
        )
        with self._lock:
            self._calls.append(record)

    def summary(self) -> None:
        if not self._calls:
            return
        print("\n── Token Usage ──────────────────────────────────────────────────────")
        for c in self._calls:
            cache = f"  cache={c.cache_read_tokens:,}" if c.cache_read_tokens else ""
            print(f"  {c.label:<42} {c.model:<22} "
                  f"in={c.input_tokens:>8,}  out={c.output_tokens:>6,}{cache}  "
                  f"${c.cost_usd:.4f}")
        total_cost = sum(c.cost_usd for c in self._calls)
        total_in   = sum(c.input_tokens for c in self._calls)
        total_out  = sum(c.output_tokens for c in self._calls)
        print(f"  {'TOTAL':<42} {'':22} "
              f"in={total_in:>8,}  out={total_out:>6,}  ${total_cost:.4f}")
        print("─────────────────────────────────────────────────────────────────────\n")
