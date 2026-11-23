---
Title: "SIEVE is Simpler than LRU: an independent reimplementation, and a test of whether a turn-key eviction policy transfers to prefix caches"
Author:
  - name: Zhibo Zhang
    affiliation: 1
Address:
  - code:    1
    address: Hangzhou Dianzi University, Hangzhou, Zhejiang, China
Contact:
  - 24061721@hdu.edu.cn
Publication:
  received:  Nov, 23, 2026
  accepted:  pending
  published: pending
  volume:    pending
  issue:     pending
  date:      pending
  number:    pending
Repository:
  article:   "https://github.com/lindicaphxag-tech/sieve-prefix-replication/tree/main/article"
  code:      "https://github.com/lindicaphxag-tech/sieve-prefix-replication/tree/main/code"
  data:      "https://github.com/lindicaphxag-tech/sieve-prefix-replication/tree/main/data"
Reproduction:
  - "Y. Zhang, J. Yang, Y. Yue, Y. Vigfusson, and K. V. Rashmi. SIEVE is Simpler than LRU: an Efficient Turn-Key Eviction Algorithm for Web Caches. NSDI 2024. https://www.usenix.org/conference/nsdi24/presentation/zhang-yazhuo"
Bibliography:
  bibliography.bib
---

# Introduction

SIEVE [@sieve2024] proposes that an eviction policy for web caches does not need
recency promotion to be effective: one first-in-first-out queue, one visited bit
per object, and a hand that walks from the tail toward the head, evicting the
first object it finds that has not been visited. The paper reports three things
that this replication touches:

1. On the released Twitter trace used here, SIEVE should have a lower miss
   ratio than FIFO, LRU and CLOCK, with the advantage growing at larger
   cache sizes.
2. Across its whole corpus, SIEVE "has a lower miss ratio than 9 state-of-the-art
   algorithms on more than 45% of the 1559 traces".
3. SIEVE is a *turn-key* primitive, in the sense that it can be dropped in
   wherever FIFO or LRU is used today.

The authors released code and traces (a C++ simulator, `libCacheSim`, and one
10-million-request Twitter trace inside the repository). I did not compile or
execute that simulator: no C++ toolchain was available in my environment, and
a compiled run would have been a reproduction of the same code rather than a
replication. Instead I wrote an independent implementation of the policies
from the paper's description and, for the one place where the description is
ambiguous (how the hand advances after an eviction), from the published
eviction source file `Sieve.c`. The source was read, not run.

Claim 2 is the one I cannot test, and the reason is arithmetic rather than
technical: it depends on a corpus that is mostly not public. Section
"Results" makes that explicit, because a reader who wants to re-derive the
headline number should know before trying.

Claim 3 is the one I extend. The cache workloads that dominate 2026-2028
systems are not object caches of independently reusable objects: they are
prefix caches for large language model inference, where a request reuses a
chain of key/value blocks and the chain is only reusable from its first block.
That changes the objective. I therefore ran the same policy set on four
publicly released prefix-cache traces, where the unit of reuse is a block
chain rather than an object.

# Methods

## Independent implementation

All policies are written in Python 3.13 with the standard library only, in
`sieve_bytes.py` (byte-capacity object cache) and `kv_sim.py`
(block-capacity prefix cache). No code from `libCacheSim` is imported or
vendored.

Byte capacity is used throughout the object-cache experiment, because the
original paper sizes caches at 0.1% and 10% of the trace footprint in
bytes, not in objects. An object larger than the whole cache is counted as a
miss and is not admitted, which is what the released simulator does.

For SIEVE the published description leaves the post-eviction hand position
slightly ambiguous. `Sieve.c` resolves it: the hand is set to the evicted
node's `prev` pointer, the walk advances with `prev` and wraps to the tail,
a hit sets the frequency field to one rather than incrementing it, and
objects whose field is above the current threshold are retained with their
field decremented.

## Validation before measurement

Three checks were run before any miss ratio was reported, because an
independent implementation that is subtly wrong produces numbers that look
plausible.

* A byte-capacity policy with every object of size one must match its
  count-capacity counterpart exactly. Five policies at two capacities: all
  match (`validate_bytes.py`).
* SIEVE implemented with arrays must match SIEVE implemented as an explicit
  node graph that follows `Sieve.c` pointer by pointer. Two traces at two
  capacities: identical miss counts, 93975, 89798, 10456 and 7191
  (`check_sieve.py`).
* LRU must match `collections.OrderedDict` semantics, and cache occupancy
  must never exceed capacity.

An earlier intermediate version of the reference SIEVE, written with list
index arithmetic, disagreed with the node version because the hand index
shifted when an object was removed from the middle of the list. That version
was discarded. The disagreement is worth noting because it is exactly the
kind of defect that would have made a replication report a false
discrepancy.

## Prefix-cache model

A request carries a chain of block hashes. Reuse requires a contiguous
match from the first block, so the reusable prefix is the leading run of
resident blocks and everything after the first gap must be recomputed. Capacity
is a number of blocks. On a miss the missing suffix is inserted in order, evicting
until it fits.

Two metrics are reported: the block ratio, the fraction of requested blocks
that were reused, and the token ratio, which weights each block by the
measured tokens-per-block of its request. The block ratio has a hard ceiling
of `1 - distinct_blocks / requested_blocks`, which is what the cache would
achieve with unbounded capacity; it is reported alongside every result so
that a policy that looks poor can be distinguished from a workload that
offers little reuse.

## Time-aware ablation

The reuse model ignores that a request holds its key/value blocks while it is
in flight. A second experiment adds arrival timestamps, pins the blocks of
in-flight requests so that they cannot be evicted, and completes a request
after `computed_prefill_tokens / prefill_rate + output_tokens * decode_latency`.
The parameters are declared because they are assumptions, not measurements:
prefill 80 tokens per millisecond and decode 20 milliseconds per token, with
the reuse results also reported for a cache in which nothing is pinned.

## Workloads

Object cache: `twitter_cluster52_10m.csv.zst` from the SIEVE repository,
10,000,000 requests over 897,664 distinct objects, footprint 174,722,570 bytes,
mean object size 201.9 bytes.

Prefix caches: the four traces released with Mooncake [@mooncake2024],
`conversation_trace.jsonl`, `mooncake_trace.jsonl`,
`toolagent_trace.jsonl` and `synthetic_trace.jsonl`, with 12,031, 23,608,
23,608 and 3,993 requests, and 182,790, 183,166, 183,300 and 43,924 distinct
blocks. Blocks are about 512 tokens.

I did not contact the authors of either artifact.

# Results

## The per-trace claim reproduces

Table 1 gives the object miss ratio on the released 10-million-request
Twitter trace at the two cache sizes the paper uses.

Table: Object miss ratio on `twitter_cluster52_10m`, byte capacity at 0.1% and 10% of the 174,722,570-byte footprint. Lower is better. SIEVE is best at both sizes.

| capacity | LRU | FIFO | CLOCK | FIFO-Reinsertion | SIEVE |
| --- | --- | --- | --- | --- | --- |
| 0.1% (174,722 B) | 0.385526 | 0.413157 | 0.413114 | 0.385027 | 0.374601 |
| 10% (17,472,257 B) | 0.137120 | 0.154165 | 0.154165 | 0.136976 | 0.129208 |

SIEVE lowers the miss ratio by 9.3% and 16.2% relative to FIFO, and by 2.8%
and 5.8% relative to LRU, at the small and large cache size respectively. The
direction matches the paper, including the observation that SIEVE's margin
over FIFO grows at the large cache size. Since the paper reports per-trace
results only graphically, this comparison is to the direction and magnitude
family rather than to a published number for this trace; that is a limit of
this replication, not a discrepancy.

CLOCK and FIFO are within 43 misses of each other at both sizes, which is
consistent with them sharing an eviction candidate at the tail.

## The aggregate claim is not re-derivable from the released artifact

The headline figure, "lower miss ratio than 9 state-of-the-art algorithms on
more than 45% of the 1559 traces", cannot be recomputed by anyone outside the
authors, for two independent reasons.

First, the corpus is 95.7% proprietary. Counting from the paper's Table 1
and its Figure 5: 1273 traces of CDN1 and 219 of CDN2 are proprietary, and
the public share is 54 Twitter, 5 Meta KV, 3 Meta CDN, 3 Wiki CDN and 2
Tencent Photo, which is 67. 1492 of 1559 traces, or 95.7%, cannot be obtained.

Second, the released repository ships traces and a simulator but no per-trace
result files and no script that regenerates the figures. The released data
directory contains one 10-million-request Twitter trace, one synthetic Zipf
trace, and two small I/O traces, so even the public share cannot be re-run
from the artifact alone; the remaining public traces are hosted elsewhere.

This is a statement about what the artifact supports, not a criticism of
the result. The paper does label the two CDN datasets as proprietary. The
consequence for a reader is simply that the aggregate percentage is
author-computed, while the per-trace behaviour is checkable, and it is the
per-trace behaviour that Table 1 addresses.

## The turn-key claim does not transfer to prefix caches

Table 2 applies the same policies to the four Mooncake prefix-cache traces.
Because reuse needs the chain to be contiguous from the first block, a
policy that evicts an interior block invalidates every resident block
downstream of it.

Table: Block reuse ratio (fraction of requested prefix blocks that were resident) on four prefix-cache traces. The ceiling column is `1 - distinct/requested`, the reuse obtainable with unbounded capacity. LRU is better than SIEVE in all eight settings.

| trace | ceiling | 5% LRU | 5% SIEVE | 20% LRU | 20% SIEVE |
| --- | --- | --- | --- | --- | --- |
| conversation | 0.3664 | 0.1954 | 0.1269 | 0.3446 | 0.3068 |
| mooncake | 0.5526 | 0.4496 | 0.3987 | 0.5486 | 0.5251 |
| toolagent | 0.5525 | 0.4494 | 0.3985 | 0.5485 | 0.5250 |
| synthetic | 0.6396 | 0.1548 | 0.1051 | 0.3905 | 0.3271 |

Eight of eight comparisons favour LRU, by 4.5% to 54%. SIEVE wins exactly one
setting in the sweep, the smallest cache on the conversation trace: at 1% of
distinct blocks SIEVE reaches 0.0582 against LRU's 0.0523.

The interpretation is structural. SIEVE's design goal is to evict an
unpopular object that sits in the middle of the insertion order, and its
advantage on object caches comes from doing so without recency promotion. In
a prefix cache that same behaviour destroys chains whose first block is
evicted while later blocks remain resident, and the surviving blocks cannot
be reused at all. LRU's recency order incidentally protects the shared
first blocks, which is the property prefix reuse needs.

A second reading of the same data is that little is left to win. At 20%
capacity LRU already reaches 94% to 99% of the ceiling on three traces, so
on these workloads a policy cannot gain much over plain LRU regardless of
how clever it is. The remaining headroom is at small capacity, where
LRU reaches only 24% to 53% of the ceiling.

## Three attempts to beat LRU that did not work

The gap at small capacity motivated three prefix-aware policies. All three
are reported because two of them failed.

Dead-block reclamation. A resident block is useful only if all of its
ancestors are resident; once an ancestor is evicted, the whole resident
subtree can never serve a hit. Evicting that space first should be free
capacity. It is not: across eight settings the reuse ratio was identical to
LRU to four decimal places. Instrumentation showed the mechanism was active,
with 94.8% of evictions coming from the unreachable set (211,474 of 223,979,
peak unreachable set 245 blocks). The explanation is that LRU's tail is
already made of exactly those blocks. Eviction order among worthless blocks
changes nothing.

Leaf-first eviction. Instead of evicting the least recently used block,
evict a block with no resident descendant; when that leaves its parent
childless, the parent becomes a candidate, so a cold branch is released
along its own path rather than orphaned. This was positive in every setting
but small: +0.37%, +0.17% and +0.23% on the conversation trace at 1%, 5%
and 20% capacity; +0.05%, +0.11% and +0.01% on the two Meta-derived traces;
+10.99%, +1.20% and +0.65% on the synthetic trace. The one large gain
coincides with the smallest cache (439 blocks) on the trace with the
shallowest reuse.

Depth-truncated admission. Admitting only the first K blocks of a chain
should help at small capacity, because shallow blocks are shared by more
requests than deep ones. It does, but only in one regime. On the conversation
trace at 1% capacity K=4 raises reuse from 0.0523 to 0.0728, a gain of 39.2%,
while at 5% and 20% capacity K=4 falls to 0.0847 and 0.0851, losing 57% and
75% against LRU. Fixed K is not a policy; it is a bet that capacity is
smaller than the mean chain length, and the mean chain length here is 24
blocks.

Taken together, these three results say that the obvious ways to exploit
chain structure are either already exploited by LRU or only exploitable
under a fixed truncation that fails as capacity grows. I did not find a
prefix-aware policy that dominates LRU on these four traces, and I would
rather report that than tune a policy against them.

## What concurrency changes

Table 3 compares a cache where in-flight requests pin their blocks against
the same cache where nothing is pinned, at three capacities.

Table: Effect of pinning in-flight key/value blocks. Capacities are 0.5%, 1% and 5% of distinct blocks. The pinning branch denies a request when the block budget is entirely occupied by live requests.

| trace | blocks | reuse pinned | reuse unpinned | gap | denials | peak pinned |
| --- | --- | --- | --- | --- | --- | --- |
| conversation | 913 | 0.0426 | 0.0420 | +1.49% | 524 | 913 |
| conversation | 1827 | 0.0484 | 0.0507 | -4.54% | 0 | 1685 |
| conversation | 9139 | 0.1964 | 0.1944 | +1.04% | 0 | 1663 |
| mooncake | 915 | 0.3288 | 0.3330 | -1.25% | 988 | 915 |
| mooncake | 1831 | 0.3378 | 0.3392 | -0.42% | 0 | 1698 |
| mooncake | 9158 | 0.4462 | 0.4443 | +0.42% | 0 | 1698 |

The direct cost of concurrency is concentrated at the smallest capacity:
4.4% and 4.2% of requests cannot be admitted to the cache at all, because
the live requests already occupy the entire budget. Above 1% capacity
denials disappear and the reuse difference is inside a few percent in
either direction. Concurrency therefore matters as an admission problem
rather than as an eviction problem, at least on these traces.

# Conclusion

The per-trace claim of the original article replicates: with an
independently written implementation, SIEVE has the lowest miss ratio of
the five policies tested on the released 10-million-request Twitter trace,
by 9.3% and 16.2% against FIFO at the small and large cache sizes. The
aggregate claim over 1559 traces does not replicate in any externally
checkable sense, because 1492 of those traces are proprietary and no
per-trace results are released.

The extension reverses the turn-key claim for the workload class that
matters most in current systems. On four public prefix-cache traces, LRU
beats SIEVE in all eight capacity settings, by as much as 54%. The mechanism
is structural: SIEVE's eviction target can orphan a prefix chain, while LRU's
recency order protects the shared first blocks. Three prefix-aware policies
tested here did not beat LRU, and two of them produced gains below one
percent.

What would change this conclusion is a workload in which capacity is
smaller than the chain length, where truncation at admission wins by 39%
in the one setting measured, and a policy that adapts the admitted depth
to available capacity without failing at larger capacity. I did not
implement such a policy, and I do not claim the negative result extends
beyond the four traces and the three capacities tested.

# Limitations

Only one of the 54 released Twitter traces was run. The baselines are LRU,
FIFO, CLOCK, FIFO-Reinsertion and SIEVE; ARC, TwoQ, LHD, LIRS and S3-FIFO
are not implemented here, so no statement in this article compares SIEVE
against the nine algorithms of the original evaluation. The prefix
experiment ignores batching, queueing and scheduler effects, and its
latency parameters are declared assumptions rather than measurements. The
object-cache experiment uses a single machine with no GPU; every number
reported is reproducible on a CPU in minutes from the released traces.

# References
