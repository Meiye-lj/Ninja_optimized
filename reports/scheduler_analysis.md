# Scheduler Analysis

## Phase 1: Current Ninja scheduling path

- `Plan::PrepareQueue()` computes edge critical-path weights and then schedules initial ready edges. Current implementation uses `critical_path_weight` and a priority queue over ready edges.
- `Plan::FindWork()` pops highest-priority ready edge; pool and jobserver checks can still delay execution.
- `Pool::RetrieveReadyEdges()` drains delayed edges based on pool depth constraints.

### Why waiting/saturation can happen

1. Ready queue priority is only as good as edge cost estimation quality.
2. If non-phony edges are treated with similar cost, long link/archive edges may start too late.
3. Pool delays and dependency frontiers can expose idle worker windows when long blocker edges are not started early enough.

## Phase 2: Task graph and timing profile (repo evidence)

Data source:
- `project/catch_build/ninja_analysis_summary.json` (existing analyzer output).
- `experiment_results/catch2_scheduler_benchmark.json` (new run attempts in this environment).

### Edge/task breakdown (Catch2 build graph)

- Total edges: **151**
- Task type distribution:
  - compile: 107
  - custom: 12
  - io: 4
  - link: 2
  - phony: 25
  - regen: 1

Builtin/meta edges are excluded from executable command accounting by Ninja semantics (`phony` not counted as command edges in `Plan::EdgeWanted`).

### Environment limitation on runtime profiling

In this container snapshot, `project/catch_build/build.ninja` attempts CMake regeneration from `/home/lyu/BuildAC/Ninja_optimized/project/Catch2`, but the source tree there does not contain `CMakeLists.txt`, so clean-build benchmarking fails before command execution.
