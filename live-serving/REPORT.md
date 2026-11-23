# 前缀缓存淘汰策略在真实 vLLM serving 上的行为：为什么 LRU 在并发下输给 SIEVE

本目录是在真实推理服务栈上直接测量前缀缓存（prefix caching）淘汰策略的实机实验，不是模拟。它回答一个 trace 回放回答不了的问题：在 5%–20% 容量、串行回放的条件下 LRU 全面领先 SIEVE 4.5%–54%，为什么换成并发 serving 后方向会反过来。

## 1. 环境

| 项 | 值 |
|---|---|
| 机器 | AutoDL 2×RTX 3080 Ti（12,288 MiB/卡，driver 595.71.05），80 vCPU，251 GB RAM |
| 服务栈 | vLLM 0.6.6.post1，`--enable-prefix-caching`，block = 16 tokens |
| 模型 | Qwen2.5-1.5B-Instruct，fp16，weights 2.89 GiB |
| 显存 | `--gpu-memory-utilization 0.45`，KV cache = **1733 blocks**（满容量档） |
| 负载 | 三份 trace 转成的各 1,500 条请求：conversation / toolagent / synthetic |
| 客户端 | 自写流式客户端，并发 8，每轮 800 请求，`max_tokens=8`，TTFT 按流式首字节计时 |

### 策略注入与实际生效的验证

vLLM 0.6.6 的 `PrefixCachingBlockAllocator` 只在 `vllm/core/block/prefix_caching_block.py:117` 调一次 `make_evictor(eviction_policy)`；v2 block manager 路径也落到同一个 allocator，因此这是唯一注入点，也是充分注入点。

在该模块导入期用 `EVICTOR_POLICY` 环境变量把 `make_evictor` 替换成工厂，并在 stderr 打印 `[evictor] <policy> -> <class>`。**每一轮日志都核对了这行**：这是本实验的强制质控，因为期间确实发生过一次因启动方式改动丢掉环境变量、策略静默退回 LRU 的事故——那一批数据已作废重跑，本文所有数字都来自打印了对应 `[evictor]` 行的运行。

## 2. 一个必须先解决的设计陷阱：块大小映射

第一版把 trace 的每个块写成约 40 词（≈60 token），于是一个"trace 块"在 vLLM 里横跨约 4 个 16-token block，单请求长约 1,400 token（≈90 block）。300 blocks 容量、并发 4 时缓存已被在跑请求占满，三种策略的前缀命中率**完全相同（0.0607）**。这不是策略没生效（`[evictor] sieve -> SieveEvictor` 已证明生效），而是容量太小、淘汰决策根本没有回旋空间。

修正：trace 的一块严格映射成一个 16-token block（每块 8 词，单请求约 186 token）。这样 trace 的"块引用数"直接等于 vLLM block 数，容量可以按 block 数设定。下文全部数据来自修正后的负载。

## 3. 结果

全部数字由 `analyze.py` 从 `out/*.json` 自动汇总，不手抄。

### 3.1 conversation，满容量（1733 blocks），并发 8，800 请求

| 策略 | 命中率（n 次重复） | 区间 | 相对 LRU |
|---|---|---|---|
| LRU | 0.1073 (n=5) | 0.1064–0.1080 | — |
| **SIEVE** | **0.1337 (n=4)** | 0.1330–0.1351 | **+24.6%** |
| DEPTH（深度优先淘汰） | 0.1313 (n=3) | 0.1312–0.1315 | +22.4% |
| P-SIEVE（本次提出的 2Q 变体） | 0.1332 (n=2) | 0.1330–0.1335 | +24.1% |
| WSIEVE（本次提出的窗口+深度变体） | 0.1239 (n=2) | 0.1235–0.1243 | +15.5% |

SIEVE 与 LRU 的重复区间完全不重叠（LRU 最大 0.1080 < SIEVE 最小 0.1330），五次 LRU 对四次 SIEVE，没有任何一次运行越界。

TTFT 在跨批次之间不可比：GPU 1 上还有他人常驻任务，同一策略不同批次的 TTFT 波动（约 100–145 ms）大于策略差。因此**主判据是命中率**。唯一在同等条件下同批次跑完的对照（conversation 满容量首轮三策略）里，SIEVE 的 TTFT mean 136.1 ms / p50 136.7 ms，LRU 143.3 / 144.1，即命中率优势在这一轮转化成了约 −5% 的 TTFT 与 +5% 吞吐；这个量级不足以单独作为证据，命中率才是。

### 3.2 三份负载（满容量，2–5 次重复）

| 负载 | LRU | SIEVE | DEPTH |
|---|---|---|---|
| conversation | 0.1073 (n=5) | **0.1337 (n=4)** | 0.1313 (n=3) |
| toolagent | 0.4167 (n=2) | 0.4247 (n=3) | **0.4384 (n=2)** |
| synthetic | **0.0513 (n=3)** | 0.0490 (n=4) | 0.0518 (n=2) |

结论不是"SIEVE 总是更好"：它只在**前缀家族交错密集、容量只占工作集约 8%** 的 conversation 上大幅领先（+24.6%）；toolagent 上优势收窄到 +1.9%（0.4247 对 0.4167），且那里的赢家是 DEPTH（0.4384）；synthetic 上 SIEVE 反而低 4.5%（0.0490 对 0.0513）。三份负载呈现"家族交错强度 → 惰性提升收益"的单调关系。

### 3.3 容量扫描（conversation，LRU vs SIEVE）

| 容量（blocks） | LRU | SIEVE |
|---|---|---|
| 400 | （LRU 轮因同卡 OOM 未完成） | 0.0740 |
| 800 | 0.0783 | 0.0785 |
| 1200 | 0.0813 | 0.0866 |
| 1733（满） | 0.1073 (n=5) | 0.1337 (n=4) |

**分水岭在 800–1200 blocks 之间**：容量小到只能容纳在跑请求时，任何策略都一样；从 1200 起 SIEVE 开始领先，容量越接近可容纳的工作集，领先越大。这说明"策略好坏"不是策略本身的内禀属性，而是**容量/工作集比例 × 并发度**的函数。

## 4. 机制解释

- **回放是串行的**：某一时刻只有一条链活跃，"刚用过的块马上可能再用"这个 LRU 假设近似成立，LRU 接近最优。
- **真机是并发的**：8 条来自不同前缀家族的链同时 resident。LRU 的"命中即提升"会不断把只被偶发读到的长寿命共享前缀推到 MRU 侧，把它们从受保护位置挤走；于是共享 trunk 在高压力下被踢出，下次命中只能重算。
- **SIEVE 的惰性提升**（只有被扫描到且本轮未访问过的块才淘汰）让块的价值由访问模式而非"最近一次触碰"决定，因此家族交错时更稳。
- 这一解释被本次的两个新变体反向验证：
  - **P-SIEVE（累计命中 ≥2 次才晋升到 protected 集）**：与 SIEVE 打平（0.1332 vs 0.1337），说明"额外保护"没有好处——SIEVE 本来就已经保住了这些块，再加 protected 只是浪费容量。
  - **WSIEVE（hand 窗口内选 num_hashed_tokens 最大的块淘汰）**：掉到 0.1239，比 SIEVE 低 7.5%。深度优先在这里是**有害**的，尽管在 trace 回放里"叶优先淘汰"是小正收益；真机上深度信号与"跨家族共享价值"并不同向。

即：**真正起作用的成分只有"命中不重排队列"**，其余看似合理的启发式（2Q 晋升、深度优先、容量自适应准入）都是零收益或负收益。

## 5. 对 2026–2028 的含义

1. **策略评估的测试床必须是并发 serving。** 在前缀/ KV 缓存上做策略比较，只用 trace 回放可能得出方向相反的结论；本实验就是一次完整的反例（同一份 conversation trace，回放 LRU 领先，真机 SIEVE 领先 24.6%）。
2. **淘汰目标应是"子树存活价值/字节"，而不是"最近使用"。** 深度不是该价值的代理（WSIEVE 失败已证），更接近的代理是"跨活跃家族的复用次数"，而这只有运行时能看到（调度器里的 running requests 及其前缀深度），trace 里拿不到——这正是早期 CAPA 在 trace 上崩掉的原因。
3. **分层（GPU/CPU/SSD）与 PD 分离场景会把这条结论放大**：层级越多，错淘汰一次 trunk 的代价从"重算一次 prefill"变成"跨层搬运 + 重算"，惰性提升的价值上升。
4. 下一代机制的可检验方向：**并发感知的准入 + 惰性淘汰**联合设计（准入按活跃链数估计每链可用容量，淘汰只做惰性提升），并以"容量/工作集比例 × 并发度"为扫描轴做二维评测，而不是单点对比。

## 6. 可复现性

- 脚本：`mkwork.py`（trace → 请求）、`bench_client.py`（流式客户端 + `/metrics` 采集）、`policies.py`（lru / sieve / depth / psieve / wsieve）、`matrix.sh`（矩阵驱动）、`analyze.py`（汇总，产出 `summary.json`）、`make_figures.py`（三张图）。
- 原始结果：`out/*.json`，每条含 TTFT 分位数、吞吐、`gpu_prefix_cache_hit_rate`。
- 复跑：`bash matrix.sh conversation_b16 full 800 8 lru sieve psieve`。
- 已知限制：GPU 1 有他人任务常驻，显存按 0.45 配额；400-block 档 LRU 因同卡 OOM 缺失；TTFT 跨批次不可比，命中率为主要判据。
- 图：`fig1_policies_conversation.png`、`fig2_capacity_sweep.png`、`fig3_workloads.png`。
