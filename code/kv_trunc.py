"""Depth-truncated admission for prefix caches.

The hit metric counts reused blocks, and a block at depth d can only be
reused by requests whose chain reaches depth d. Shallow blocks are shared
across many chains, deep blocks across few. Admitting only the first K blocks
of a chain can therefore buy more hits per byte at small capacity.
"""

import json
import os

from collections import OrderedDict

import kv_leaf


class TruncLRU(kv_leaf.LRU):
    name = "TruncLRU"

    def __init__(self, capacity, limit):
        super().__init__(capacity)
        self.limit = limit

    def insert(self, key, depth=0):
        if depth >= self.limit:
            return False
        super().insert(key, depth)
        return True


def simulate(policy, chains, capacity, limit):
    hit = 0
    total = 0
    for chain in chains:
        total += len(chain)
        prefix = 0
        for block in chain:
            if block in policy:
                policy.touch(block)
                prefix += 1
            else:
                break
        hit += prefix
        for depth in range(prefix, len(chain)):
            block = chain[depth]
            if block in policy:
                policy.touch(block)
                continue
            while len(policy) >= capacity:
                policy.evict()
            policy.insert(block, depth)
    return hit / float(total)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    files = {
        "conversation": "conversation_trace.jsonl",
        "mooncake": "mooncake.jsonl",
        "toolagent": "toolagent.jsonl",
        "synthetic": "synthetic.jsonl",
    }
    for name, filename in files.items():
        chains = []
        with open(os.path.join(here, "kv_traces", filename), "r", encoding="utf-8") as handle:
            for line in handle:
                chains.append(json.loads(line)["hash_ids"])
        distinct = len({b for c in chains for b in c})
        print("\n=== %s" % name, flush=True)
        for frac in (0.01, 0.05, 0.2):
            cap = max(1, int(distinct * frac))
            base = simulate(kv_leaf.LRU(cap), chains, cap, 10 ** 9)
            line = "  cap %-6d LRU %.4f" % (cap, base)
            for limit in (4, 16, 64):
                value = simulate(TruncLRU(cap, limit), chains, cap, limit)
                line += " | K=%-3d %.4f (%+.1f%%)" % (limit, value, (value - base) / base * 100)
            print(line, flush=True)


if __name__ == "__main__":
    main()
