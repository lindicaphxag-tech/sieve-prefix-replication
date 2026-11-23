"""Prefix-cache (KV block) simulator on the Mooncake FAST'25 traces.

A request carries a chain of block hashes. Reuse needs a contiguous match
from the first block, so the reusable prefix is the leading run of resident
blocks; blocks after the first gap must be recomputed.
"""

import json
import os


class Node:
    __slots__ = ("key", "prev", "next", "flag", "depth")

    def __init__(self, key, depth=0):
        self.key = key
        self.prev = None
        self.next = None
        self.flag = 0
        self.depth = depth


class BlockCache:
    name = "base"

    def __init__(self, capacity):
        self.cap = capacity
        self.head = None
        self.tail = None
        self.table = {}
        self.used = 0

    def __contains__(self, key):
        return key in self.table

    def __len__(self):
        return self.used

    def _prepend(self, node):
        node.prev = None
        node.next = self.head
        if self.head is not None:
            self.head.prev = node
        self.head = node
        if self.tail is None:
            self.tail = node

    def _remove(self, node):
        if node.prev is not None:
            node.prev.next = node.next
        else:
            self.head = node.next
        if node.next is not None:
            node.next.prev = node.prev
        else:
            self.tail = node.prev
        node.prev = None
        node.next = None

    def _drop(self, node):
        del self.table[node.key]
        self._remove(node)
        self.used -= 1

    def insert(self, key, depth=0):
        node = Node(key, depth)
        self.table[key] = node
        self._prepend(node)
        self.used += 1


class LRU(BlockCache):
    name = "LRU"

    def touch(self, key):
        node = self.table[key]
        if node is self.head:
            node.flag = 1
            return
        self._remove(node)
        self._prepend(node)
        node.flag = 1

    def evict(self):
        node = self.tail
        self._drop(node)
        return node.key


class FIFO(BlockCache):
    name = "FIFO"

    def touch(self, key):
        self.table[key].flag = 1

    def evict(self):
        node = self.tail
        self._drop(node)
        return node.key


class SIEVE(BlockCache):
    name = "SIEVE"

    def __init__(self, capacity):
        super().__init__(capacity)
        self.hand = None

    def touch(self, key):
        self.table[key].flag = 1

    def evict(self):
        node = self.hand if self.hand is not None else self.tail
        while node.flag > 0:
            node.flag = 0
            node = node.prev if node.prev is not None else self.tail
        self.hand = node.prev
        self._drop(node)
        return node.key


class CLOCK(BlockCache):
    name = "CLOCK"

    def touch(self, key):
        self.table[key].flag = 1

    def evict(self):
        node = self.tail
        while node.flag > 0:
            node.flag = 0
            node = node.prev if node.prev is not None else self.tail
        self._drop(node)
        return node.key


class ChainAwareLRU(BlockCache):
    """LRU tie-break, but deep blocks are dropped before shallow ones."""

    name = "DepthLRU"

    def touch(self, key):
        node = self.table[key]
        if node is self.head:
            return
        self._remove(node)
        self._prepend(node)

    def evict(self):
        best = None
        node = self.tail
        while node is not None:
            if best is None or node.depth > best.depth:
                best = node
                if best.depth >= 200:
                    break
            node = node.prev
        self._drop(best)
        return best.key


def simulate(policy_cls, chains, capacity):
    policy = policy_cls(capacity)
    hit_blocks = 0
    total_blocks = 0
    full_hits = 0
    for chain in chains:
        total_blocks += len(chain)
        prefix = 0
        for block in chain:
            if block in policy:
                policy.touch(block)
                prefix += 1
            else:
                break
        hit_blocks += prefix
        if prefix == len(chain):
            full_hits += 1
        for depth in range(prefix, len(chain)):
            block = chain[depth]
            if block in policy:
                policy.touch(block)
                continue
            while len(policy) >= capacity:
                policy.evict()
            policy.insert(block, depth)
    return hit_blocks / float(total_blocks), full_hits / float(len(chains))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    chains = []
    with open(os.path.join(here, "kv_traces", "conversation_trace.jsonl"), "r", encoding="utf-8") as handle:
        for line in handle:
            chains.append(json.loads(line)["hash_ids"])
    distinct = len({b for c in chains for b in c})
    total = sum(len(c) for c in chains)
    print("requests %d | blocks %d | distinct %d" % (len(chains), total, distinct))

    for frac in (0.01, 0.05, 0.2):
        cap = max(1, int(distinct * frac))
        print("=== capacity %d blocks (%.0f%% of distinct)" % (cap, frac * 100))
        for cls in (LRU, FIFO, CLOCK, SIEVE, ChainAwareLRU):
            ratio, full = simulate(cls, chains, cap)
            print("  %-10s prefix_hit=%.4f full_hit=%.4f" % (cls.name, ratio, full), flush=True)


if __name__ == "__main__":
    main()
