# Rewritten harness SHAs

Before this repo went public, its history was rewritten once to remove a private
host address and a local filesystem path that early commits had baked into
`providers.py`, `qwen_red.py`, `README.md`, `BENCHMARK-SPEC.md` and
`recorder/README.md`. Every commit from the first one onward changed hash.

Runs are immutable once recorded (BENCHMARK-SPEC §2b), so the `harness_git_sha`
in a receipt written before the rewrite still names the pre-rewrite commit. Those
commits are no longer reachable here. Use this table to find the commit a receipt
means:

| `harness_git_sha` in the receipt | Commit in this history | Run |
|---|---|---|
| `7521441` | `a6e2c79` | `runs/or-muse-spark-1-3-20260912_000513-fx8lfea_` |
| `25359d3` | `8ce1f48` | `runs/unrecorded/qwen3-8-27b-20260911_165204-o44za1i6` |
| `bc7b3c9` | `0c681db` | `runs/gemini-3-8-flash-20260912_181852-sid5a1mf` |

The rewrite touched only those two strings; the code and prose those commits
recorded are otherwise byte-identical, so a receipt's SHA still identifies the
harness that produced it.
