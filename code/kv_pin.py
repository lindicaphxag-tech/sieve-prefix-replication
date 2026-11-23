"""Time-aware ablation: what concurrency pinning costs a prefix cache.

Two runs over the same arrival order:
  pinned   in-flight requests hold their KV, those blocks cannot be evicted
  unpinned every resident block is evictable (the pure reuse model)

The gap is the cost of serving concurrency at a fixed block budget.
"""

import heapq
import json
import os

from collections import OrderedDict

import kv_time


class NoPinLRU(kv_time.PinLRU):
    name = "LRU-nopin"

    def pin(self, key):
        if key not in self.table:
            return
        self.table[key] = 0
        if key not in self.unpinned:
            self.unpinned[key] = None

    def unpin(self, key):
        return None


def simulate(rows, policy_cls, capacity, prefill_rate, decode_ms):
    policy = policy_cls(capacity)
    active = []
    counter = 0
    reused = 0
    input_tokens = 0
    evictions = 0
    denied = 0
    peak_pinned = 0
    pin_ticks = 0

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
        reused += min(input_len, prefix * tokens_per_block)
        input_tokens += input_len
        if len(chain) > capacity:
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
        pinned = sum(1 for count in policy.table.values() if count > 0)
        peak_pinned = max(peak_pinned, pinned)
        pin_ticks += pinned
        duration = (input_len - (prefix * tokens_per_block)) / float(prefill_rate) + out_len * decode_ms
        counter += 1
        heapq.heappush(active, (ts + duration, counter, chain))

    return {
        "reuse": reused / float(input_tokens),
        "evictions": evictions,
        "denied": denied,
        "peak_pinned": peak_pinned,
        "mean_pinned": pin_ticks / float(len(rows)),
    }


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    for name, filename in (("conversation", "conversation_trace.jsonl"),
                           ("mooncake", "mooncake.jsonl")):
        rows = kv_time.load(os.path.join(here, "kv_traces", filename))
        distinct = len({b for r in rows for b in r["hash_ids"]})
        print("\n=== %s | requests %d | distinct blocks %d" % (name, len(rows), distinct), flush=True)
        for frac in (0.005, 0.01, 0.05):
            cap = max(1, int(distinct * frac))
            pinned = simulate(rows, kv_time.PinLRU, cap, 80.0, 20.0)
            free = simulate(rows, NoPinLRU, cap, 80.0, 20.0)
            print("  cap %-6d (%.1f%%) | pinned reuse %.4f deny %-5d evict %-7d peak_pin %-5d"
                  % (cap, frac * 100, pinned["reuse"], pinned["denied"], pinned["evictions"],
                     pinned["peak_pinned"]), flush=True)
            print("                    | free   reuse %.4f deny %-5d evict %-7d  (gap %+.2f%%)"
                  % (free["reuse"], free["denied"], free["evictions"],
                     (pinned["reuse"] - free["reuse"]) / free["reuse"] * 100), flush=True)


if __name__ == "__main__":
    main()
