# Trace evidence v3 - replay order, reuse depth, reuse frequency

Supersedes v1/v2. Every number comes from the two public lcp traces and the single-pass parsers in this directory.

## 1. Replay order is a protocol variable

`prefixsim` defaults to `--replay-order deepest-first`; a vLLM engine registers a request's blocks shallow-to-deep (prefix-order). Same trace, pool and algorithms:

| trace / pool | LRU df | LRU po | SIEVE df | SIEVE po | d df | d po |
|---|---|---|---|---|---|---|
| freeinference 64k | 0.917540 | 0.917430 | 0.917670 | 0.917779 | +0.014 pp | **+0.035 pp** |
| freeinference 256k | 0.936234 | 0.936230 | 0.936274 | 0.936293 | +0.004 pp | +0.006 pp |
| freeinference 1M | 0.938126 | 0.938125 | 0.938170 | 0.938170 | +0.004 pp | +0.005 pp |
| chutes 64k | 0.726900 | 0.726831 | 0.714400 | 0.713628 | -1.700 pp | **-1.320 pp** |
| chutes 256k | 0.748757 | 0.748745 | 0.747115 | 0.746994 | -0.164 pp | -0.175 pp |
| chutes 1M | 0.761576 | 0.761574 | 0.760827 | 0.761158 | -0.075 pp | **-0.042 pp** |

LRU moves by at most 0.012 pp; SIEVE moves by up to 0.077 pp, removing 22 % of the 64k loss and 44 % of the 1M loss while adding 0.011 pp at 256k. Since the baseline is invariant, the effect is protocol, not mechanism: an eviction comparison reported only under the simulator default is not comparable to an engine's.

## 2. Reuse depth (`depthmeas.cpp`)

Share of reuse accesses by in-request block position:

| trace | 1 | 2-4 | 5-16 | 17-64 | 65-256 | 257-1024 | 1025-4096 | 4097-16384 | mean depth |
|---|---|---|---|---|---|---|---|---|---|
| freeinference | 0.053 % | 0.144 % | 0.439 % | 1.420 % | 4.956 % | 15.668 % | **41.068 %** | 36.200 % | 3,653.9 |
| chutes | 0.105 % | 0.297 % | 1.130 % | 4.177 % | 15.174 % | **39.023 %** | 35.398 % | 4.592 % | 1,198.7 |

Control workloads (same binning, `depth_live.py`): conversation mean depth 1.63 blocks (max 14), toolagent 1.51 (14), synthetic 1.91 (22). Production reuse is three orders of magnitude deeper than the microbenchmarks, which retracts the v2 claim that real cross-stream reuse is shallow.

## 3. Reuse frequency (`freqmeas.cpp`)

| trace | distinct | accesses/distinct | count 1 blocks/accesses | >=17 mass | >=65 mass |
|---|---|---|---|---|---|
| freeinference | 39,578,367 | 16.58 | 53.02 % / 3.20 % | **0.859** | **0.612** |
| chutes | 139,518,804 | 4.33 | 56.37 % / 13.03 % | 0.521 | 0.323 |

Frequency separates the two traces better than sigma_cross (0.170 vs 0.645, where the losing trace has the *higher* sigma), yet it also fails as a law: the conversation workload has the lowest accesses/distinct of anything measured (1.21) and SIEVE wins there by +24.6 %. Two single-axis readings die; what survives is sigma_cross >= 0.25 as a necessary, not sufficient, condition.

## 4. Reproduce

```bash
g++ -O2 -std=c++17 -o depthmeas depthmeas.cpp -lzstd
g++ -O2 -std=c++17 -o freqmeas  freqmeas.cpp  -lzstd
./depthmeas trace/chutes.lcp.zst ; ./freqmeas trace/chutes.lcp.zst
python3 depth_live.py
for o in deepest-first prefix-order; do for s in 64k 256k 1m; do
  PrefixSim/_build/bin/prefixsim --trace trace/chutes.lcp.zst --cache-size $s --algo lru,sieve --replay-order $o
done; done
```
