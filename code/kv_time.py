"""Time-aware prefix-cache simulation on the Mooncake FAST'25 traces.

Adds the two things the pure reuse simulation leaves out: requests hold their
KV while they are in flight (pinned, not evictable), and arrivals overlap so
capacity pressure depends on concurrency.

Parameters are declared, not hidden: prefill throughput and per-token decode
latency are swept and reported.
"""

import json
import os

from collections import OrderedDict

BLOCK_TOKENS = 512


class PinLRU:
    name = "LRU"

    def __init__(self, capacity):
        self.cap = capacity
        self.table = {}  # key -> pin count
        self.unpinned = OrderedDict()

    def __len__(self):
        return len(self.table)

    def __contains__(self, key):
        return key in self.table

    def touch(self, key):
        if key in self.unpinned:
            self.unpinned.move_to_end(key)

    def insert(self, key):
        self.table[key] = 0
        self.unpinned[key] = None

    def pin(self, key):
        if key not in self.table:
            return
        self.table[key] = self.table[key] + 1
        self.unpinned.pop(key, None)

    def unpin(self, key):
        count = self.table.get(key)
        if count is None:
            return
        count -= 1
        self.table[key] = count
        if count <= 0:
            self.unpinned[key] = None

    def evictable(self):
        return bool(self.unpinned)

    def evict(self):
        key, _ = self.unpinned.popitem(last=False)
        del self.table[key]
        return key


class PinSIEVE(PinLRU):
    name = "SIEVE"

    def __init__(self, capacity):
        super().__init__(capacity)
        self.flag = {}
        self.hand = None
        self.order = []  # insertion order, oldest first
        self.alive = set()

    def insert(self, key):
        super().insert(key)
        self.order.append(key)
        self.flag[key] = 0
        self.alive.add(key)

    def touch(self, key):
        self.flag[key] = 1

    def evict(self):
        i = self.hand if self.hand is not None else 0
        while True:
            if i >= len(self.order):
                i = 0
            key = self.order[i]
            if key not in self.alive:
                i += 1
                continue
            if self.table.get(key, 0) > 0:
                i += 1
                continue
            if self.flag.get(key, 0):
                self.flag[key] = 0
                i += 1
                continue
            self.hand = i + 1
            self.alive.discard(key)
            del self.table[key]
            self.unpinned.pop(key, None)
            self.flag.pop(key, None)
            return key


def load(path):
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            rows.append(json.loads(line))
    return rows


def simulate(rows, policy_cls, capacity, prefill_rate, decode_ms):
    """prefill_rate in tokens/ms a single request can compute; decode_ms per token."""
    import heapq

    policy = policy_cls(capacity)
    active = []
    counter = 0
    reused_tokens = 0
    computed_tokens = 0
    input_tokens = 0
    evictions = 0
    denied = 0
    peak = 0

    for row in rows:
        ts = row["timestamp"]
        while active and active[0][0] <= ts:
            _, _, chain = heapq.heappop(active)
            for block in chain:
                policy.unpin(block)
        chain = row["hash_ids"]
        input_len = row["input_length"]
        out_len = row["output_length"]
        tokens_per_block = max(1, int(round(input_len / float(len(chain)))))
        prefix = 0
        for block in chain:
            if block in policy:
                policy.touch(block)
                prefix += 1
            else:
                break
        gain = min(input_len, prefix * tokens_per_block)
        reused_tokens += gain
        input_tokens += input_len
        computed_tokens += max(0, input_len - gain)
        need = len(chain)
        if need > capacity:
            denied += 1
            continue
        for block in chain[prefix:]:
            if block in policy:
                policy.touch(block)
                continue
            while len(policy) >= capacity and policy.evictable():
                policy.evict()
                evictions += 1
            if len(policy) >= capacity:
                denied += 1
                break
            policy.insert(block)
        for block in chain:
            policy.pin(block)
        peak = max(peak, len(policy))
        duration = (input_len - gain) / float(prefill_rate) + out_len * decode_ms
        counter += 1
        heapq.heappush(active, (ts + duration, counter, chain))

    return {
        "reuse": reused_tokens / float(input_tokens),
        "computed": computed_tokens,
        "evictions": evictions,
        "denied": denied,
        "peak": peak,
    }


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    files = {
        "conversation": "conversation_trace.jsonl",
        "mooncake": "mooncake.jsonl",
        "toolagent": "toolagent.jsonl",
        "synthetic": "synthetic.jsonl",
    }
    for name, filename in files.items():
        rows = load(os.path.join(here, "kv_traces", filename))
        distinct = len({b for r in rows for b in r["hash_ids"]})
        print("\n=== %s | requests %d | distinct %d" % (name, len(rows), distinct), flush=True)
        for prefill_rate, decode_ms in ((80.0, 20.0), (40.0, 40.0)):
            print("  params prefill=%d tok/ms decode=%d ms/tok" % (prefill_rate, decode_ms))
            for frac in (0.01, 0.05):
                cap = max(1, int(distinct * frac))
                line = "    cap %-6d" % cap
                for cls in (PinLRU, PinSIEVE):
                    out = simulate(rows, cls, cap, prefill_rate, decode_ms)
                    line += " | %s reuse %.4f evict %d deny %d" % (
                        cls.name, out["reuse"], out["evictions"], out["denied"])
                print(line, flush=True)


if __name__ == "__main__":
    main()
