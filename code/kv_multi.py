import json
import os
import urllib.request

import kv_sim

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "kv_traces")
BASE = "https://raw.githubusercontent.com/kvcache-ai/Mooncake/main/FAST25-release/"
SOURCES = {
    "mooncake": BASE + "arxiv-trace/mooncake_trace.jsonl",
    "toolagent": BASE + "traces/toolagent_trace.jsonl",
    "synthetic": BASE + "traces/synthetic_trace.jsonl",
}

for name, url in SOURCES.items():
    dst = os.path.join(OUT, name + ".jsonl")
    if os.path.exists(dst) and os.path.getsize(dst) > 500_000:
        print("have", name, os.path.getsize(dst))
        continue
    for attempt in range(6):
        try:
            urllib.request.urlretrieve(url, dst)
            print("got", name, os.path.getsize(dst))
            break
        except Exception as error:
            print("retry", name, error)

FILES = {
    "conversation": "conversation_trace.jsonl",
    "mooncake": "mooncake.jsonl",
    "toolagent": "toolagent.jsonl",
    "synthetic": "synthetic.jsonl",
}

for name, filename in FILES.items():
    path = os.path.join(OUT, filename)
    if not os.path.exists(path):
        print("missing", name)
        continue
    chains = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            chains.append(row["hash_ids"])
    distinct = len({b for c in chains for b in c})
    total = sum(len(c) for c in chains)
    bound = 1.0 - distinct / float(total)
    print("\n=== %s | requests %d | blocks %d | distinct %d | upper bound %.4f"
          % (name, len(chains), total, distinct, bound))
    for frac in (0.05, 0.2):
        cap = max(1, int(distinct * frac))
        line = "  cap %-5d" % cap
        for cls in (kv_sim.LRU, kv_sim.FIFO, kv_sim.SIEVE):
            ratio, full = kv_sim.simulate(cls, chains, cap)
            line += " | %s %.4f" % (cls.name, ratio)
        print(line, flush=True)
