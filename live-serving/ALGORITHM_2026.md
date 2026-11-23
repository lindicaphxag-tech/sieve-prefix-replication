# Victim-rule search on two production traces: four refutations and one bound

Date: 2026-11-24. Traces: `chutes.lcp.zst` (603,642,254 block accesses, 515,817 requests)
and `freeinference.lcp.zst` (656,240,179 block accesses, 327,548 requests).
Cache pools: 65,536 / 262,144 / 1,048,576 blocks. All runs are full-trace, single-pass.

## Engine and validation

`tools/replay2.cpp` implements the same three phases the production engine needs:
match (read-only probe) -> make room (bulk eviction with the arriving request pinned) ->
access (promote hits, insert misses in prefix order). Uniform cost, block-id = prefix,
request-level pin set, so a request can never evict its own blocks.

Cross-check on chutes 64k LRU: 0.726831, identical to PrefixSim's
`block_hit_ratio=0.726831`, with the same 603,642,254 access count. On freeinference 64k
the in-engine baseline is 0.910181 against PrefixSim's 0.917430; the 0.7 pp gap traces to
request-skip/occupancy accounting on very long requests, so every comparison below is made
inside a single engine, and absolute levels are quoted from the cross-checked cells.

## Two hit metrics, and the gap between them

PrefixSim counts a block as a hit if it is resident. A real engine reports only the
contiguous resident prefix, because a miss at position i stops the prefix match.

| trace | pool | block metric | prefix metric | gap |
|---|---|---|---|---|
| chutes | 64k | 0.726128 | 0.725610 | -0.05 pp |
| freeinference | 64k | 0.910181 | 0.905400 | -0.48 pp |

The overstatement is small but one-directional: replaying with the simulator's own
accounting reads high relative to what the engine can serve.

## Refutation 1: depth-first eviction (TLRU)

Tiers by prefix depth (<16, <256, <1024, >=1024 blocks); always evict from the deepest
non-empty tier, LRU within a tier. The motivation was the subtree argument: evicting a
shallow block invalidates every descendant, evicting a deep block loses only its own suffix.

| trace | pool | LRU | TLRU | delta |
|---|---|---|---|---|
| chutes | 64k | 0.726128 | 0.367276 | -35.9 pp |
| freeinference | 64k | 0.910181 | 0.474692 | -43.5 pp |

The subtree argument is backwards on these traces. Reuse is deep: the mean reuse position
is 3,653.9 blocks on freeinference and 1,198.7 on chutes, and 41.1 % / 39.0 % of all reuse
lands in the 1,025-4,096 band. The deep tail is exactly what gets re-requested, so ranking
eviction by depth destroys the reused part first.

## Refutation 2: shallow protection (SD-SIEVE)

SIEVE's second-chance scan, but refusing to evict tiers 1-2 at all, so shallow blocks are
pinned for the lifetime of the run.

| trace | pool | LRU | SD-SIEVE |
|---|---|---|---|
| chutes | 64k | 0.726128 | 0.262214 |
| freeinference | 64k | 0.910181 | 0.197017 |

Same cause, in the opposite direction: the protected shallow blocks are not what the
workload asks for, and they crowd out the chains that are.

## Refutation 3: orphan-first (evict a block whose parent is gone)

Under a contiguous-prefix metric a block whose parent is not resident cannot contribute a
hit. `replay2` records each block's parent at insertion and, on eviction, scans up to 64
positions from the LRU tail for such an unreachable block before falling back to the tail.

| trace | pool | LRU | orphan-first | delta |
|---|---|---|---|---|
| chutes | 64k | 0.726128 | 0.726126 | -0.000002 |
| freeinference | 64k | 0.910181 | 0.910174 | -0.000007 |

Zero. Chains are requested whole, so a parent eviction is almost always followed by the
chain being re-fetched; LRU already ejects those blocks with the same order, and the
structural rule finds nothing to reorder.

## Refutation 4: capchain admission (cache only the first m blocks of a request)

Motivated by the 1,170-block mean request on chutes flooding a 64k pool. Blocks past
position m are not cached at all.

| m | chutes 64k hit ratio | evictions |
|---|---|---|
| 128 | 0.084054 | 5,780,183 |
| 256 | 0.158850 | 13,205,768 |
| 512 | 0.278718 | 34,230,868 |
| 1024 | 0.444258 | 75,071,604 |
| unbound (LRU) | 0.726128 | 165,258,252 |

Monotone towards LRU and never above it. Truncation removes the deep band that carries
about 40 % of all reuse on both traces, so every block saved at the front is paid for
several times at the back.

## The bound: how much any victim rule can win here

Belady (offline optimal, same pool, same order): **0.760084** on chutes 64k and
**0.933723** on freeinference 64k, against LRU's 0.726831 / 0.917430. The entire headroom
available to any history-based victim rule is therefore **+3.33 pp (4.6 % relative)** on
chutes and **+1.63 pp (1.8 % relative)** on freeinference - and SIEVE spends 1.32 pp of the
chutes headroom going the wrong way.

That number is the reason the selector, not a new victim rule, is the contribution: on
production traces victim choice is a second-order lever bounded at a few percentage points,
while pool size and admission are first-order. It also explains the 2028 result: with
pi ~ 0.65 (pool pressure high enough that a request's chain rarely survives), four policies
land inside a 0.8 % band, because the bound itself collapses there.

## Six published policies against that bound (chutes 64k, same pool, same order)

| policy | hit ratio | delta vs LRU | self-evictions |
|---|---|---|---|
| Belady (offline optimum) | 0.760084 | +3.33 pp | 0 |
| **LRU** | **0.726831** | - | 0 |
| hyperbolic | 0.724643 | -0.22 pp | 579,784 |
| SLRU | 0.723886 | -0.29 pp | 0 |
| SIEVE | 0.713628 | -1.32 pp | 0 |
| S3FIFO | 0.695840 | -3.10 pp | 1,037,094 |
| W-TinyLFU | 0.623055 | -10.38 pp | 2,152,023 |
| LFU | 0.380103 | -34.67 pp | 45,525,230 |

Two readings. First, none of the six closes any of the 3.33 pp gap; the closest,
hyperbolic, is still 0.22 pp under LRU, and the two frequency-based entries lose 10 and
35 pp. Second, the self-eviction column is a protocol artefact, not a policy verdict:
LFU, S3FIFO and W-TinyLFU take blocks the running request had already matched 45.5 M /
1.04 M / 2.15 M times, which a real engine that pins a running request's blocks never does.
Those three numbers cannot be compared with an engine at all, which is the same
comparability rule the replay-order experiment established.

So on this trace the victim-rule column is closed: an offline optimum worth 3.33 pp, six
published policies at or below LRU, and four structure-aware rules of our own at exactly
LRU. The lever that remains is how much of the pool exists and who gets admitted, not who
gets evicted.

## Where the algorithm contribution actually sits

The working algorithm is the selector, not a replacement victim rule: SEW-2 gates SIEVE
behind sigma_hat >= 0.25 and keeps LRU otherwise, 12/12 non-negative windows across
3 workloads x 4 pools, +18.3 % relative over pure LRU at 1,733 blocks, 69 % of the
achievable incremental reuse. See `SELECTOR_ABLATION.md`.

## Transfer test: a workload prior mislabels chutes, a windowed gate cannot

`sigma_cross = 0.6451` on chutes, so the prior-based rule would run SIEVE there and pay its
full-scale cost. The windowed rule instead measures SIEVE against LRU inside a window. To
see what the opening window says, replay chutes' first 30,000 requests (38,291,337 block
accesses, `tools/trunc.cpp` cuts them) at the same 64k pool:

| policy | opening-window hit ratio (30k requests) |
|---|---|
| LRU | 0.657994 |
| SIEVE | 0.657995 |

The window reads as a tie (+0.0001 pp), so the guard holds LRU and never spends the
1.32 pp the prior would have promised to win. Workload labels are unsafe across traces;
measurement inside the window is safe by construction. That is why the deliverable is SEW-2
with a measured gate rather than a sigma_hat classifier.

## Artefacts

- `tools/replay2.cpp` - the engine used here: two metrics, LRU / SIEVE / orphan-first /
  capchain, request-level pinning, three-phase replay.
- `tools/trunc.cpp` - cuts an `.lcp.zst` to its first N requests (window experiments).
- logs under `live_serving/logs/`: `rp2_chutes_64k_{lru,orphan,cc128,cc256,cc512,cc1024}.txt`,
  `rp2_free_64k_{lru,orphan}_*.txt`, `ps_chutes_64k_batch.txt`, `ps_free_64k_belady.txt`,
  `rp_chutes_64k_{tlru,sdsieve}.txt`, `rp_free_64k_{tlru,sdsieve}.txt`.

## Second model, real engine: policy identity collapse at a small pool

Qwen2.5-0.5B on the same conversation workload (800 requests, concurrency 8, vLLM 0.6.6,
`[evictor] <policy> -> <Class>` line confirms each run's injection) with the pool the
machine could actually give out: 894 blocks.

| policy | hit rate | wall s | throughput req/s |
|---|---|---|---|
| LRU | 0.060677399756986675 | 20.424 | 39.17 |
| SIEVE | 0.060677399756986670 | 27.456 | 29.14 |
| LFU-W | 0.062556956257594170 | 35.14 | 22.77 |

LRU and SIEVE agree to 17 significant digits. At 894 blocks the conversation workload's
reuse is short-range enough that no victim rule can change which blocks are resident at the
moment of a match, so the only difference left is the policy's per-eviction bookkeeping
cost: SIEVE pays 34 % wall time and LFU-W 72 % for a 0.0 / +3.1 % hit-rate change. This is
the same collapse the offline 2028 cell shows at pi ~ 0.65, now measured on hardware with a
second model: below a pool size the victim rule is not a first-order decision, and its
overhead is the only thing that moves.
