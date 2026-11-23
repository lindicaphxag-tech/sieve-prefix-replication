# TRACE EVIDENCE UPDATE (2026-11-24)

补两条生产 trace 回放的收尾读数，用来修正 `PAPER.md` / `FRAMEWORK_2026.md` 中的两处措辞。

## chutes @256,144 blocks（4× 池）

| algo | block hit ratio | Δ vs LRU |
|---|---|---|
| lru | 0.748757 | — |
| sieve | 0.747115 | **−0.16 pp** |
| s3fifo | 0.746891 | **−0.19 pp** |

64k 时是 −1.70 pp / −4.22 pp，4× 池子后收缩到 −0.16 pp / −0.19 pp：**SIEVE 仍然输，但输幅随容量单调收缩**。这正是"池是否活过一次复用间隔"这条判据的预测（chutes 跨 session 间隔中位 7,218 s，256k 池只覆盖 139.5 M 地址空间的 0.19%）。

## freeinference @16,384 blocks（24 GiB）

不报数。该点在本机 3 GB 内存下被 OOM 杀死两次（单次运行 >55 min 无结果，且与并行的 chutes 256k 回放争内存），已中止。16k 的结论不依赖它：freeinference 的 σ_cross=0.160 已经在 64k/256k/1M 三个容量上给出 +0.014/+0.011/+0.011 pp，容量放大 16 倍后策略差仍在 0.003 pp 内，容量的口子不在这里。

## 口径

- uniform cost model、block_id=prefix、n_self_eviction=0（与 `PrefixSim` 默认一致）。
- 三条读数的 `n_req_skipped=0`、`n_unexpected_eviction=0`（除 s3fifo 的 `n_unobserved_eviction_round` 计数），说明没有走"超长请求暂存"路径。
