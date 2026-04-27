# Codex Cloud Prompt for Ninja Scheduler Optimization

你在一个云端 Codex 环境中工作。仓库根目录包含：
- `ninja-1.13.2/`：作为主要修改对象的 Ninja 1.13.2 源码
- `project/`：包含若干 Ninja 构建项目，用于功能验证和性能对比（例如 Catch2、cxxopts、fmt、googletest、json-c，以及对应的构建目录）
- `get_edge_cost/`：已有的任务抽取、构建时间分析、命令与时间估计相关脚本

## 总目标
我发现 Ninja 当前构建调度对所有任务隐式视为等权，容易在多线程构建中出现线程等待：短任务线程提前空闲，但被长任务阻塞的后继任务尚未 ready，导致并行效率快速饱和。你的任务是：

**在不破坏 Ninja 构建语义和正确性的前提下，设计并实现一种更好的任务调度策略，以降低线程等待并改善并行构建性能。**

## 关键约束
1. 不要直接大改 Ninja；先测量，再建模，再改代码，再验证。
2. 任务粒度必须是 **build edge**，不是 alias target。
3. 不能把 `phony`、`help`、`clean`、`all`、`default` 这类 builtin/meta 边当作真实执行任务。
4. 不要依赖脆弱的 `output substring in command` 方式绑定命令。
5. 所有性能改动都必须配套 benchmark 和正确性验证。
6. 如果 patch 带来构建错误、测试失败、或关键项目明显退化，应自动回退或拒绝该 patch。

## 你必须遵循的工作流
### Phase 1: 理解仓库与现状
1. 阅读仓库结构，重点查看：
   - `ninja-1.13.2/src/build.cc`
   - `ninja-1.13.2/src/build.h`
   - `ninja-1.13.2/src/graph.cc`
   - `ninja-1.13.2/src/graph.h`
   - `get_edge_cost/` 下已有脚本
2. 找出当前 ready queue、critical path、pool/jobserver、edge 调度相关逻辑。
3. 总结当前 Ninja 为什么会在多线程下出现等待与饱和。

### Phase 2: 任务图与耗时画像
1. 基于 `build.ninja` 原生语法和 Ninja 自带工具，构建完整 build edge 图。
2. 若仓库里已有 `ninja_analyzer.py` 或同类脚本，优先复用并修正，而不是重复造轮子。
3. 从 `.ninja_log` 或已有时间分析脚本中抽取历史任务耗时。
4. 输出一个结构化摘要，至少包括：
   - 总 edge 数
   - compile/link/archive/custom/phony/builtin 的数量分布
   - 每个项目的长任务 top-k
   - 关键路径上的长任务
   - 潜在“长且挡路”的阻塞任务

### Phase 3: 设计调度策略
优先尝试以下策略，而不是简单的“长任务优先”：
1. **weighted critical path priority**
2. `priority(edge) = estimated_cost(edge) + max_downstream_path_cost(edge)`
3. 在上述基础上增加一个轻量的 anti-starvation tie-breaker

要求：
- 明确说明你选择的优先级公式
- 明确 estimated_cost 的来源（历史耗时、启发式估计、或已有脚本输出）
- 明确默认值和缺失值处理逻辑

### Phase 4: 修改 Ninja
1. 仅修改与调度直接相关的文件，优先限制在：
   - `ninja-1.13.2/src/build.cc`
   - `ninja-1.13.2/src/build.h`
   - `ninja-1.13.2/src/graph.cc`
   - `ninja-1.13.2/src/graph.h`
   - 如确有必要，再新增一个很小的 `cost_model.*`
2. 保持 patch 尽量小、可解释、可回滚。
3. 避免引入大量 debug `printf`；若需要调试输出，做成可控开关。
4. 不得改变 Ninja 的依赖语义、dirty 判断语义或输出正确性。

### Phase 5: 构建与验证
对 `project/` 中的多个项目进行 baseline vs patched 对比实验。
至少选择几个不同类型项目，例如：
- `Catch2`
- `fmt`
- `googletest`
- `json-c`
- `cxxopts`

每个项目都应尽量完成：
1. clean build
2. 多线程构建（例如 `-j4`, `-j8`，视环境而定）
3. 若项目带测试，运行其测试或至少执行基础构建验证
4. 对比以下指标：
   - 总 wall time
   - 长尾任务完成时间
   - 线程等待代理指标（例如 ready 队列空转、关键长任务完成时间偏移等）
   - 是否存在明显退化

### Phase 6: 输出结论
最终必须给出：
1. 做了哪些代码修改
2. 调度策略的公式与理由
3. 各项目 benchmark 对比结果
4. 该 patch 是否值得接受
5. 如果不值得接受，说明失败原因并提出下一轮改进方向

## 质量门槛
只有在同时满足以下条件时，才建议接受 patch：
1. Ninja 能成功构建
2. 相关测试通过，或至少主要项目成功构建
3. 至少一个代表性项目有明确性能改善
4. 不能让其他关键项目出现明显退化

如果结果不稳定、不显著或有风险，请不要强行提交“看起来更聪明”的调度逻辑；要诚实说明，并保留最有前景的小改动。

## 执行风格要求
1. 先读代码和脚本，再动手。
2. 每一轮改动后都运行命令验证。
3. 每个关键判断都要基于仓库内证据，而不是凭空猜测。
4. 优先产出可落地的小步改进，而不是一次性大改。
5. 如发现仓库里已有半成品脚本或已有分析结果，优先接续利用。

## 交付物
在仓库中新增或更新这些产物（如合适）：
- `reports/scheduler_analysis.md`
- `reports/benchmark_summary.md`
- `reports/patch_rationale.md`
- `experiment_results/*.json`

并在最终答复中简洁说明：
- 你改了什么
- 为什么这样改
- 结果是否有效
