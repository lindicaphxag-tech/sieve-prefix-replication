import os

import numpy as np

import sieve_literal
import sieve_sim

HERE = os.path.dirname(os.path.abspath(__file__))
small = np.fromfile(os.path.join(HERE, "sieve_data", "trace.txt"), dtype=np.int64, sep="\n")

import random


def zipf(n, alpha, nkeys, seed=7):
    rng = random.Random(seed)
    ranks = list(range(1, nkeys + 1))
    weights = [r ** (-alpha) for r in ranks]
    return [rng.choices(ranks, weights=weights, k=1)[0] for _ in range(n)]


for label, keys in (("cloudPhysicsIO", small), ("zipf1.0", zipf(30000, 1.0, 20000))):
    print("===", label)
    for cap in (1000, 5000):
        lit = sieve_literal.SieveLiteral(cap)
        m_lit = sum(lit.request(int(k)) for k in keys)
        fast = sieve_sim.SIEVE(cap)
        m_fast = sum(fast.request(int(k)) for k in keys)
        print("cap %-6d literal %-7d fast %-7d %s" % (cap, m_lit, m_fast, "MATCH" if m_lit == m_fast else "DIFF"))
