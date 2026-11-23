import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "kv_traces")
os.makedirs(OUT, exist_ok=True)

SRC = "https://raw.githubusercontent.com/kvcache-ai/Mooncake/main/FAST25-release/traces/conversation_trace.jsonl"
DST = os.path.join(OUT, "conversation_trace.jsonl")

if os.path.exists(DST) and os.path.getsize(DST) > 1_000_000:
    print("have", os.path.getsize(DST))
else:
    for attempt in range(6):
        try:
            urllib.request.urlretrieve(SRC, DST)
            print("got", os.path.getsize(DST))
            break
        except Exception as error:
            print("retry", error)
    else:
        raise SystemExit("download failed")

with open(DST, "rb") as handle:
    for i in range(4):
        line = handle.readline()
        print("RAW", line[:400])

rows = []
with open(DST, "r", encoding="utf-8") as handle:
    for line in handle:
        rows.append(json.loads(line))
print("requests", len(rows))
print("keys", list(rows[0].keys()))
for row in rows[:3]:
    print({k: (v if not isinstance(v, list) else "%d items: %s" % (len(v), v[:3])) for k, v in row.items()})
blocks = [len(r.get("hash_ids", [])) for r in rows]
print("block count per request: min %d max %d mean %.1f" % (min(blocks), max(blocks), sum(blocks) / len(blocks)))
print("distinct blocks", len({b for r in rows for b in r.get("hash_ids", [])}))
