"""Leaf-first eviction for prefix caches.

LRU can evict an interior block, which orphans every block deeper in that
chain. A leaf-first policy evicts a block with no resident descendant and,
when that leaves its parent childless, the parent becomes a candidate too,
so a cold branch is released along its own path and capacity is not
fragmented across half-chains.
"""

import heapq
import json
import os

from collections import OrderedDict


class LRU:
    name = "LRU"

    def __init__(self, capacity, parents=None, children=None):
        self.cap = capacity
        self.resident = set()
        self.stamp = OrderedDict()

    def __contains__(self, key):
        return key in self.resident

    def __len__(self):
        return len(self.resident)

    def touch(self, key):
        self.stamp.move_to_end(key)

    def insert(self, key, depth=0):
        self.resident.add(key)
        self.stamp[key] = None

    def evict(self):
        key, _ = self.stamp.popitem(last=False)
        self.resident.discard(key)
        return key


class LeafFirst(LRU):
    name = "LeafFirst"

    def __init__(self, capacity, parents, children):
        super().__init__(capacity)
        self.parents = parents
        self.static_children = children
        self.live_children = {}
        self.tick = {}
        self.clock = 0
        self.heap = []

    def _bump(self, key):
        self.clock += 1
        self.tick[key] = self.clock
        return self.clock

    def insert(self, key, depth=0):
        self.resident.add(key)
        self.live_children[key] = 0
        parent = self.parents.get(key)
        if parent is not None and parent in self.resident:
            self.live_children[parent] = self.live_children.get(parent, 0) + 1
            heapq.heappush(self.heap, (self._bump(key), key))
        else:
            heapq.heappush(self.heap, (self._bump(key), key))

    def touch(self, key):
        heapq.heappush(self.heap, (self._bump(key), key))

    def evict(self):
        while self.heap:
            tick, key = self.heap[0]
            if (key not in self.resident or self.live_children.get(key, 0) != 0
                    or self.tick.get(key) != tick):
                heapq.heappop(self.heap)
                continue
            heapq.heappop(self.heap)
            break
        else:
            return super().evict()
        self.resident.discard(key)
        self.tick.pop(key, None)
        parent = self.parents.get(key)
        if parent is not None and parent in self.resident:
            self.live_children[parent] = self.live_children.get(parent, 1) - 1
            if self.live_children[parent] == 0:
                heapq.heappush(self.heap, (self.tick.get(parent, 0), parent))
        self.live_children.pop(key, None)
        return key


def build(chains):
    parents = {}
    children = {}
    for chain in chains:
        for i, block in enumerate(chain):
            if block not in parents:
                parents[block] = chain[i - 1] if i > 0 else None
            if i > 0:
                kids = children.setdefault(chain[i - 1], [])
                if block not in kids:
                    kids.append(block)
    return parents, children


def simulate(policy, chains, capacity):
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
        for block in chain[prefix:]:
            if block in policy:
                policy.touch(block)
                continue
            while len(policy) >= capacity:
                policy.evict()
            policy.insert(block, 0)
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
        total = sum(len(c) for c in chains)
        parents, children = build(chains)
        print("\n=== %s | distinct %d | bound %.4f" % (name, distinct, 1.0 - distinct / float(total)), flush=True)
        for frac in (0.01, 0.05, 0.2):
            cap = max(1, int(distinct * frac))
            base = simulate(LRU(cap), chains, cap)
            leaf = simulate(LeafFirst(cap, parents, children), chains, cap)
            print("  cap %-6d LRU %.4f | LeafFirst %.4f | delta %+.2f%%"
                  % (cap, base, leaf, (leaf - base) / base * 100), flush=True)


if __name__ == "__main__":
    main()
