"""Capacity-adaptive admission depth for prefix caches (CAPA).

The earlier sweep showed that admitting only the first K blocks of a chain helps
when capacity is smaller than the mean chain length, and hurts badly at larger
capacity, because a fixed K is a bet on one capacity regime. This experiment
replaces the fixed K with a rule that has no free parameter: K is the largest
depth at which every prefix family seen so far still holds a resident block,

    K = floor(B / N1)

where B is the block budget and N1 the running count of distinct first blocks.
If B/N1 is 4, the shallow four blocks of every family fit; if capacity grows,
K grows with it and truncation dissolves on its own.

Variants calibrate the same quantity by a multiplier c, and a variant evicts
resident blocks that are now deeper than K instead of waiting for them to age
out. Everything is online: no trace-wide constant is computed ahead of time.
"""

import json
import os
import sys

from kv_sim import BlockCache, LRU, SIEVE


def load(name):
    here = os.path.dirname(os.path.abspath(__file__))
    chains = []
    with open(os.path.join(here, "kv_traces", name), "r", encoding="utf-8") as handle:
        for line in handle:
            chains.append(json.loads(line)["hash_ids"])
    return chains


class Admitting(BlockCache):
    """Refuse admission for blocks deeper than the current budget allows."""

    def __init__(self, capacity, mult, eager=False):
        super().__init__(capacity)
        self.mult = mult
        self.eager = eager
        self.n1 = 0
        self.seen_first = set()
        self.k_sum = 0
        self.k_min = 0
        self.k_max = 0
        self.refused = 0

    def on_request(self, chain):
        first = chain[0]
        if first not in self.seen_first:
            self.seen_first.add(first)
            self.n1 += 1
        k = int(self.mult * self.cap / max(1, self.n1))
        if k < 1:
            k = 1
        self.k = k
        self.k_sum += k
        self.k_min = k if self.k_min == 0 else min(self.k_min, k)
        self.k_max = max(self.k_max, k)
        if self.eager:
            for node in list(self.table.values()):
                if node.depth >= k:
                    self._drop(node)
                    self.refused += 1

    def depth_limit(self, length):
        return self.k

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


def run(policy_cls, chains, capacity, **kwargs):
    policy = policy_cls(capacity, **kwargs)
    hit_blocks = 0
    total_blocks = 0
    full_hits = 0
    adm_refused = 0
    for chain in chains:
        if hasattr(policy, "on_request"):
            policy.on_request(chain)
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
            if hasattr(policy, "depth_limit") and depth >= policy.depth_limit(len(chain)):
                adm_refused += 1
                continue
            while len(policy) >= capacity:
                policy.evict()
            policy.insert(block, depth)
    return {
        "reuse": hit_blocks / float(total_blocks),
        "full": full_hits / float(len(chains)),
        "refused": adm_refused,
        "k_mean": (policy.k_sum / float(len(chains))) if hasattr(policy, "k_sum") else 0.0,
    }


def main():
    traces = [("conversation", "conversation_trace.jsonl"), ("mooncake", "mooncake.jsonl"),
              ("toolagent", "toolagent.jsonl"), ("synthetic", "synthetic.jsonl")]
    trex = [(name, load(fname), None) for name, fname in traces]
    for name, chains, _ in trex:
        lengths = [len(c) for c in chains]
        distinct = len({b for c in chains for b in c})
        firsts = len({c[0] for c in chains})
        print("%-13s requests %6d blocks %7d distinct %7d chains %6d mean_len %5.1f distinct_blocks_pct %.4f"
              % (name, len(chains), sum(lengths), distinct, firsts,
                 sum(lengths) / float(len(chains)), 1.0 - distinct / float(sum(lengths))), flush=True)

    variants = [("CAPA-c1", 1.0, False), ("CAPA-c2", 2.0, False), ("CAPA-c4", 4.0, False),
                ("CAPA-c1-eager", 1.0, True), ("CAPA-c2-eager", 2.0, True)]

    print()
    header = "%-13s %6s %8s %8s" % ("trace", "cap", "LRU", "SIEVE")
    for label, _, _ in variants:
        header += " %14s" % label
    print(header, flush=True)

    for name, chains, _ in trex:
        distinct = len({b for c in chains for b in c})
        for frac in (0.005, 0.01, 0.05, 0.20):
            cap = max(1, int(distinct * frac))
            line = "%-13s %6d %8.4f %8.4f" % (
                name, cap,
                run(LRU, chains, cap)["reuse"],
                run(SIEVE, chains, cap)["reuse"])
            for _, mult, eager in variants:
                r = run(Admitting, chains, cap, mult=mult, eager=eager)
                line += " %8.4f/%4.0f" % (r["reuse"], r["k_mean"])
            print(line, flush=True)


if __name__ == "__main__":
    main()
