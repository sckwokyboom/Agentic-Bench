# Defects4J baseline sieve (RCC candidate selection)

Infrastructure to run **real Java bugs from Defects4J** through Agentic-bench and
find the ones a plain `opencode + deepseek` agent (no augmentation) FAILS on — the
cases where RCC's causal loop has room to help. This is the *sieve* step: run the
baseline, keep the failures, then run `phased` vs `rcc` on those.

## Files
- `gems.csv` — the frozen shortlist (46 bugs) with metadata: `tier`, project, bug,
  `triggers` (cascade width), `hunks`, `nonlocal`, buggy/fixed revs, modified class,
  method hint, first trigger test. Two tiers:
  - `nonlocal_gem` (19) — single-class fix whose failing tests are in OTHER
    classes/packages (symptom ≠ cause) → **RCC's exact niche**.
  - `bigproj_cascade` (27) — single-class fix with a wide cascade (≥5 failing tests)
    in large projects (Closure/Lang/Math/…) → hard for a mid-tier agent.
- `../../scripts/defects4j_select.py` — recompute the shortlist from a Defects4J
  checkout's metadata (no builds). `python3 scripts/defects4j_select.py <df>/framework/projects`.
- `../../scripts/defects4j_baseline.py` — generate per-bug baseline experiments +
  `run_baseline.sh` from `gems.csv`.

## Prerequisites (remote box)
1. **Defects4J** (metadata + checkout tooling):
   ```bash
   git clone https://github.com/rjust/defects4j
   # Perl deps — init.sh does NOT install these; defects4j aborts without them:
   sudo apt install -y cpanminus build-essential
   sudo cpanm String::Interpolate DBI DBD::CSV JSON URI Text::CSV
   (cd defects4j && ./init.sh)                          # downloads project repos + tools
   export PATH="$PWD/defects4j/framework/bin:$PATH"     # `defects4j` on PATH
   defects4j info -p Lang -b 1                          # sanity: must print bug info
   ```
2. **Java 11** — the Defects4J *framework* itself requires Java 11 to run (its perl
   driver aborts with "Java 11 is required!" otherwise). It compiles/tests the
   patched projects under 11 too. Point JAVA_HOME/PATH at a JDK 11:
   ```bash
   sudo apt install -y openjdk-11-jdk               # Debian/Ubuntu/WSL
   export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
   export PATH="$JAVA_HOME/bin:$PATH"
   defects4j info -p Lang -b 1                       # sanity: must NOT say "Java 11 is required"
   ```
3. **Agentic-bench**: `pip install -e '.[langgraph]'`.
4. **opencode 1.15.x** with a DeepSeek key: `export DEEPSEEK_API_KEY=…` (or auth.json).

## Run the baseline sieve
```bash
git pull                                                     # brings gems.csv + scripts
python3 scripts/defects4j_baseline.py experiments/defects4j/gems.csv
#   -> d4j-runs/<P>-<bug>/experiment.yaml  + d4j-runs/run_baseline.sh  (git-ignored)
# (optional) only the non-local gems:
#   python3 scripts/defects4j_baseline.py experiments/defects4j/gems.csv nonlocal_gem
DEEPSEEK_API_KEY=… bash d4j-runs/run_baseline.sh             # checkout + abench run per bug
```
`run_baseline.sh` for each bug does: `defects4j checkout -v Nb` (buggy fixture) +
`-v Nf` (fixed reference) then `abench run`. Grading is `defects4j test`, which
Agentic-bench now understands natively (fails when `failing_tests` is non-empty).

## VALIDATE the verify seam on ONE gem first
Agentic-bench copies the fixture (a Defects4J checkout, incl. `.defects4j.config`)
into a workdir and runs `defects4j test` there. Confirm this grades correctly before
the batch:
```bash
cd d4j-runs/Chart-26 && defects4j checkout -p Chart -v 26b -w checkout
abench run experiment.yaml
# the run's verify status must match a manual `cd checkout && defects4j test`
```
If it diverges, the `defects4j test` grader (abench/verify.py `_grade_defects4j`)
needs adjusting for that project's layout — fix there, not per-bug.

## After the sieve
- Keep the bugs where **baseline FAILED** — those are the demo set (agent can't solve
  them plainly, so RCC has room to help). Memorization note: Defects4J is old; a bug
  the agent PASSES may be memorized — the fail-filter drops those automatically.
- For the RCC arm: each gem's `modified_class` (from `gems.csv`) is the known target →
  per-bug GT mutation-graph precompute (like picocli putValue), then `phased` vs `rcc`.

## Caveats
- The `baseline` condition uses no `restore_non_target_before_verify`, so grading the
  agent's edits is clean. The later `rcc`/`phased` arms on Defects4J need care: those
  checkouts are git repos whose HEAD is the BUGGY commit, so a HEAD-based restore would
  revert the fix — use the reference tree / a tailored restore.
- Batch cost is real: each bug = a full agent session + build. Start with the 19
  `nonlocal_gem`s.
