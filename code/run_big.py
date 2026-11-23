import os
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sieve_data", "twitter_10m.csv")
CACHE = os.path.join(HERE, "sieve_data", "twitter_keys.npz")


def load():
    if os.path.exists(CACHE):
        data = np.load(CACHE)
        return data["keys"], data["sizes"]
    start = time.time()
    keys = []
    sizes = []
    with open(SRC, "rb") as handle:
        handle.readline()
        for line in handle:
            parts = line.split(b",")
            keys.append(int(parts[1]))
            sizes.append(int(parts[2]))
    print("parsed %d requests in %.1fs" % (len(keys), time.time() - start))
    keys = np.asarray(keys, np.uint64)
    sizes = np.asarray(sizes, np.int64)
    np.savez(CACHE, keys=keys, sizes=sizes)
    return keys, sizes


keys_np, sizes_np = load()
uniq, idx = np.unique(keys_np, return_index=True)
footprint = int(sizes_np[idx].sum())
total_bytes = int(sizes_np.sum())
print("requests %d | unique %d | footprint %d bytes (%.2f GiB) | mean size %.1f" %
      (keys_np.size, uniq.size, footprint, footprint / float(1 << 30), sizes_np.mean()))

keys = keys_np.tolist()
sizes = sizes_np.tolist()
del keys_np, sizes_np, uniq, idx

import sieve_bytes

limit = int(os.environ.get("LIMIT", "0")) or len(keys)

for frac in (0.001, 0.1):
    cap = int(footprint * frac)
    print("=== cap %.1f%% = %d bytes" % (frac * 100, cap), flush=True)
    for name in ("LRU", "FIFO", "CLOCK", "FIFO-Reinsertion", "SIEVE"):
        policy = sieve_bytes.POLICIES[name](cap)
        start = time.time()
        missing = 0
        miss_bytes = 0
        for i in range(limit):
            if policy.request(keys[i], sizes[i]):
                missing += 1
                miss_bytes += sizes[i]
        print("  %-18s miss=%-9d obj_mr=%.6f byte_mr=%.6f %.1fs" %
              (name, missing, missing / float(limit), miss_bytes / float(total_bytes), time.time() - start), flush=True)
