import os

import numpy as np

import sieve_bytes
import sieve_sim

HERE = os.path.dirname(os.path.abspath(__file__))
keys = np.fromfile(os.path.join(HERE, "sieve_data", "trace.txt"), dtype=np.int64, sep="\n")

print("byte-capacity policies with size=1 must match count-capacity policies")
for cap in (1000, 5000):
    for name in ("LRU", "FIFO", "SIEVE", "CLOCK", "FIFO-Reinsertion"):
        a = sieve_sim.POLICIES[name](cap)
        m1 = sum(a.request(int(k)) for k in keys)
        b = sieve_bytes.POLICIES[name](cap)
        m2 = sum(b.request(int(k), 1) for k in keys)
        used_ok = b.used <= cap
        print("%-18s cap %-6d count %-7d bytes %-7d %s used_ok=%s" %
              (name, cap, m1, m2, "MATCH" if m1 == m2 else "DIFF", used_ok))
