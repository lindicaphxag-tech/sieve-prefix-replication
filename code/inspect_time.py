import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = {
    "conversation": "conversation_trace.jsonl",
    "mooncake": "mooncake.jsonl",
    "toolagent": "toolagent.jsonl",
    "synthetic": "synthetic.jsonl",
}

for name, filename in FILES.items():
    rows = []
    with open(os.path.join(HERE, "kv_traces", filename), "r", encoding="utf-8") as handle:
        for line in handle:
            rows.append(json.loads(line))
    ts = np.array([r["timestamp"] for r in rows], dtype=np.int64)
    inp = np.array([r["input_length"] for r in rows], dtype=np.int64)
    out = np.array([r["output_length"] for r in rows], dtype=np.int64)
    blocks = np.array([len(r["hash_ids"]) for r in rows], dtype=np.int64)
    span = ts.max() - ts.min()
    print("\n=== %s | n=%d" % (name, len(rows)))
    print("  timestamp min %d max %d span %d | non-monotonic %d"
          % (ts.min(), ts.max(), span, int((np.diff(ts) < 0).sum())))
    print("  input_length: mean %.0f p50 %d max %d sum %d"
          % (inp.mean(), np.median(inp), inp.max(), inp.sum()))
    print("  output_length: mean %.0f p50 %d max %d sum %d"
          % (out.mean(), np.median(out), out.max(), out.sum()))
    print("  blocks per request: mean %.1f max %d" % (blocks.mean(), blocks.max()))
    print("  tokens per block: implied %.1f (input/block mean)"
          % (inp.sum() / float(blocks.sum()) * (blocks.mean() / max(inp.mean(), 1)) * 0 + (inp / np.maximum(blocks, 1)).mean()))
    if span > 0:
        print("  arrival rate: %.3f req/s (assuming timestamps in seconds)" % (len(rows) / float(span)))
        print("  first 12 timestamps:", ts[:12].tolist())
