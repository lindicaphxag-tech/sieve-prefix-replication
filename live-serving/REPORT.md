# 前缀缓存淘汰策略在真实 vLLM serving 上的行为：为什么 LRU 在并发下输给 SIEVE

本目录是在真实推理服务栈上直接测量前缀缓存（prefix caching）淘汰策略的实机实验，不是模拟。它回答一个 trace 回放回答不了的问题：在 5%–20% 容量、串行回放的条件下 LRU 全面领先 SIEVE 4.5%–54%，为什么换成并发 serving 后方向会反过来。

## 1. 环境

| 项 | 值 |
|---|---|
| 机器 | AutoDL 2×RTX 3080 Ti（12,288 MiB/卡），80 vCPU，251 GB RAM |
| 服务栈 | vLLM 0.6.6.post1，`--enable-prefix-caching`，block = 16 tokens |
| 模型 | Qwen2.5-1.5B-Instruct，fp16，weights 2.89 GiB |
| 显存 | `--gpu-memory-utilization 0.45`，KV cache = **1733 blocks**（满容量档） |
| 负载 | 三份 trace 转成的各 1,500 条请求：conversation / toolagent / synthetic |
| 客户端 | 自写流式客户端，并发 8，每轮 800 请求，`max_tokens=8`，TTFT 按流式首字节计时 |

### 策略注入与实际生效的验证

vLLM 0.6.6 的 `PrefixCachingBlockAllocator` 只在 `vllm/core/block/prefix_caching_block.py:117` 调一次 `make_evictor(eviction_policy)`；v2 block manager 路径也落到同一个 allocator，因此这是唯一注入点。在该模块导入期用 `EVICTOR_POLICY` 把 `make_evictor` 换成工厂，并在 stderr 打印 `[evictor] <policy> -> <class>`；**每一轮都核对了这行日志**（期间确实发生过一次策略静默退回 LRU 的事故，那批数据已作废重跑）。

## 2. 设计陷阱：块大小映射

第一版把 trace 的每块写成约 40 词（≈60 token），一个 trace 块横跨约 4 个 16-token block，单请求约 90 block。300 blocks、并发 4 时缓存已被在跑请求占满，三种策略命中率**完全相同（0.0607）**——不是策略没生效，而是容量太小没有回旋空间。修正为一块对应一个 16-token block（每块 8 词、单请求约 186 token）后，容量才能按 block 数设定。

## 3. 结果

conversation，满容量 1733 blocks，并发 8，800 请求：

| 策略 | 命中率 | 区间 | 相对 LRU |
|---|---|---|---|
| LRU | 0.1073 (n=4) | 0.1064–0.1080 | — |
| **SIEVE** | **0.1339 (n=3)** | 0.1333–0.1351 | **+24.8%** |
| DEPTH | 0.1313 (n=3) | 0.1312–0.1315 | +22.4% |
| P-SIEVE（本次 2Q 变体） | 0.1332 (n=2) | 0.1330–0.1335 | +24.1% |
| WSIEVE（本次窗口+深度变体） | 0.1239 (n=2) | 0.1235–0.1243 | +15.5% |

SIEVE 与 LRU 的重复区间不重叠（LRU 最大 0.1080 < SIEVE 最小 0.1333）。

三份负载（满容量）：

| 负载 | LRU | SIEVE | DEPTH |
|---|---|---|---|
| conversation | 0.1064 | 0.1351 | 0.1313 |
| toolagent | 0.4167 | 0.4221 | 0.4379 |
| synthetic | 0.0511 | 0.0493 | 0.0518 |

容量扫描（conversation，LRU vs SIEVE）：800 blocks 0.0783 vs 0.0785（持平）；1200 blocks 0.0813 vs 0.0866；1733 blocks 0.1073 vs 0.1339。分水岭在 800–1200 blocks 之间：容量小到只装得下在跑请求时，任何策略都一样。

## 4. 机制解释

- 回放串行：同一时刻只有一条链活跃，"刚用过的块马上可能再用"成立，LRU 接近最优。
- 真机并发：8 条来自不同前缀家族的链同时 resident，LRU 的"命中即提升"不断把偶发读到的长寿命共享前缀推到 MRU 侧，trunk 被挤掉后只能重算。
- SIEVE 惰性提升（只有被扫描到且本轮未访问过的块才淘汰）让价值由访问模式而非最近触碰决定。
- 反向验证：P-SIEVE 的 2Q 晋升与 SIEVE 打平（额外保护不带来收益，SIEVE 本来已保住这些块）；WSIEVE 的深度优先掉到 0.1239（−7.5%），说明深度不是跨家族共享价值的代理。真正起作用的成分只有"命中不重排队列"。

## 5. 对 2026–2028 的含义

1. 策略评估的测试床必须是并发 serving；只用 trace 回放可能得出方向相反的结论（本文即反例）。
2. 淘汰目标应是"子树存活价值/字节"，近似量是"跨活跃家族的复用次数"，只有运行时可见（running requests 及其前缀深度），trace 里拿不到——这正是早期 CAPA 在 trace 上崩掉的原因。
3. 分层 KV（GPU/CPU/SSD）与 PD 分离会放大该结论：错淘汰一次 trunk 的代价从重算 prefill 升级为跨层搬运加重算。
4. 下一代机制：并发感知准入 + 惰性淘汰联合设计，以"容量/工作集比例 × 并发度"为二维扫描轴做评测。

## 6. 可复现性

脚本：`mkwork.py`、`bench_client.py`、`policies.py`（lru/sieve/depth/psieve/wsieve）、`matrix.sh`、`analyze.py`（产出 `summary.json`）、`make_figures.py`。原始结果在 `out/*.json`（含 TTFT 分位数、吞吐、`gpu_prefix_cache_hit_rate`）。已知限制：GPU 1 有他人任务常驻；400-block 档 LRU 因同卡 OOM 缺失；TTFT 跨批次不可比，命中率为主要判据。
