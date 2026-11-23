# live-serving experiment

Prefix-cache eviction policies measured on a real vLLM 0.6.6 stack rather than on trace replay.
See [REPORT.md](REPORT.md) for the full setup, results and the mechanism argument.

Key result (conversation trace, 800 requests, concurrency 8, 1733 KV blocks):
SIEVE reaches a 0.1339 prefix-cache hit rate in 3 repeats versus 0.1073 for LRU (n=4),
+24.8% relative, with non-overlapping ranges -- the opposite direction from the same
trace replayed serially, where LRU led SIEVE by 4.5%-54%.

Two proposed variants did not beat SIEVE: P-SIEVE (promote a block to a protected
set after two hits) lands at 0.1332, i.e. it only ties; WSIEVE (evict the deepest of
the next window of candidates) lands at 0.1239. The operative ingredient is SIEVE's
lazy promotion -- hits must not reorder the queue.

## Files

| file | role |
|---|---|
| `REPORT.md` | full write-up: environment, design pitfalls, tables, mechanism, implications |
| `mkwork.py` | trace -> request list; one trace block is mapped to exactly one 16-token vLLM block |
| `bench_client.py` | streaming client measuring TTFT and scraping `/metrics` |
| `policies.py` | lru / sieve / depth / psieve / wsieve evictors behind vLLM's `Evictor` API |
| `matrix.sh` | `matrix.sh <workload> <blocks|full> <requests> <concurrency> <policy...>` |
| `analyze.py` | aggregates `out/*.json` into tables and `summary.json` |
| `make_figures.py` | regenerates the three figures from `summary.json` |

## Reproducing

```
# inject the policy: in vllm/core/block/prefix_caching_block.py replace the
# make_evictor call with a factory keyed on EVICTOR_POLICY (see REPORT.md §1)
python mkwork.py traces/conversation_trace.jsonl work/conversation_b16.json --max-requests 1500 --max-depth 24 --words 8
EVICTOR_POLICY=sieve CUDA_VISIBLE_DEVICES=1 python -m vllm.entrypoints.openai.api_server \
  --model <Qwen2.5-1.5B-Instruct> --served-model-name models --enable-prefix-caching \
  --max-model-len 2048 --gpu-memory-utilization 0.45 --dtype float16 --port 8100 --disable-log-requests
python bench_client.py --base http://127.0.0.1:8100 --work work/conversation_b16.json --model models --concurrency 8 --requests 800 --max-tokens 8 --out out/run.json
```

Every run used in the report printed `[evictor] <policy> -> <class>` on stderr; runs
without that line were discarded.
