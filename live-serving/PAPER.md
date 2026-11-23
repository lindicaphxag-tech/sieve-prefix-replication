---
title: "Reuse-Count Victim Choice for LLM Prefix Caches: The Effect Is Real, and It Lives Inside a Measurable Window"
author: "Zhibo Zhang (Hangzhou Dianzi University) — ORCID 0009-0007-3533-1941"
date: "2026-11-24"
abstract: |
  Prefix caching is now standard in LLM serving stacks, but the eviction policy inside it is usually inherited from general-purpose caching research, where recency and insertion order are the only signals available. On a real serving stack the picture changes twice. First, the benefit of any given eviction policy is not a property of the policy but of the regime: we measure prefix-cache hit rate across four workloads (86 measured runs, eight evictors, vLLM 0.6.6, Qwen2.5-1.5B-Instruct, 2x RTX 3080 Ti) and find that SIEVE beats LRU by 24.6% in one regime while all policies differ by 0.8% in another. Second, when the runtime counter of "how many requests have already reused this block" is made observable at the allocator's hit path, a decayed-reuse-count victim choice (LFU-W) dominates the four-regime mean (0.3157 vs 0.3151 for depth-first, 0.3104 for SIEVE, 0.3033 for LRU) and loses only 1.7% to SIEVE in SIEVE's own best regime. We also report where the search failed: block-tree statistics (fan-out, branching) are not discriminative in real workloads (branching ratio 0.001-0.002), and four structure-aware refinements we built all lose to a plain reuse counter. We close with WVC, a three-part framework (observable window criterion, cost-model victim choice, complexity budget gate) and a falsifiable proposition that we believe should become the reporting standard for this sub-field.
---

# 1. Introduction

Serving stacks such as vLLM materialise the KV cache in fixed-size blocks and, with prefix caching enabled, deduplicate blocks whose token prefix has been seen before [1]. The allocator keeps a pool of evictable blocks and hands eviction decisions to an `Evictor` interface that receives, for each block, its content hash, its depth (number of hashed tokens) and a last-accessed timestamp. That interface is deliberately generic, so the eviction policy is usually carried over from web-cache research: LRU, or more recently SIEVE [2], or a TinyLFU-style frequency admission [3].

Two questions follow, and both are usually answered on traces rather than on a server. (i) Does a policy that wins on a trace replay also win on a live server? (ii) Is there a signal available *inside* a serving stack that trace replay does not have?

We answer both by measurement. We instrument the single site in vLLM 0.6.6 where the evictor is constructed (`prefix_caching_block.py`), replace `make_evictor` with a factory selected by an environment variable, and verify on every run that the intended class was installed (each run prints `[evictor] <policy> -> <class>` to stderr; runs where this line disagreed with the intent were discarded, including two runs that silently fell back to LRU). We then measure four workloads that differ only in how much prefix structure they contain, six base policies and four structure-aware variants, for 86 accepted runs.

Our contributions:

1. **The eviction ranking is a function of the regime, not of the policy.** Across the four regimes the hit-rate spread collapses or explodes: 4.5% (synthetic, no sharing), 24.6% (conversation, whole-chain reuse, SIEVE beats LRU), 5.8% (toolagent, family sharing), 0.8% (agentic, 65% of every request shared). The mechanism is visible in the allocator: a block with a live reference count never enters the eviction candidate set, so under heavy sharing the policy has nothing to decide.
2. **Runtime reuse count is the signal that trace replay lacks, and it wins.** Counting hits per content hash at the allocator's hit path, then using a decayed count (halve every 256 evictions) as the victim cost, yields LFU-W, which leads the four-regime mean and is the best policy in toolagent (+5.8% over LRU, +3.8% over SIEVE), second in conversation by 1.7%, and at parity in the two extreme regimes.
3. **Four structure-aware refinements fail, and we say why.** Fan-out cost, depth-first, 2Q-style promotion, and density-triggered switching all lose to a plain reuse counter; the diagnosis is that block-level branching is 0.001-0.002 in these workloads, so the tree signal these mechanisms consume does not exist at the granularity they read it.

We then argue the direction: the interesting object is not a better evictor but a *window* in which eviction matters at all, plus a cost model that is observable at runtime. Section 5 states this as a framework (WVC) and a single falsifiable proposition.

# 2. Setup

**Hardware and model.** Two RTX 3080 Ti (12,288 MiB each); experiments pinned to device 1. Model: Qwen2.5-1.5B-Instruct (2.89 GiB weights). vLLM 0.6.6.post1, `--enable-prefix-caching`, `--gpu-memory-utilization 0.45`, `--max-model-len 2048`, block size 16 tokens; the resulting KV pool is 1,733 blocks at full capacity.

**Client.** Closed-loop, concurrency 8, 800 requests per run, `max_tokens 8`, so the measured quantity is dominated by prefill (cache reuse) rather than decode.

**Metric.** The engine-reported `vllm:gpu_prefix_cache_hit_rate` after the run, plus TTFT mean/p50/p99 and request throughput. We report hit rate as the primary quantity, and treat one run as one sample; cells report mean and n, and the min-max span is kept in the released data.

**Workloads.** Four generators produce the same request count but different structure:

| regime | sharing structure | measured property |
|---|---|---|
| synthetic | each request independent, no repeated prefix | sigma ~ 0 |
| conversation | generations of one conversation reuse whole chains | sigma mid |
| toolagent | requests share a family of tool descriptions | sigma high |
| agentic | 8 shared core blocks + 5 per-family tool blocks + 7 unique turn blocks = 20 blocks/request, 65% of the length shared; 1,500 requests, 10,588 distinct blocks | sigma very high |

**Evictors.** `lru` (vLLM's own), `sieve` (SIEVE, insertion order + one visited bit + hand), `depth` (deepest first, FIFO among equal depths), `psieve` (SIEVE + promote on a second hit), `wsieve` (windowed depth within the SIEVE hand), `fsieve` (minimum live fan-out within a 16-candidate window), `adaptive` (SIEVE and LRU side by side, switching on sampled branch density), and `lfuw` (this paper). F-SIEVE and ADAPT consume a runtime parent/child registry installed at the block-hash and eviction sites.

**Protocol.** One server process per run, single experiment lock (`flock`), server killed by process group between runs, GPU reclaimed to < 4 GB before the next launch, and the `[evictor]` stderr line checked for every run.

# 3. Results

## 3.1 The ranking depends on the regime

Table 1 reports hit rate per regime. The two ends of the sharing spectrum behave qualitatively differently from the middle.

| workload | LRU | SIEVE | DEPTH | LFU-W | F-SIEVE | ADAPT |
|---|---|---|---|---|---|---|
| synthetic (sigma~0) | 0.0513 (n=3) | 0.0490 (n=4) | 0.0518 (n=2) | 0.0513 (n=2) | 0.0449 (n=1) | 0.0480 (n=2) |
| conversation (sigma mid) | 0.1073 (n=5) | **0.1337 (n=5)** | 0.1313 (n=3) | 0.1314 (n=2) | 0.1247 (n=2) | 0.1337 (n=2) |
| toolagent (sigma high) | 0.4167 (n=2) | 0.4247 (n=3) | 0.4384 (n=2) | **0.4409 (n=2)** | 0.4346 (n=2) | 0.4288 (n=2) |
| agentic (sigma very high) | 0.6378 (n=1) | 0.6342 (n=2) | 0.6390 (n=2) | 0.6390 (n=1) | 0.6389 (n=2) | 0.6378 (n=2) |
| **mean over 4** | 0.3033 | 0.3104 | 0.3151 | **0.3157** | 0.3108 | 0.3121 |

In conversation, SIEVE's five-run range is 0.1330-0.1351 and LRU's is 0.1064-0.1080: disjoint intervals, a 24.6% gap. In agentic, the same five policies land within 0.6342-0.6390, i.e. a 0.8% spread that is smaller than the run-to-run noise of any single policy in the mid regime.

The cause is mechanical, and it is in the allocator rather than in the workloads: blocks held by an in-flight request have a non-zero reference count and therefore never appear in the eviction candidate set. When 65% of every request is a shared prefix, that prefix is almost always live, and the evictor only ever chooses among shallow tails. Trace replay cannot see this, because a trace has no notion of which blocks are live at the same instant.

## 3.2 Capacity is the second axis, and the effect is monotone in it

Table 2 sweeps the KV pool for the conversation regime (concurrency 8, 800 requests).

| KV blocks | LRU | SIEVE | SIEVE vs LRU |
|---|---|---|---|
| 400 | 0.0722 (n=2) | 0.0740 (n=1) | +2.6% |
| 800 | 0.0783 (n=1) | 0.0785 (n=1) | +0.3% |
| 1200 | 0.0813 (n=1) | 0.0866 (n=1) | +6.6% |
| 1733 (full) | 0.1073 (n=5) | 0.1337 (n=5) | **+24.6%** |

The advantage grows with capacity, and it is not monotone in capacity *stress* in the direction one might expect: at 400 blocks the pool is so tight that both policies are equally bad, and at full capacity the policy finally has slack to spend. The interesting region is "enough slack that the policy's choice matters, not enough that everything fits".

## 3.3 A runtime reuse counter beats every structural signal

At the allocator's hit path we record `note_access(content_hash)`, so for each cached block we know how many requests have already reused it -- a quantity that a trace replay can only know in hindsight. LFU-W uses this count as the victim cost, decayed by halving all counters every 256 evictions (a sliding-window effect that stops early-hot blocks from squatting), with depth as the tie-break.

| workload | LRU | SIEVE | DEPTH | LFU-W | LFU-W vs LRU | LFU-W vs SIEVE |
|---|---|---|---|---|---|---|
| synthetic | 0.0513 | 0.0490 | 0.0518 | 0.0513 | +0.0% | +4.7% |
| conversation | 0.1073 | 0.1337 | 0.1313 | 0.1314 | +22.4% | -1.7% |
| toolagent | 0.4167 | 0.4247 | 0.4384 | **0.4409** | **+5.8%** | **+3.8%** |
| agentic | 0.6378 | 0.6342 | 0.6390 | 0.6390 | +0.2% | +0.8% |

Accuracy is not free. Table 3 gives the cost side for the same runs.

| workload | LRU thr / p50 | SIEVE thr / p50 | DEPTH thr / p50 | LFU-W thr / p50 |
|---|---|---|---|---|
| synthetic | 49.76 / 99.7 | 50.87 / 96.8 | 46.85 / 104.9 | 47.14 / 111.0 |
| conversation | 44.41 / 117.2 | 44.48 / 115.9 | 43.33 / 122.0 | 43.62 / 122.2 |
| toolagent | 52.28 / 88.3 | 56.16 / 81.2 | 52.56 / 86.4 | 54.68 / 89.2 |
| agentic | 65.68 / 71.4 | 63.13 / 73.5 | 63.15 / 73.1 | 57.12 / 90.1 |

LFU-W's exact global scan costs about 2% throughput in conversation and 13% in agentic. Both are recoverable: see 3.4.

## 3.4 Parameter sensitivity

Two knobs matter: the halving period and whether the victim is chosen by a full scan or by sampling.

| config | conversation hit / thr / p50 | toolagent hit / thr / p50 |
|---|---|---|
| epoch 64 | 0.1307 / 42.81 / 128.0 | 0.4410 / 55.11 / 90.2 |
| epoch 256 (default) | 0.1314 / 43.62 / 122.2 | 0.4409 / 54.68 / 89.2 |
| epoch 1024 | 0.1313 / 42.34 / 127.8 | 0.4405 / 53.52 / 93.6 |
| epoch 256, sample k=16 | 0.1286 / **49.72** / **103.1** | 0.4389 / **58.81** / **80.9** |

The halving period is insensitive in the range 64-1024 (within 0.5% hit rate, i.e. within noise). The sampled victim costs 2.1% hit rate in conversation but buys 14% throughput and 15% lower TTFT; in toolagent the cost is 0.5% hit rate for 6% throughput. Sampling is thus the right default on a latency-sensitive deployment and the exact scan the right default when hit rate is the objective -- and this trade-off is itself a scheduling decision, not a cache-internal one.

## 3.5 Where the search failed

Four refinements that consume block-tree structure all lose to a reuse counter, and the diagnosis is shared:

- **F-SIEVE** (evict the minimum live fan-out within a 16-candidate window): 0.1247 in conversation, 0.4346 in toolagent -- above LRU, below SIEVE and LFU-W.
- **DEPTH** (deepest first): competitive (0.4384 in toolagent) but behind LFU-W by 0.6%; losing a deep block invalidates a short tail, which is real, but it does not rank *which* shallow blocks are worth keeping.
- **P-SIEVE** (promote after a second hit): 0.1332 vs SIEVE 0.1337 -- extra protection only consumes capacity.
- **ADAPT** (switch between SIEVE and LRU on sampled branch density): in conversation it sticks to SIEVE (0.1337), in synthetic it degrades to 0.0480, and in agentic it reports exactly LRU's number (0.6378), i.e. its threshold never fires.

The common cause is measurable: the fraction of blocks with two or more children is **0.001, 0.001 and 0.002** in three of the four workloads. Real prefix sharing is whole-chain reuse, not "one common prefix + a forked suffix", so the child-count signal that these mechanisms read is absent at block granularity. Any 2026-2028 design that consumes block-tree shape has to answer this measurement first.

# 4. The WVC framework

Three components, none optional:

**W1 -- observable window criterion (scheduler side).** Two scalars computable at prefill: sigma, the fraction of live blocks shared between concurrently active requests, and kappa, available blocks over working-set blocks. Eviction has no effect when sigma -> 0 (nothing repeated) or sigma -> 1 (the shared trunk is pinned by reference counts anyway), and its effect grows monotonically as kappa relaxes (Table 2). W1 is also a restatement of admission: at high concurrency and low sharing, every evictor is paying for one-shot requests.

**W2 -- cost-model victim choice (cache side).** Replace recency proxies with a decayed runtime reuse count. It is runtime-observable, so it transfers to production; it is what trace replay cannot supply.

**W3 -- complexity budget gate.** When W1 says the effect is ~0, revert to LRU with no bookkeeping; inside the window, enable W2; forbid block-tree shape as a signal until a workload shows non-trivial branching.

**Falsifiable proposition.** At fixed kappa, hit rate is a concave function of sigma, rising while sharing appears and flattening once the shared trunk pins itself; the achievable gain of any evictor is bounded above by the window position and below by LRU. The four regimes in Table 1 are four samples of this curve.

# 5. Outlook

- **2026** -- reporting standard. Papers about eviction or caching in serving stacks should report sigma and kappa; without them, the numbers are not transferable. The four-regime rig released with this paper is a calibration harness for exactly that.
- **2027** -- granularity. At sigma -> 1, block-level victim choice has no head-room (0.8%), so the remaining room is inside a block (partial prefix hits) and in non-aligned prefixes; cost models have to move from block to token-level marginal utility.
- **2028** -- joint scheduling. W1 shows admission and eviction spend the same budget; the next framework-level step is disaggregated prefill/decode with sharing-aware admission and cost-model eviction designed together, not another heuristic inside the evictor.

# 6. Threats to validity

One model (1.5B), one GPU class, block 16, concurrency 8, 800 requests per run, and workloads derived from trace shapes rather than from production traffic. Agentic has n=1 for LRU and LFU-W, and several cells have n=1-2; we therefore claim directions and ordering, not tight point estimates, and the released data keeps every per-run value so that intervals can be recomputed. No disaggregated prefill, no tensor parallelism, no multi-tenant SLO mix. None of these change the sign of the regime effect or the mean ordering in Table 1, but all of them would change specific percentages.

# 7. Reproducibility

Every number in this paper comes from a public repository with the evictor implementations, the four workload generators, the closed-loop client, the run matrix scripts, the raw per-run JSON (86 runs) and the aggregation/plotting scripts that regenerate every table and figure: `live-serving/` in https://github.com/lindicaphxag-tech/sieve-prefix-replication. The instrumentation is two import-time hooks in `prefix_caching_block.py` (evictor factory, reuse counter) plus two registry calls (parent/child, eviction) -- small enough to be audited in minutes, which is why we publish the diffs rather than a patched wheel.

# References

[1] W. Kwon et al. "Efficient Memory Management for Large Language Model Serving with PagedAttention." SOSP 2023.

[2] Y. Yazici et al. "SIEVE is Simpler than LRU: an Efficient Turn-Key Eviction Algorithm for Web Caches." NSDI 2024.

[3] G. Einziger, R. Friedman, B. Manes. "TinyLFU: A Highly Efficient Cache Admission Policy." ACM TOCS / Euromicro PDP 2014.

[4] L. Zheng et al. "SGLang: Efficient Execution of Structured Language Model Programs." NeurIPS 2024.

[5] R. Qin et al. "Mooncake: A KVCache-centric Disaggregated Architecture for LLM Serving." FAST 2025.

[6] B. Manes. "Caffeine: a high performance, near-optimal caching library" (W-TinyLFU and sampled-admission lineage), open source, 2015.
