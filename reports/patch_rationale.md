# Patch Rationale

## Strategy

Use weighted critical-path scheduling with a lightweight estimated cost model:

`priority(edge) = estimated_cost(edge) + max_downstream_path_cost(edge)`

where downstream path cost is accumulated by the existing reverse topological propagation in `Plan::ComputeCriticalPath()`.

## Estimated cost source and defaults

Estimated cost is inferred at runtime from stable edge metadata:

1. `edge->rule().name()` (preferred)
2. Fallback: coarse command-shape checks (`-c`, `ar`, `ld`, shared-link markers)

Default mapping:
- phony = 0
- compile-like = 2
- archive-like = 4
- link-like = 8
- generic command = 3

This avoids binding by output-name substring and keeps semantics unchanged.

## Anti-starvation tie-breaker

Tie-break behavior remains deterministic by edge id ordering when priorities are equal. This avoids unstable ordering and prevents pathological oscillation among equal-priority edges.

## Risk and rollback

- Scope is limited to scheduler weight heuristic in `src/build.cc`.
- No dependency/dirty-state semantics are modified.
- Rollback is a single-file revert.
