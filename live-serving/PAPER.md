---
title: "Reuse-Count Victim Choice for LLM Prefix Caches: A Measurable Window, a Protocol Confounder, One Counterexample, and a Selector That Lives in the Scheduler"
author: "Zhibo Zhang (Hangzhou Dianzi University) - ORCID 0009-0007-3533-1941"
date: "2026-11-24"
abstract: |
  One eviction pair (SIEVE vs LRU) across ten regimes (110 live vLLM runs, two production traces with 1.26 G block accesses and 625 k sessions, three control workloads) spans +24.6 % to -1.32 pp in block-hit ratio. (1) The comparison is protocol-dependent: a controlled replay-order experiment leaves LRU invariant to <=0.012 pp while SIEVE moves up to 0.077 pp, so numbers published only under a simulator default are not portable to an engine. (2) Reuse geometry refutes our earlier reading: production reuse is deep (mean depth 1,199-3,654 blocks) versus 1.5-1.9 blocks in our microbenchmarks, and frequency mass separates the traces better than sigma_cross, which is higher on the trace that loses; no single axis is a law, and sigma_cross >= 0.25 is necessary but not sufficient. (3) Ablation shows the selector's pressure term was redundant and vetoed real wins: the sigma-only selector reaches 0.1159 against LRU 0.0980 (+18.3 %), zero negative windows in 12/12 cells and 69 % of the attainable increment.
---

## Claims

1. **Window measurable and protocol-dependent.** d(SIEVE-LRU) spans +24.6 % to -1.32 pp; the same trace and pool give different d under different block-registration orders. LRU is invariant, SIEVE is not.
2. **Selector above the allocator, one criterion not two.** Frontend sigma gate + allocator victim rule: +18.3 % relative, 0/12 negative cells. The same rule estimated inside the allocator degenerates to LRU (negative result, kept).
3. **The counterexample stays a counterexample.** chutes satisfies sigma_cross 0.645, F(64k) 0.942 and hit 0.727, and loses at 64k/256k/1M: -1.32 / -0.18 / -0.042 pp - 31x smaller over a 16x pool, never a sign change.

## Live (single node, 110 runs)

vLLM 0.6.6.post1, Qwen2.5-1.5B-Instruct, 12 GiB shared device, block 16, 800 req/cell, evictor swapped at the only `make_evictor` site with an `[evictor]` line printed every run as a quality gate.

| workload | LRU | SIEVE | LFU-W | d(SIEVE-LRU) | note |
|---|---|---|---|---|---|
| synthetic | 0.0513 | 0.0490 | 0.0513 | -4.5 % | cross-stream, 1-2 blocks deep |
| conversation | 0.1073 | 0.1337 | 0.1314 | **+24.6 %** | five runs, disjoint intervals |
| toolagent | 0.4167 | 0.4247 | 0.4409 | +1.9 % | LFU-W wins here |
| agentic | 0.6342-0.6390 | same band | same band | ~0 | pi ~ 0.65, trunk pinned |

Capacity sweep on conversation (400/800/1200/1733): +2.6 / +0.3 / +6.6 / +24.6 %. Throughput is not attributable on a shared device and is not reported.

## Production traces, engine-faithful order

`cacheMon/PrefixSim`, uniform cost model, `block_id=prefix`, `n_self_eviction=0`; locality from the single-pass parsers `gapmeas.cpp`, `depthmeas.cpp`, `freqmeas.cpp`.

| trace | accesses | distinct | sessions | sigma_cross (of reuse) | mean reuse depth | accesses/distinct |
|---|---|---|---|---|---|---|
| freeinference | 656,240,179 | 39,578,367 | 222,934 | **0.1699** | 3,653.9 blocks | 16.58 |
| chutes | 603,642,254 | 139,518,804 | 402,221 | **0.6451** | 1,198.7 blocks | 4.33 |

sigma_cross divides by reuse accesses; the earlier 0.160 / 0.496 divided by all accesses and is withdrawn. F(tau = C/lambda): free 0.978/0.978/0.988/0.994, chutes 0.890/0.942/0.967/0.989 at 16k/64k/256k/1M.

| trace / pool | LRU | SIEVE | d, prefix-order | d, simulator default |
|---|---|---|---|---|
| freeinference 64k | 0.917430 | 0.917779 | **+0.035 pp** | +0.014 pp |
| freeinference 256k | 0.936230 | 0.936293 | +0.006 pp | +0.004 pp |
| freeinference 1M | 0.938125 | 0.938170 | +0.005 pp | +0.004 pp |
| chutes 64k | 0.726831 | 0.713628 | **-1.320 pp** | -1.700 pp |
| chutes 256k | 0.748745 | 0.746994 | -0.175 pp | -0.164 pp |
| chutes 1M | 0.761574 | 0.761158 | -0.042 pp | -0.075 pp |

Protocol result: LRU is invariant to <=0.012 pp across replay orders while SIEVE shifts up to 0.077 pp (-22 % of the 64k loss, -44 % of the 1M loss, +0.011 pp at 256k). `prefixsim` defaults to deepest-first; engines register shallow-to-deep. Since the baseline does not move, an eviction comparison published only under a simulator default is not comparable to an engine's.

## Reuse geometry: two single-axis readings die

| trace | single-touch blocks/accesses | >=17 count mass | >=65 mass | d at 1M |
|---|---|---|---|---|
| freeinference | 53.0 % / 3.2 % | **0.859** | **0.612** | +0.005 pp |
| chutes | 56.4 % / 13.0 % | 0.521 | 0.323 | -0.042 pp |

Reuse depth shares (1 / 2-4 / 5-16 / 17-64 / 65-256 / 257-1024 / 1025-4096 / 4097-16384): free 0.05/0.14/0.44/1.42/4.96/15.67/**41.07**/36.20 %; chutes 0.11/0.30/1.13/4.18/15.17/**39.02**/35.40/4.59 %. Control workloads: mean depth 1.63 / 1.51 / 1.91 blocks.

Supported: cross-stream reuse (sigma_cross >= 0.25 in every live cell), pool not already holding the working set (hit <= 0.85), evictor actually asked (pi small); loss monotone in pool where the window is closed; a one-criterion frontend estimator recovers most of the attainable gain.

Withdrawn: the two-factor conjunction law (sigma_cross x coverage); the claim that cross-stream reuse in real traffic is frequent and shallow; the pressure criterion rho-hat. chutes satisfies the first and second and loses everywhere.

Open: replay fixes pi = 0 (needs an engine-side pi histogram); sigma alone is one-sided and would fire on chutes (needs lineage from `session_id`/`parent_chat_id`, supported by the format, unimplemented here).

## Selector SEW-2 and its ablation

| C | workload | LRU | SIEVE | LFU-W | **SEW-2** | oracle | inside % | regret | recovered |
|---|---|---|---|---|---|---|---|---|---|
| 400 | conversation | 0.0681 | 0.0708 | 0.0671 | **0.0707** | 0.0712 | 100 | -0.05 pp | 100 % |
| 800 | conversation | 0.0732 | 0.0755 | 0.0836 | **0.0784** | 0.0849 | 100 | -0.65 pp | 44 % |
| 1200 | conversation | 0.0791 | 0.0869 | 0.0910 | **0.0883** | 0.0940 | 100 | -0.56 pp | 62 % |
| 1733 | conversation | 0.0980 | 0.1229 | 0.1106 | **0.1159** | 0.1277 | 100 | -1.18 pp | 69 % |
| 1733 | toolagent | 0.4534 | 0.4642 | 0.4582 | **0.4534** | 0.4664 | 0 | -1.30 pp | 0 % |
| 1733 | synthetic | 0.0498 | 0.0530 | 0.0438 | **0.0498** | 0.0575 | 0 | -0.77 pp | 0 % |

Ablation over 3 workloads x 4 capacities (`ablate.py`): sigma-and-rho 0/12 negative (0.0681 at C=400, 0.1121 at C=1733); sigma-only 0/12 negative (0.0707, 0.1159); rho-only 1/12 negative (0.0681, 0.1121, and -0.05 pp on toolagent at C=1200). rho-hat vetoed windows in which SIEVE wins, including the 400-block cell where the live engine had already measured +2.6 %. A three-action bandit with exploration reaches 0.1037 / 0.1067 versus 0.1159 and never selects LFU-W: a policy needing warmed counters cannot win the window it is given.

## 2026 / 2027 / 2028

- **2026 - delivered.** Report replay/registration order, sigma_cross over reuses, and pi (share of pool held by refcount>0 blocks) with every eviction result; all three are free engine counters and two of them changed our conclusion twice.
- **2027 - designed, half built.** Design selectors, not evictors: estimator in the frontend, actuator in the allocator (12/12 non-negative, 69 % of attainable gain). Failure mode named: a one-sided gate cannot reject deep, cross-stream, eviction-hostile reuse; closing it needs lineage from session/parent ids on the production traces.
- **2028 - a pilot result, not a plan.** With prefill/decode disaggregation, placement decides whether a prefix can be met at all. The predictor we can already compute is pi: in the agentic cell pi ~ 0.65 and the four-policy spread collapsed to 0.8 % (0.6342-0.6390), so at pi > 0.5 the evictor is not a first-order decision - measured, not predicted. Agenda: report that threshold per deployment, and test whether prefix-affinity placement pushes pi below it.

## Reproduce and artefacts

Reproduce: `g++ -O2 -o gapmeas gapmeas.cpp -lzstd` and likewise `depthmeas.cpp`, `freqmeas.cpp`; `./depthmeas trace/chutes.lcp.zst`; `PrefixSim/_build/bin/prefixsim --trace trace/chutes.lcp.zst --cache-size 64k --algo lru,sieve --replay-order prefix-order`; `python3 router_sim.py --capacity 1733`; `python3 ablate.py`.

`PAPER_detail.md` (long version), `INNOVATION.md`, `TRACE_EVIDENCE_V3.md`, `SELECTOR_ABLATION.md`, `FRAMEWORK_2026_v5.md`, `ROUTER_RESULTS.md`, `SELECTOR_VARIANTS.md`, `gapmeas.cpp`, `depthmeas.cpp`, `freqmeas.cpp`, `depth_live.py`, `ablate.py`, `router_sim.py`, `router_bandit.py`, `offline_sim.py`, `reuse_profile.py`, `out/` (110 live runs), `trace/`, `PrefixSim/` (fork with `traceReuseStat`).
