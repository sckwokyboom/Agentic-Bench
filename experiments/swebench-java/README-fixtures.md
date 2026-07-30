# SWE-bench-java A/B (fixture mode) — baseline vs rcc

One entry point, five subcommands. Nothing here needs Docker or the official
multi-swe-bench harness.

```bash
./scripts/swe.sh fetch          # download + schema-validate the dataset
./scripts/swe.sh build          # clone@base.sha + patches -> fixtures + run script
./scripts/swe.sh doctor         # prove the toolchain builds it and the bug reproduces
./scripts/swe.sh run            # the batch (resumable — Ctrl-C is safe)
./scripts/swe.sh status         # progress, from ANOTHER terminal while it runs
./scripts/swe.sh report         # digest -> swe-ab.md
```

`./scripts/swe.sh all` chains them. Defaults: repo `jackson-core`, 4 instances,
2 reps → 16 agent sessions. Override with env vars:

```bash
SWE_REPO=gson SWE_LIMIT=8 SWE_REPS=3 ./scripts/swe.sh build
```

| var | default | meaning |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | **required to run** |
| `MSB_DATA` | `~/msb-data` | where datasets land |
| `SWE_ROOT` | `./swe-runs` | fixtures + runs (git-ignored) |
| `SWE_REPO` | `jackson-core` | dataset short name (`swe_fetch.py --list`) |
| `SWE_LIMIT` / `SWE_REPS` | `4` / `2` | instances / repetitions per arm |

## What a fixture is

| tree | contents |
|---|---|
| `checkout/` | repo @ `base.sha` **+ `test_patch`** → the new tests FAIL |
| `reference/` | the same **+ `fix_patch`** → they pass |

The agent sees only `checkout/` and the issue text. `fix_patch` builds the reference
and points at the method under repair — the same value for both arms, so it cannot
bias the comparison — and is never shown to the agent.

## ⚠ What these numbers are, and are not

The verdict is **our own test run**, not the official multi-swe-bench `resolved`.
They are comparable to our Defects4J A/B and to each other; they must **not** be
quoted against published SWE-bench scores. The official path needs orchestration
wired into benchmark mode plus the container evaluator — see [RUNBOOK.md](./RUNBOOK.md).

Benchmark mode currently runs the plain agent only, and config validation **refuses**
an orchestrated condition there rather than running baseline under an `rcc` label.
That is why the A/B lives in fixture mode.

## Do this before the batch

`doctor` exists because two failures are very expensive when found late: a toolchain
that cannot build the repo (every run fails and reads as the agent's fault), and a
fixture whose tests already pass (nothing to fix — the run grades nothing).

```bash
./scripts/swe.sh doctor          # env + first fixture deeply + the rest compile-only
```

Start small — `SWE_LIMIT=2 SWE_REPS=1` — confirm the digest looks sane, then scale.

## Monitoring a running batch

`run` prints how many fixtures it is about to run and tees to `$SWE_ROOT/swe.log`.
From another terminal:

```bash
./scripts/swe.sh status          # done / running / pending per fixture + overall %
watch -n 30 ./scripts/swe.sh status
tail -f swe-runs/swe.log         # raw output
```

`status` reads the run tree, so it is safe at any time and also works after the batch
died — it shows what completed and what to resume. A session with no file activity
for a long time is flagged; that usually means a wedged provider connection.

If `run` says **no fixtures**, `build` produced none: re-run it and read its per-instance
lines — each skip states its reason (no `.java` in the fix, unresolvable target method,
clone/patch failure).

## Reading the digest

`swe-ab.md` reports per-instance cost per arm, the rcc/baseline ratio, and a headline
median. Two gates decide whether any claim may be made:

- **rcc health** — how many rcc runs actually entered the causal loop. A run that
  degraded is not evidence that rcc didn't help; the treatment never ran. (With
  `orchestration.rcc_strict` on by default, a missing mutation graph now fails the
  rep loudly instead of silently running phased.)
- cost ratios are pooled **only** over instances both arms solved; solve-rate is
  reported separately.

Re-grade environment-independently when a verdict matters:
`python3 scripts/d4j_replay.py --ab` (works on any run tree with arms/reps).
