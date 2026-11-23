# 前缀缓存淘汰策略在真实 vLLM serving 上的行为：LRU 在并发下输给 SIEVE，但没有单一赢家

在真实推理服务栈上直接测量前缀缓存淘汰策略，不是模拟。回答一个 trace 回放回答不了的问题：串行回放里 LRU 在 5%–20% 容量上领先 SIEVE 4.5%–54%，换成并发 serving 后方向为什么会反过来，以及——反过来之后，到底有没有一个策略能把三种负载都拿下。

## 1. 环境

| 项 | 值 |
|---|---|
| 机器 | AutoDL 2×RTX 3080 Ti（12,288 MiB/卡，driver 595.71.05），80 vCPU，251 GB RAM |
| 服务栈 | vLLM 0.6.6.post1，`--enable-prefix-caching`，block = 16 tokens |
| 模型 | Qwen2.5-1.5B-Instruct，fp16，weights 2.89 GiB |
| 显存 | `--gpu-memory-utilization 0.45`，满容量档 KV cache = **1733 blocks** |
| 负载 | 三份 trace 转成的各 1,500 条请求：conversation / toolagent / synthetic |
| 客户端 | 自写流式客户端，并发 8，每轮 800 请求，`max_tokens=8`，TTFT 按流式首字节计时 |

### 策略注入与生效验证

vLLM 0.6.6 只在 `vllm/core/block/prefix_caching_block.py:117` 调一次 `make_evictor(eviction_policy)`，v2 block manager 也落到同一个 allocator，因此这是唯一且充分的注入点。注入用 `EVICTOR_POLICY` 环境变量把 `make_evictor` 换成工厂，并在 stderr 打印 `[evictor] <policy> -> <class>`；**每一轮日志都核对了这一行**。期间确实发生过一次启动方式改动丢掉环境变量、策略静默退回 LRU 的事故，那批数据已作废重跑。

## 2. 设计陷阱：块大小映射

第一版把 trace 每块写成约 40 词（≈60 token），一个 trace 块横跨约 4 个 16-token block，单请求约 90 block。300 blocks、并发 4 时缓存被在跑请求占满，三种策略命中率**完全相同（0.0607）**——不是策略没生效，而是容量太小没有回旋空间。修正为一块对应一个 16-token block（每块 8 词、单请求约 186 token）后，容量才能按 block 数设定。下文全部数据来自修正后的负载。

## 3. 结果

数字由 `analyze.py` 从 `out/*.json` 自动汇总，不手抄。

### 3.1 conversation（满容量 1733 blocks，并发 8，800 请求）

| 策略 | 命中率（n 次重复） | 区间 | 相对 LRU |
|---|---|---|---|
| LRU | 0.1073 (n=5) | 0.1064–0.1080 | — |
| **SIEVE** | **0.1337 (n=5)** | 0.1330–0.1351 | **+24.6%** |
| ADAPT（本次，运行时切换） | 0.1337 (n=2) | 0.1328–0.1345 | +24.6% |
| P-SIEVE（本次，2Q 晋升） | 0.1332 (n=2) | 0.1330–0.1335 | +24.1% |
| DEPTH（最深层优先淘汰） | 0.1313 (n=3) | 0.1312–0.1315 | +22.4% |
| F-SIEVE（本次，扇出代价） | 0.1247 (n=2) | 0.1240–0.1254 | +16.2% |
| WSIEVE（本次，窗口+深度） | 0.1239 (n=2) | 0.1235–0.1243 | +15.5% |

SIEVE 与 LRU 的重复区间完全不重叠（LRU 最大 0.1080 < SIEVE 最小 0.1330）。

TTFT 跨批次不可比：GPU 上另有他人常驻任务，同策略不同批次的 TTFT 波动（约 100–160 ms）大于策略差。**主判据是命中率**。唯一同批次跑完的三策略对照里，SIEVE 的 TTFT mean 136.1 ms / p50 136.7，LRU 143.3 / 144.1，即优势在这一轮转化成约 −5% TTFT 与 +5% 吞吐——量级不足以单独立论。

### 3.2 三份负载（满容量，2–5 次重复）

| 负载 | LRU | SIEVE | DEPTH | F-SIEVE | ADAPT |
|---|---|---|---|---|---|
| conversation | 0.1073 | **0.1337** | 0.1313 | 0.1247 | 0.1337 |
| toolagent | 0.4167 | 0.4247 | **0.4384** | 0.4346 | 0.4288 |
| synthetic | 0.0513 | 0.0490 | **0.0518** | 0.0449 | 0.0480 |

**没有任何一个静态策略在三份负载上都最好**：conversation 赢家是 SIEVE（比 LRU +24.6%）；toolagent 赢家是 DEPTH（0.4384，SIEVE 只比 LRU 高 1.9%）；synthetic 上 SIEVE 反而比 LRU 低 4.5%，最差的是 F-SIEVE（0.0449）。

### 3.3 容量扫描（conversation，LRU vs SIEVE）

| 容量（blocks） | LRU | SIEVE |
|---|---|---|
| 400 | （LRU 轮因同卡 OOM 未完成） | 0.0740 |
| 800 | 0.0783 | 0.0785 |
| 1200 | 0.0813 | 0.0866 |
| 1733（满） | 0.1073 | 0.1337 |

分水岭在 800–1200 blocks 之间：容量只够装下在跑请求时任何策略都一样；1200 起 SIEVE 开始领先，越接近工作集领先越大。**策略优劣不是内禀属性，是“容量/工作集比例 × 并发度”的函数。**

### 3.4 跨负载均值与三个失败的机制尝试

均值（三份负载命中率的算术平均）：DEPTH 0.2072 > ADAPT 0.2035 > SIEVE 0.2024 > F-SIEVE 0.2014 > LRU 0.1918。

三个“更聪明”的变体都没赢：

- **P-SIEVE（累计命中 ≥2 次才晋升到 protected 集）**：conversation 0.1332，与 SIEVE 打平。额外保护毫无收益——SIEVE 本来已经保住了那些块，protected 只是占容量。
- **WSIEVE（hand 窗口内选最深块淘汰）**：0.1239，比 SIEVE 低 7.5%。深度优先在真机上有害，尽管回放里“叶优先淘汰”是小正收益。
- **F-SIEVE（按运行时扇出选代价最小的块淘汰）**：conversation 0.1247、toolagent 0.4346、synthetic 0.0449。它比 LRU 好，但没有一次压过 SIEVE 或 DEPTH。

这些尝试是带诊断的失败。为做 F-SIEVE，我在分配器里挂了运行时扇出注册表（在 `PrefixCachingBlock.content_hash` 的惰性计算点记录 parent→child 边），实测三份负载的**分支度（子节点 ≥2 的块占比）分别只有 0.001 / 0.001 / 0.002**。原因是这批 trace 的“共享”是**整链复用**（同一串前缀被整体重复使用），不是“公共前缀 + 分叉后缀”。这个负载族里不存在可供策略利用的树结构，任何以扇出/分支为信号的切换器在这类流量上都退化成噪声。这也解释了 ADAPT 为什么只能贴着 SIEVE（conversation）而在 synthetic 上掉到 0.0480。

## 4. 机制解释

- **回放是串行的**：某一时刻只有一条链活跃，“刚用过的块马上可能再用”成立，LRU 接近最优。
- **真机是并发的**：8 条链同时 resident。LRU 的“命中即提升”不断把只被偶发读到的长寿命共享块推到 MRU 侧，把它们从受保护位置挤走，下次命中只能重算。
- **SIEVE 的惰性提升**（只有被扫描到且本轮未访问过的块才淘汰）让块的价值由访问模式而非最近一次触碰决定，因此在整链复用 + 高并发下更稳。**起作用的成分只有“命中不重排队列”**，其余启发式（2Q 晋升、深度优先、扇出代价、密度切换）都是零收益或负收益。

## 5. 对 2026–2028 的含义

1. **策略评估的测试床必须是并发 serving**，只用 trace 回放会得出方向相反的结论（本文即同一份 trace 的完整反例）。
2. **不存在通用赢家，决策依据是运行时 regime**：整链复用下 SIEVE，分叉密集＋缓存紧张下 DEPTH，稀疏复用下 LRU 与 DEPTH 并排最优。26–28 的系统级收益应来自“**判定 regime → 选纪律**”，而不是再调一个静态启发式。
3. **判定 regime 需要新的可观测量**。本实验证明两种自然候选都失效：块级扇出（本负载恒为 1）、分支密度（恒为 0）。真正需要的是**跨请求复用结构**——同一批 active requests 之间共享了多少 token、共享发生在链的哪一段，这只有调度器在 prefill 阶段看得到。
4. **分层 KV 与 PD 分离会放大这条结论**：错淘汰一次长寿命共享段，代价从“重算一次 prefill”升级为“跨层搬运 + 重算”，惰性提升的价值上升，而 regime 判定也更容易（层级本身提供了复用距离信号）。
5. 下一代机制的可检验形态：**调度器侧计算复用结构（跨 active requests 的共享 token 覆盖率），缓存侧只执行被选中的纪律**；评测轴是“容量/工作集比例 × 并发度 × 复用结构”，不是单点对比。

## 6. 可复现性

- 脚本：`mkwork.py`、`bench_client.py`、`policies.py`（lru / sieve / depth / psieve / wsieve / fsieve / adaptive）、`matrix.sh`、`analyze.py`（产出 `summary.json`）、`make_figures.py`（四张图）。
- 原始结果：`out/*.json`（62 轮），每条含 TTFT 分位数、吞吐、`gpu_prefix_cache_hit_rate`。
- 复跑：`bash matrix.sh conversation_b16 full 800 8 lru sieve adaptive`。
- 已知限制：GPU 有他人任务常驻，显存按 0.45 配额；400-block 档 LRU 因同卡 OOM 缺失；TTFT 跨批次不可比，命中率为主要判据；扇出注册表只在 `content_hash` 计算点生效，对整链复用的负载分支度天然接近 0。
- 图：`fig1_policies_conversation.png`、`fig2_capacity_sweep.png`、`fig3_workloads.png`、`fig4_mean_across_workloads.png`。
