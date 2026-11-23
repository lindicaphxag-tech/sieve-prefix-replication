# Independent replication of SIEVE, and its transfer to prefix caches

This repository holds the code, the article and the result record for a
ReScience C submission. It asks two things about SIEVE, the eviction policy
published at NSDI 2024:

1. Does an independently written implementation reproduce the reported
   advantage of SIEVE over FIFO, LRU and CLOCK on the released trace?
2. Does that advantage transfer to prefix caches, where a request reuses a
   chain of key/value blocks and the chain is reusable only from its first
   block?

Short answers: the per-trace claim reproduces, the transfer does not hold,
and the aggregate claim over 1559 traces cannot be re-derived from the
released artifact because 1492 of those traces are proprietary.

No source file from `libCacheSim` is imported, vendored or compiled here.
Every policy is implemented from the published description, with the
published eviction source read (not run) to resolve how the SIEVE hand
advances after an eviction.

## Layout

```
article/   the submission (Zhang-2026.md plus the ReScience template)
code/      the independent implementations and the experiment drivers
data/      results.md, the full record of every run reported in the article
```

## Reproducing

Python 3.13, standard library only. Two external traces are downloaded by
script; neither is redistributed here. They are Apache-2.0 and whatever the
Mooncake release states, so both are fetched from their own repositories:

```
python code/fetch_big2.py     # 10M-request Twitter trace from cacheMon/NSDI24-SIEVE (0.16 GiB footprint)
python code/fetch_kv.py       # Mooncake FAST'25 conversation trace
python code/kv_multi.py       # fetches the other three Mooncake traces too
```

Then, in order, with the working directory holding both the scripts and the
trace folders they create:

```
python code/validate_bytes.py   # byte-capacity == count-capacity when every object has size 1
python code/check_sieve.py      # array SIEVE == node SIEVE that follows Sieve.c pointer by pointer
python code/run_big.py          # object cache, 10M requests, 0.1% / 1% / 10% of footprint
python code/kv_sim.py           # prefix cache, conversation trace, 1% / 5% / 20% of distinct blocks
python code/kv_multi.py         # prefix cache, all four traces
python code/kv_dead.py          # unreachable-block reclamation against LRU
python code/kv_leaf.py          # leaf-first eviction against LRU
python code/kv_trunc.py         # depth-truncated admission against LRU
python code/kv_pin.py           # in-flight pinning ablation, two traces, three capacities
```

Runtime on a laptop CPU: `run_big.py` about four seconds per policy per
capacity; the prefix simulations a few seconds each; the four-trace sweeps
under a minute. Nothing here needs a GPU.

## What the numbers say

Object cache, `twitter_cluster52_10m`, object miss ratio:

| capacity | LRU | FIFO | CLOCK | FIFO-Reinsertion | SIEVE |
| --- | --- | --- | --- | --- | --- |
| 0.1% of footprint | 0.385526 | 0.413157 | 0.413114 | 0.385027 | 0.374601 |
| 10% of footprint | 0.137120 | 0.154165 | 0.154165 | 0.136976 | 0.129208 |

Prefix cache, four Mooncake traces, block reuse ratio, LRU against SIEVE at
5% and 20% of distinct blocks: LRU wins all eight comparisons, by 4.5% to
54%. SIEVE wins only the smallest-cache setting of one trace.

## Building the article

The article is Markdown with a YAML front matter, converted by pandoc and then
compiled by xelatex, following the ReScience `article/Makefile`:

```
pandoc --standalone --template=rescience-template.tex --biblatex \
       --bibliography=bibliography.bib -M "crossrefYaml=crossref.yaml" \
       --output Zhang-2026.tex Zhang-2026.md
xelatex Zhang-2026.tex; biber Zhang-2026; xelatex Zhang-2026.tex; xelatex Zhang-2026.tex
```

Two packages are missing from the current upstream template and were added
locally, otherwise `\includegraphics` and every pandoc table fail to compile:
`letltxmacro` (for the `\LetLtxMacro` around `\includegraphics`) and `array`
plus `longtable` (for pandoc's table column spec). With those three lines
added the build is error-free.

## Scope and honesty notes

* Only one of the 54 released Twitter traces was run.
* Baselines are LRU, FIFO, CLOCK, FIFO-Reinsertion and SIEVE. ARC, TwoQ,
  LHD, LIRS and S3-FIFO are not implemented, so nothing here compares SIEVE
  against the nine algorithms of the original evaluation.
* The prefix model ignores batching, queueing and scheduling, and its
  latency parameters are declared assumptions.
* Three prefix-aware policies were tried and none of them beat LRU. The
  article reports the two that produced no measurable gain as well as the
  one that gained only in a fixed regime.

## License

Code: MIT. Article text: CC-BY-4.0, matching ReScience C.
