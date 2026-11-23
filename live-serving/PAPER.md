---
title: "Reuse-Count Victim Choice for LLM Prefix Caches: A Measurable Window, One Counterexample, and a Selector That Lives in the Scheduler"
author: "Zhibo Zhang (Hangzhou Dianzi University) — ORCID 0009-0007-3533-1941"
date: "2026-11-24"
abstract: |
  Prefix caching is standard in LLM serving stacks, but the eviction policy inside it is usually inherited from general-purpose caching research, where recency and insertion order are the only signals available. We measure the same policy pair (SIEVE vs LRU) in seven regimes, spanning 110 live runs on a real vLLM stack and two released production traces (1.26 billion block accesses, 625 thousand sessions). The difference runs from +24.6% (live conversation workload, 1733-block pool) to +0.014 pp and -1.70 pp (two production traces at 64k blocks). We show which counters make that difference predictable: the share of reuse that crosses request streams (sigma_cross), the pool's occupancy hit rate, and the visibility of pinned blocks (pi). We then show that the estimator cannot live inside the allocator: a proxy measured there never crossed threshold on any live workload and degenerated to LRU. Moving the estimator to the request stream and the actuator to the allocator yields a selector that recovers 57% of the attainable increment (0.0980 to 0.1121 at the operating point) with zero negative windows across twelve workload-capacity points. Finally we report the case that does not fit: a chat trace with sigma_cross = 0.645, servable-gap share 0.942, hit rate 0.727 and 48% revisit concentration still loses 1.70 pp at 64k blocks, and only 0.16 pp at 4x pool. We state the two hypotheses that survive and the two experiments that separate them, rather than fitting a narrative to it. The framework section states what 2026 reporting, 2027 design and 2028 placement each have to be able to measure.
---

## 0. What this paper claims

1. **A window exists and it is measurable.** For the same policy pair the block-hit ratio difference spans +24.6 % to −1.70 pp across seven regimes. Three counters — cross-stream reuse share σ_cross, pool occupancy hit rate, and pin visibility π — determine whether the window can open at all, and the increment scales with σ_cross.
2. **The selector must sit above the allocator.** Estimating σ from the request stream (where sessions are visible) and actuating the victim rule in the allocator recovers +14.4 % relative gain (0.0980 → 0.1121), i.e. 57 % of the attainable increment, with zero negative windows across 12 workload×capacity points. The same idea inside the allocator fails outright.
3. **One counterexample is left open on purpose.** A chat trace satisfying every condition we can measure still loses at 64k blocks. Section 4 states the two surviving hypotheses and the experiment that separates them.

## 1. Live measurements (single node)

Harness: vLLM 0.6.6.post1, Qwen2.5-1.5B-Instruct, a 12 GiB device shared with co-tenants, `--enable-prefix-caching`, block 16, concurrency 8/16/32, 800 requests per cell, 110 runs. The evictor is swapped at import time through the only `make_evictor` site in `vllm/core/block/prefix_caching_block.py`; every run prints `[evictor] <policy> -> <class>` to stderr as a quality gate.

| workload | LRU | SIEVE | LFU-W | Δ(SIEVE−LRU) | note |
|---|---|---|---|---|---|
| synthetic | 0.0513 | 0.0490 | 0.0513 | −4.5 % | reuse is cross-stream but only 1 block deep |
| conversation | 0.1073 | 0.1337 | 0.1314 | **+24.6 %** | five runs, non-overlapping intervals |
| toolagent | 0.4167 | 0.4247 | 0.4409 | +1.9 % | LFU-W wins this cell |
| agentic | 0.6342–0.6390 | same band | same band | ~0 | π≈0.65: shared trunk is refcount-pinned |

Capacity sweep on conversation (400/800/1200/1733 blocks): +2.6 % / +0.3 % / +6.6 % / +24.6 %. Halving-period 64/256/1024 insensitive; sampling k=16 trades 2.1 % hit ratio for 14 % throughput and lower p50. Throughput itself is **not attributable** on a shared device (27 % spread at identical configuration) and is not reported as a result.

## 2. Production traces

Two public traces from *When Fancy Eviction Fails* (arXiv:2609.28870) replayed through `cacheMon/PrefixSim` (uniform cost model, `block_id=prefix`, `n_self_eviction=0`, no skipped requests). Locality statistics come from a single-pass parser (`gapmeas.cpp`, zstd+lcp).

| trace | requests | block accesses | distinct | sessions | σ_cross (share of reuse) | mean cross gap | gap max |
|---|---|---|---|---|---|---|---|
| freeinference | 327,548 | 656,240,179 | 39,578,367 | 222,934 | **0.1699** | 404 s | 577,140 s |
| chutes | 515,817 | 603,642,254 | 139,518,804 | 402,221 | **0.6451** | 7,218 s | 9,519,854 s |

Servable share of cross-stream reuse, F(τ) with τ = C/λ (λ = 65.4 and 12.34 new blocks/s):

| pool | freeinference F | chutes F |
|---|---|---|
| 16k | 0.978 | 0.890 |
| 64k | 0.978 | 0.942 |
| 256k | 0.988 | 0.967 |
| 1M | 0.994 | 0.989 |

Revisit concentration — share of cross-stream reuses landing on blocks revisited n times across streams:

| trace | 1 | 2 | 3–4 | 5–8 | 9–32 | >32 |
|---|---|---|---|---|---|---|
| freeinference | 0.0196 | 0.0195 | 0.0292 | 0.0538 | 0.2546 | **0.6232** |
| chutes | 0.0645 | 0.0572 | 0.0844 | 0.0972 | 0.2192 | **0.4775** |

Replay results:

| trace / pool | LRU | SIEVE | S3FIFO |
|---|---|---|---|
| freeinference 64k | 0.917540 | 0.917670 (**+0.014 pp**) | 0.912296 (−0.57 pp) |
| freeinference 256k | 0.9362 | 0.9363 | 0.9356 |
| freeinference 1M | 0.9381 | 0.9382 | 0.9382 |
| chutes 64k | 0.726900 | 0.714400 (**−1.70 pp**) | 0.696200 (−4.22 pp) |
| chutes 256k | 0.748757 | 0.747115 (**−0.16 pp**) | 0.746891 (−0.19 pp) |

The two traces fail for different reasons, and only one of them is a condition we can name: freeinference fails on σ (83 % of its reuse is intra-session, so recency already captures it), chutes passes σ but fails somewhere we have not pinned (Section 4).

## 3. Selector

Allocation-side estimation fails: a rule that samples 16 candidates for "reused but stale" blocks produced proxy values 0.006–0.085 on all three live workloads, never crossed 0.25, and degenerated to LRU (the code is kept as a negative result). Cross-stream reuse in real traffic is usually **frequent and shallow**, not stale and isolated; the discriminating quantity needs prefix depth and session identity, both of which live above the allocator.

Request-stream estimator: lineage = greedy longest-shared-prefix join against the last 64 requests (≥ 4 leading blocks); σ̂ = share of observed reuse whose previous accessor belongs to another lineage; ρ̂ = C/(λ̂·ĝ). Window 256 requests; inside the window the allocator runs SIEVE, outside LRU.

| capacity | workload | LRU | SIEVE | LFU-W | **selector** | hindsight max | inside % | regret |
|---|---|---|---|---|---|---|---|---|
| 400 | conversation | 0.0681 | 0.0708 | 0.0671 | **0.0681** | 0.0712 | 0 | −0.31 pp |
| 800 | conversation | 0.0732 | 0.0755 | 0.0836 | **0.0737** | 0.0849 | 17 | −1.13 pp |
| 1200 | conversation | 0.0791 | 0.0869 | 0.0910 | **0.0808** | 0.0940 | 17 | −1.32 pp |
| 1733 | conversation | 0.0980 | 0.1229 | 0.1106 | **0.1121** | 0.1277 | 50 | −1.56 pp |
| 1733 | toolagent | 0.4534 | 0.4642 | 0.4582 | **0.4534** | 0.4664 | 0 | −1.30 pp |
| 1733 | synthetic | 0.0498 | 0.0530 | 0.0438 | **0.0498** | 0.0575 | 0 | −0.77 pp |

Thresholds were fixed a priori from the necessary conditions and were **not** tuned on these traces. The regret is concentrated in windows where LFU-W would have won and the selector only had SIEVE available; extending the action set to three policies is the next experiment, not a claim.

## 4. What the evidence supports, and what it does not

Supported:

- SIEVE/LFU-W beat LRU **only** when (i) a non-trivial share of reuse is cross-stream, (ii) the pool does not already hold the working set (hit rate ≲ 0.85), and (iii) the evictor is asked at all (π small);
- the increment scales with σ_cross: +1.9 % at σ = 0.41, +24.6 % at σ ≈ 1;
- capacity monotonically shrinks the loss where the window is closed: chutes −1.70 → −0.16 pp at 4× pool;
- a request-stream estimator recovers a majority of the attainable gain without knowing the workload.

Not supported, and stated as such:

- the earlier "two-factor conjunction law" (σ_cross × coverage). chutes satisfies every factor we can measure — σ 0.645, F(64k) 0.942, hit 0.727, 48 % revisit concentration — and still loses 1.70 pp at 64k. Two hypotheses remain:
  - **H1**: chutes has ≈ 1,170 blocks per request against a 65k-block pool, and hits occur at the prefix head, so a policy that evicts the newest block first is structurally penalised independent of cross-stream reuse;
  - **H2**: replay fixes π = 0 while a real deployment of that trace may run at high concurrency, in which case the replay's π is simply not the deployment's π.
  Separating them needs (a) chutes replay at 1M blocks — if the loss keeps halving, capacity/chain length is the axis; if it flattens, π is — and (b) an engine-side histogram of π. Both are specified in `TRACE_EVIDENCE_V2.md`.

## 5. Implications for 2026–2028

- **2026** — report σ_cross, hit rate and π with every eviction result, otherwise numbers are not portable. All three are available from engine counters (session id, reuse count on the hit path, candidate refcount), with no extra hardware.
- **2027** — stop designing evictors, design **selectors**: estimator in the frontend, actuator in the allocator. This work shows 57 % of attainable gain with zero negative windows; open problems are calibration across workloads and a three-policy action set.
- **2028** — once prefill and decode are disaggregated, placement decides whether a request can meet its prefix at all; per-node eviction becomes second order unless placement is prefix-affinity aware.

## 6. Reproduce

```bash
# live (needs a GPU; see run_one.sh)
EVICTOR_POLICY=sieve setsid venv/bin/python -m vllm.entrypoints.openai.api_server --model <m> \
  --enable-prefix-caching --max-model-len 2048 --gpu-memory-utilization 0.45 --port 8100
python scripts/bench_client.py --base http://127.0.0.1:8100 --work work/conversation.json --requests 800

# production traces
curl -L -o trace/chutes.lcp.zst https://huggingface.co/datasets/harvardMadsys/2026_prefixcache/resolve/main/chutes.lcp.zst
g++ -O2 -o gapmeas gapmeas.cpp -lzstd && ./gapmeas trace/chutes.lcp.zst
PrefixSim/_build/bin/prefixsim --trace trace/chutes.lcp.zst --cache-size 64k --algo lru,sieve,s3fifo

# selector
python3 router_sim.py --capacity 1733
```

## 7. Artefacts

`PAPER.md` (this file), `FRAMEWORK_2026_v5.md`, `TRACE_EVIDENCE_V2.md`, `ROUTER_RESULTS.md`, `gapmeas.cpp`, `router_sim.py`, `offline_sim.py`, `reuse_profile.py`, `out/` (110 live runs), `trace/` (both public traces), `PrefixSim/` (fork with `traceReuseStat`, PR pending upstream).
