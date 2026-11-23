"""Does reclaiming unreachable prefix blocks beat plain LRU?

A resident block is useful only when every block before it in its chain is
also resident. Once an ancestor is evicted, the resident subtree underneath
is unreachable: it can never serve a prefix hit again. Reclaiming that space
first is free capacity, and it is where a prefix-aware policy can strictly
dominate LRU.
"""

import json
import os

from collections import OrderedDict


class LRU:
    name = "LRU"

    def __init__(self, capacity, parents=None, children=None):
        self.cap = capacity
        self.d = set()
        self.stamp = OrderedDict()

    def __contains__(self, key):
        return key in self.d

    def __len__(self):
        return len(self.d)

    def touch(self, key):
        self.stamp.move_to_end(key)

    def insert(self, key, depth=0):
        self.d.add(key)
        self.stamp[key] = None

    def evict(self):
        victim, _ = self.stamp.popitem(last=False)
        self.d.discard(victim)
        return victim


class LRUDead(LRU):
    name = "LRU+Dead"

    def __init__(self, capacity, parents, children):
        super().__init__(capacity)
        self.parents = parents
        self.children = children
        self.dead = OrderedDict()
        self.intact = {}

    def insert(self, key, depth=0):
        super().insert(key, depth)
        parent = self.parents.get(key)
        if parent is None or parent in self.d:
            self.intact[key] = True
        else:
            self.intact[key] = False
            self.dead[key] = None

    def evict(self):
        if self.dead:
            victim, _ = self.dead.popitem(last=False)
        else:
            victim = super().evict()
            self._break(victim)
            return victim
        self.d.discard(victim)
        self.stamp.pop(victim, None)
        self.intact.pop(victim, None)
        return victim

    def _break(self, victim):
        """Descendants of an evicted block become unreachable."""
        stack = [victim]
        while stack:
            node = stack.pop()
            for child in self.children.get(node, ()):
                if child in self.d and self.intact.get(child, True):
                    self.intact[child] = False
                    self.dead[child] = None
                    stack.append(child)


def build_parents(chains):
    parents = {}
    children = {}
    conflicts = 0
    for chain in chains:
        for i, block in enumerate(chain):
            if block not in parents:
                parents[block] = chain[i - 1] if i > 0 else None
            elif i > 0 and parents[block] != chain[i - 1]:
                conflicts += 1
            if i > 0:
                kids = children.setdefault(chain[i - 1], [])
                if block not in kids:
                    kids.append(block)
    return parents, children, conflicts


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
        parents, children, conflicts = build_parents(chains)
        print("\n=== %s | requests %d | distinct %d | parent conflicts %d"
              % (name, len(chains), distinct, conflicts), flush=True)
        for frac in (0.05, 0.2):
            cap = max(1, int(distinct * frac))
            base = simulate(LRU(cap), chains, cap)
            dead = simulate(LRUDead(cap, parents, children), chains, cap)
            print("  cap %-6d LRU %.4f | LRU+Dead %.4f | delta %+.2f%%"
                  % (cap, base, dead, (dead - base) / base * 100), flush=True)


if __name__ == "__main__":
    main()
