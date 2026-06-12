# Reproduce: picocli-putValue A/B experiment

Checklist for running the full experiment on a clean machine.
Target audience: a colleague with Python 3.11+, git, and internet access.

---

## 1. Clone both repos

```bash
# macOS / Linux  (the Graph-Tipper repo is named Graph-Augmentator on GitHub)
git clone https://github.com/sckwokyboom/Agentic-Bench.git
git clone https://github.com/sckwokyboom/Graph-Augmentator.git Graph-Tipper
```

```powershell
# Windows — disable CRLF mangling so the fixture diff stays clean
git clone -c core.autocrlf=false https://github.com/sckwokyboom/Agentic-Bench.git
git clone -c core.autocrlf=false https://github.com/sckwokyboom/Graph-Augmentator.git Graph-Tipper
```

---

## 2. Python venv + install

```bash
# macOS / Linux
cd Agentic-Bench
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

```powershell
# Windows
cd Agentic-Bench
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

---

## 3. Install opencode (need 1.15.x)

```bash
npm i -g opencode-ai
opencode --version   # confirm 1.15.x
```

---

## 4. One-time machine check + build sandbox image

```bash
python scripts/setup_check.py --container --build-image
```

This verifies opencode, JDK 17–21, docker/podman, and builds the sandbox image.
Errors print what is missing and how to get it.

---

## 5. Set GRAPH_TIPPER_HOME

Point to the Graph-Tipper clone from step 1.

```bash
# macOS / Linux — add to shell rc or export per-session
export GRAPH_TIPPER_HOME=/absolute/path/to/Graph-Tipper
```

```powershell
# Windows PowerShell
$env:GRAPH_TIPPER_HOME = "C:\absolute\path\to\Graph-Tipper"
# Also needed so {env:HOME}/.gradle cache-mount resolves:
$env:HOME = $env:USERPROFILE          # PowerShell
# (cmd.exe equivalent: set HOME=%USERPROFILE%)
```

The `cache_mounts` in `experiment.yaml` reference `{env:GRAPH_TIPPER_HOME}` and
`{env:HOME}` — both must be set before running the experiment.

---

## 6. Prepare artifacts

```bash
cd experiments/picocli-putValue
python prepare.py
```

Stages (idempotent; re-run with `--force` to regenerate):
- `deps` — dependency check; prints what is missing
- `fixtures` — clones picocli @ `fixture.lock` sha, strips `putValue` body
- `artifacts` — calls GT producer; places slices + tool data under `overlays/`
- `overlay` — copies `impact.ts` from `$GRAPH_TIPPER_HOME/integrations/opencode/tools/`
- `smoke` — validates config, pings model, checks sandbox image

Run a single stage: `python prepare.py --only artifacts`

---

## 7. Choose a model

Open [`experiment.yaml`](experiment.yaml) and set `model:`.
The current default is a free model (no API credits needed):

```yaml
model: opencode/deepseek-v4-flash-free
```

Alternatives are commented in the file. If you switch to a paid model,
confirm your API key is set and smoke passes (`python prepare.py --only smoke`).

---

## 8. Run the experiment

From the repo root (venv active, `GRAPH_TIPPER_HOME` set):

```bash
abench run experiments/picocli-putValue/experiment.yaml
```

Runs 4 conditions × 3 repetitions in a container sandbox.
Expected wall time: 20–60 min depending on model and machine.

---

## 9. Share results

Send the full batch directory:

```
runs/picocli-putValue/<batch-id>/
```

Include all files (condition subdirs, `run_manifest.json`, logs).

---

## Known machine-specific findings

- **Custom/self-signed root CA in your network: docker build and sandbox runs
  fail with `unable to get local issuer certificate`.** If your environment uses
  a private or internal root CA, drop the relevant `*.crt` files into
  `docker/extra-ca/` under neutral names (`ca-1.crt`, ...; the dir's README has
  a one-liner) and rebuild: `python scripts/setup_check.py --container
  --build-image`. The certs are gitignored and registered into the image's
  system store (curl/git), JVM keystore (gradle/maven), and Node bundle
  (opencode). A good build prints `[extra-ca] registered N extra cert(s)`.

- **macOS + python.org Python: TLS errors on downloads.** python.org builds ship
  without root certificates, so the joern bootstrap (`tools/get_joern.py`) fails
  with `CERTIFICATE_VERIFY_FAILED`. Fix once per machine: run
  `Install Certificates.command` from the Python app folder, or per-session:

  ```bash
  export SSL_CERT_FILE=$(python3 -c 'import certifi; print(certifi.where())')
  ``` (2026-06-10, macOS)

### JDK version

`/usr/bin/java` (PATH default) may point to a newer JDK than the pipeline needs.
Use **JDK 21** — it is the only version that satisfies the whole chain with a
single `JAVA_HOME`: the Graph-Tipper CLI is built with a Gradle toolchain
pinned to 21 (`build.gradle.kts`), while picocli's Gradle 8.14 runs on JDKs up
to 24 (so the PATH-default 25 is too new, and 17 cannot run the GT CLI).
`prepare.py` picks up `JAVA_HOME`; `produce_artifacts` also accepts
`--java-home`.

```bash
# macOS — set JAVA_HOME to a JDK 21
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
# Tip: if Graph-Tipper was ever built on this machine, Gradle has likely
# auto-provisioned a Temurin 21 under ~/.gradle/jdks/ — usable directly.
```

On Windows set `JAVA_HOME` to a JDK 21 installation directory before running
`prepare.py`.

### Docker not installed

`sandbox.mode: container` in `experiment.yaml` requires Docker or Podman.
Neither is installed on this machine yet. Install **Docker Desktop**
(macOS or Windows + WSL2 backend) or **podman**, then re-run:

```bash
python scripts/setup_check.py --container --build-image
```

### Joern is pinned, not from Homebrew

The pipeline pins Joern v4.0.530 via `python3 tools/get_joern.py` inside
Graph-Tipper. This downloads ~1.7 GB to `~/.graph-tipper` on first run.
Do **not** rely on a Homebrew-installed `joern` — the pipeline does not use it.

---

## Windows hazards

- **Joern native vs WSL:** `joern.bat` ships in the Joern distribution and is the
  primary path. If the native Windows distribution does not start up correctly,
  the documented fallback is to run the `joern`, `export`, and `slice` stages of
  `produce_artifacts` inside WSL; the output files are plain text and the rest of
  the pipeline runs natively.
- **CRLF:** Always clone with `core.autocrlf=false` (step 1). CRLF line endings
  in the fixture will contaminate the reference diff.
- **Docker Desktop / WSL2:** Container mode requires Docker Desktop with the WSL2
  backend enabled. Windows-path mounts are supported; Docker Desktop handles the
  translation.
- **`python3` alias:** On Windows the launcher is typically `python`, not
  `python3`. If `impact.ts` shells out to `python3` for `from_git.py`, ensure
  `python3` is aliased or on PATH (e.g. via the Python installer's option or a
  `doskey` alias). This only affects host-mode impact; container mode has
  `python3` baked in.
- **Gradle wrapper:** `gradlew.bat` is used on Windows; the pipeline calls it via
  `shutil.which`, which resolves `.bat`/`.cmd` shims automatically — no manual
  path change needed.
