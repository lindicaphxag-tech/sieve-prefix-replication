import os

import zstandard

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sieve_data", "twitter_cluster52_10m.csv.zst")
DST = os.path.join(HERE, "sieve_data", "twitter_10m.csv")

if os.path.exists(DST) and os.path.getsize(DST) > 1_000_000:
    print("already decompressed", os.path.getsize(DST))
else:
    with open(SRC, "rb") as src, open(DST, "wb") as dst:
        reader = zstandard.ZstdDecompressor().stream_reader(src)
        total = 0
        while True:
            chunk = reader.read(1 << 23)
            if not chunk:
                break
            dst.write(chunk)
            total += len(chunk)
    print("decompressed bytes", total)

with open(DST, "rb") as handle:
    print(repr(handle.read(400)))
print("lines", sum(1 for _ in open(DST, "rb")))
