# Benchmark Summary

## Scope executed in this environment

Attempted baseline vs patched runs with:
- `project/catch_build` and `-j4/-j8`
- baseline binary: `/tmp/ninja_baseline`
- patched binary: `/tmp/ninja_patched`

## Result

All attempted clean-build runs failed at CMake regeneration stage because referenced source path was incomplete in this environment. No valid wall-time or long-tail edge timing could be collected.

See raw data:
- `experiment_results/catch2_scheduler_benchmark.json`

## Acceptance decision for this round

**Not ready to accept yet** (insufficient performance evidence).

### Why

- Functional build of Ninja itself succeeds after patch.
- But required multi-project benchmark evidence is unavailable in this snapshot.

### Next iteration

1. Restore source trees for Catch2/fmt/googletest/json-c/cxxopts.
2. Re-run clean-build benchmark matrix (`-j4`, `-j8`) for baseline and patched binaries.
3. Evaluate regression guardrail: reject if representative project regresses materially.
