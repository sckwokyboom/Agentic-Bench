import type { ReactNode } from "react";
import {
  Table, TableHead, TableBody, TableRow, TableCell, Typography, Box, Tooltip,
  Chip, ToggleButton, ToggleButtonGroup, LinearProgress,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import type { Theme } from "@mui/material/styles";
import TrendingUpIcon from "@mui/icons-material/TrendingUp";
import BlockIcon from "@mui/icons-material/Block";
import RemoveIcon from "@mui/icons-material/Remove";
import { selectable } from "../theme";
import type { Aggregate, Panel, PanelCondition, PanelMetric } from "../api/types";

interface Props {
  panel: Panel;
  agg: Aggregate;
  onAggChange: (a: Aggregate) => void;
  /** panel is refetching (agg toggle / exclusion recompute) — show a thin bar. */
  busy?: boolean;
}

// ── Directional tone for cost cells ──────────────────────────────────────────
// "lower" = cheaper-is-better: a ratio CI entirely below 1 is good (green),
// entirely above 1 is bad (red), crossing 1 is inconclusive (no fill). "exec"
// (tests executed): fewer than baseline is the suspicious direction (undercount
// → warn); more is just effort. At n≈5 most CIs cross 1 — that's expected.
type Tone = "good" | "bad" | "warn" | "none";
type CostDir = "lower" | "exec";

function costTone(dir: CostDir, ci: [number | null, number | null] | null): Tone {
  if (!ci || ci[0] == null || ci[1] == null) return "none";
  const [lo, hi] = ci as [number, number];
  if (dir === "exec") return hi < 1 ? "warn" : "none";
  if (hi < 1) return "good";
  if (lo > 1) return "bad";
  return "none";
}

// Point comparison (no CI) for summary rows — pass rate, tokens/pass, tests %.
function pointTone(v: number | null, base: number | null, dir: "lower" | "higher"): Tone {
  if (v == null || base == null || v === base) return "none";
  const lower = v < base;
  if (dir === "lower") return lower ? "good" : "bad";
  return lower ? "bad" : "good";
}

const TONE_TOKEN: Record<Exclude<Tone, "none">, "success" | "error" | "warning"> = {
  good: "success", bad: "error", warn: "warning",
};

function toneCellSx(tone: Tone) {
  if (tone === "none") return {};
  return { bgcolor: (th: Theme) => alpha(th.palette[TONE_TOKEN[tone]].main, 0.1) };
}
function toneColor(tone: Tone): string {
  return tone === "none" ? "text.secondary" : `${TONE_TOKEN[tone]}.main`;
}

// ── Number formatting ─────────────────────────────────────────────────────────
function fmtTokens(v: number): string {
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${Math.round(v / 1e3)}k`;
  return `${Math.round(v)}`;
}
function fmtInt(v: number): string {
  return `${Math.round(v)}`;
}
function fmtPct0(v: number): string {
  return `${Math.round(v * 100)}%`;
}
// Floored to one decimal so a near-miss (2198/2200) never rounds up to 100%.
function fmtPct1(v: number): string {
  return v >= 1 ? "100%" : `${(Math.floor(v * 1000) / 10).toFixed(1)}%`;
}
// toFixed keeps the leading zero (0.92, not .92) the spec requires.
function ratioText(m: PanelMetric | undefined): string {
  if (!m || m.ratio == null) return "";
  const r = `${m.ratio.toFixed(2)}×`;
  if (m.ci && m.ci[0] != null && m.ci[1] != null) {
    return `${r} [${m.ci[0].toFixed(2)}–${m.ci[1].toFixed(2)}]`;
  }
  return r;
}

// ── Cost-block rows (absolute on top, ratio [CI] below) ──────────────────────
const COST_ROWS: { key: string; label: string; unit?: string; dir: CostDir;
  fmt: (v: number) => string; help?: string }[] = [
  { key: "duration_s", label: "duration", unit: "s", dir: "lower", fmt: fmtInt },
  { key: "n_steps", label: "steps", dir: "lower", fmt: fmtInt },
  { key: "n_tool_calls", label: "tool calls", dir: "lower", fmt: fmtInt },
  { key: "tokens_in", label: "tokens read", dir: "lower", fmt: fmtTokens },
  { key: "tokens_out", label: "tokens generated", dir: "lower", fmt: fmtTokens },
  { key: "n_test_runs", label: "test runs", dir: "lower", fmt: fmtInt },
  { key: "n_tests_executed", label: "tests executed", dir: "exec", fmt: fmtInt,
    help: "Total test-case executions summed over the agent's runs. A ratio whose CI sits below baseline (warn) hints at an undercount — tests that never ran." },
];

const sectionSx = {
  bgcolor: "action.hover",
  color: "text.secondary",
  fontWeight: 600,
  fontSize: 11,
  letterSpacing: "0.06em",
  textTransform: "uppercase" as const,
  py: 0.75,
};

/** Two-line cell: absolute value on top, a muted/toned sub-line below. */
function Cell({ abs, sub, subTone }: { abs: ReactNode; sub?: ReactNode; subTone?: Tone }) {
  return (
    <Box sx={{ display: "inline-flex", flexDirection: "column", alignItems: "flex-end", lineHeight: 1.3 }}>
      <Box component="span">{abs}</Box>
      {sub != null && sub !== "" && (
        <Box component="span" sx={{ fontSize: 11, mt: "1px", color: toneColor(subTone ?? "none") }}>
          {sub}
        </Box>
      )}
    </Box>
  );
}

function VerdictPill({ verdict }: { verdict: PanelCondition["verdict"] }) {
  if (verdict === "baseline") {
    return <Chip size="small" variant="outlined" label="reference" sx={{ height: 22 }} />;
  }
  if (verdict === "promising") {
    return <Chip size="small" color="success" variant="outlined" icon={<TrendingUpIcon />} label="promising" sx={{ height: 22 }} />;
  }
  if (verdict === "dominated") {
    return <Chip size="small" color="error" variant="outlined" icon={<BlockIcon />} label="dominated" sx={{ height: 22 }} />;
  }
  return <Chip size="small" variant="outlined" icon={<RemoveIcon />} label="inconclusive" sx={{ height: 22 }} />;
}

export default function SummaryTable({ panel, agg, onAggChange, busy }: Props) {
  const baseName = panel.baseline;
  // Baseline is the reference column, first; the rest keep build_panel's order.
  const base = panel.conditions.find((c) => c.name === baseName);
  const others = panel.conditions.filter((c) => c.name !== baseName);
  const ordered = base ? [base, ...others] : panel.conditions;

  if (ordered.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No aggregate yet — runs may be in progress, all interrupted, or all excluded.
      </Typography>
    );
  }

  const baseRate = base?.pass.rate ?? null;
  const baseTpr = base?.tests_pass_rate ?? null;
  const baseTpp = base?.cost_per_pass.tokens ?? null;
  const span = 1 + ordered.length;
  const isBase = (c: PanelCondition) => c.name === baseName;

  const costRows = COST_ROWS.filter((r) => panel.metric_order.includes(r.key));
  const anyTpr = ordered.some((c) => c.tests_pass_rate != null);
  const anyBehavior = ordered.some((c) =>
    c.behavior && (c.behavior.read_share != null || c.behavior.bash_share != null
      || c.behavior.edit_share != null || c.behavior.files_edited != null));

  const headCell = (c: PanelCondition) => (
    <TableCell key={c.name} align="right" sx={{ verticalAlign: "bottom", color: isBase(c) ? "text.secondary" : "text.primary" }}>
      <Box>{c.name}{isBase(c) ? " (baseline)" : ""}</Box>
      <Box component="span" sx={{ fontSize: 11, color: "text.disabled", fontWeight: 400 }}>n = {c.n_valid}</Box>
    </TableCell>
  );

  const behaviorRow = (label: string, get: (c: PanelCondition) => number | null,
    fmt: (v: number) => string) => (
    <TableRow hover>
      <TableCell>{label}</TableCell>
      {ordered.map((c) => {
        const v = get(c);
        return (
          <TableCell key={c.name} align="right" sx={selectable}>
            <Cell abs={v == null ? "—" : fmt(v)} />
          </TableCell>
        );
      })}
    </TableRow>
  );

  return (
    <>
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 1, mb: 1 }}>
        <Typography variant="body2" color="text.secondary">
          Each cell: absolute value on top, ratio vs baseline below. No p-values — at n≈{base?.n_valid ?? 5} the honest read is effect size + interval + the raw points below.
        </Typography>
        <ToggleButtonGroup
          size="small" exclusive value={agg}
          onChange={(_e, v) => { if (v) onAggChange(v as Aggregate); }}
          aria-label="aggregate"
        >
          <ToggleButton value="median" aria-label="median">median</ToggleButton>
          <ToggleButton value="mean" aria-label="mean">mean</ToggleButton>
        </ToggleButtonGroup>
      </Box>

      <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1, overflow: "auto" }}>
        {busy && <LinearProgress sx={{ height: 2 }} />}
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>metric</TableCell>
              {ordered.map(headCell)}
            </TableRow>
          </TableHead>
          <TableBody>
            {/* ── summary ──────────────────────────────────────────────────── */}
            <TableRow><TableCell colSpan={span} sx={sectionSx}>summary</TableCell></TableRow>
            <TableRow hover>
              <TableCell>verdict</TableCell>
              {ordered.map((c) => (
                <TableCell key={c.name} align="right"><VerdictPill verdict={c.verdict} /></TableCell>
              ))}
            </TableRow>
            <TableRow hover>
              <TableCell>pass rate</TableCell>
              {ordered.map((c) => {
                const tone = isBase(c) ? "none" : pointTone(c.pass.rate, baseRate, "higher");
                return (
                  <TableCell key={c.name} align="right" sx={{ ...toneCellSx(tone), ...selectable }}>
                    <Cell abs={`${c.pass.k} / ${c.pass.n}`} />
                  </TableCell>
                );
              })}
            </TableRow>
            <TableRow hover>
              <TableCell>
                <Tooltip title="Total tokens over all runs ÷ runs that passed — bundles cost and reliability into one number.">
                  <span>tokens / pass</span>
                </Tooltip>
              </TableCell>
              {ordered.map((c) => {
                const tpp = c.cost_per_pass.tokens;
                const ratio = (!isBase(c) && tpp != null && baseTpp) ? tpp / baseTpp : null;
                const tone = isBase(c) ? "none" : pointTone(tpp, baseTpp, "lower");
                return (
                  <TableCell key={c.name} align="right" sx={{ ...toneCellSx(tone), ...selectable }}>
                    <Cell
                      abs={tpp == null ? "—" : fmtTokens(tpp)}
                      sub={isBase(c) ? "baseline" : ratio == null ? "" : `${ratio.toFixed(2)}×`}
                      subTone={isBase(c) ? undefined : tone}
                    />
                  </TableCell>
                );
              })}
            </TableRow>

            {/* ── outcome ──────────────────────────────────────────────────── */}
            {anyTpr && (
              <>
                <TableRow><TableCell colSpan={span} sx={sectionSx}>outcome</TableCell></TableRow>
                <TableRow hover>
                  <TableCell>
                    <Tooltip title="Share of tests passing at the end across the condition's runs (Σpassed / Σ(passed+failed)). Floored, so a near-miss reads just under 100%.">
                      <span>tests passed <Box component="span" sx={{ color: "text.disabled", fontSize: 11 }}>% of suite</Box></span>
                    </Tooltip>
                  </TableCell>
                  {ordered.map((c) => {
                    const tone = isBase(c) ? "none" : pointTone(c.tests_pass_rate, baseTpr, "higher");
                    return (
                      <TableCell key={c.name} align="right" sx={{ ...toneCellSx(tone), ...selectable }}>
                        <Cell abs={c.tests_pass_rate == null ? "—" : fmtPct1(c.tests_pass_rate)} />
                      </TableCell>
                    );
                  })}
                </TableRow>
              </>
            )}

            {/* ── cost · ratio vs baseline [95% CI] ────────────────────────── */}
            {costRows.length > 0 && (
              <TableRow><TableCell colSpan={span} sx={sectionSx}>cost · ratio vs baseline [95% CI]</TableCell></TableRow>
            )}
            {costRows.map((r) => (
              <TableRow hover key={r.key}>
                <TableCell>
                  {r.help
                    ? <Tooltip title={r.help}><span>{r.label}{r.unit && <Box component="span" sx={{ color: "text.disabled", fontSize: 11, ml: 0.5 }}>{r.unit}</Box>}</span></Tooltip>
                    : <span>{r.label}{r.unit && <Box component="span" sx={{ color: "text.disabled", fontSize: 11, ml: 0.5 }}>{r.unit}</Box>}</span>}
                </TableCell>
                {ordered.map((c) => {
                  const m = c.metrics[r.key];
                  const tone = isBase(c) ? "none" : costTone(r.dir, m?.ci ?? null);
                  return (
                    <TableCell key={c.name} align="right" sx={{ ...toneCellSx(tone), ...selectable }}>
                      <Cell
                        abs={m?.value == null ? "—" : r.fmt(m.value)}
                        sub={isBase(c) ? "baseline" : ratioText(m)}
                        subTone={isBase(c) ? undefined : tone}
                      />
                    </TableCell>
                  );
                })}
              </TableRow>
            ))}

            {/* ── behavior · share of tool calls ───────────────────────────── */}
            {anyBehavior && (
              <>
                <TableRow><TableCell colSpan={span} sx={sectionSx}>behavior · share of tool calls</TableCell></TableRow>
                {behaviorRow("read", (c) => c.behavior?.read_share ?? null, fmtPct0)}
                {behaviorRow("search", (c) => c.behavior?.search_share ?? null, fmtPct0)}
                {behaviorRow("edit", (c) => c.behavior?.edit_share ?? null, fmtPct0)}
                {behaviorRow("bash", (c) => c.behavior?.bash_share ?? null, fmtPct0)}
                {behaviorRow("edits", (c) => c.behavior?.files_edited ?? null, fmtInt)}
              </>
            )}
          </TableBody>
        </Table>
      </Box>

      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 2, mt: 1, alignItems: "center", fontSize: 12, color: "text.secondary" }}>
        <span>cost cell color — interval vs 1:</span>
        <LegendSwatch token="success" label="cheaper" />
        <LegendSwatch token="error" label="costlier" />
        <Box sx={{ display: "inline-flex", alignItems: "center", gap: 0.75 }}>
          <Box sx={{ width: 13, height: 13, borderRadius: "4px", border: 1, borderColor: "divider" }} />
          crosses 1 — inconclusive
        </Box>
      </Box>

      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
        {panel.valid_runs}/{panel.total_runs} runs valid
        {(panel.interrupted_runs ?? 0) > 0 && ` · ${panel.interrupted_runs} interrupted (incl. looping)`}
        {(() => {
          const crashed = panel.total_runs - panel.valid_runs - (panel.interrupted_runs ?? 0);
          return crashed > 0 ? ` · ${crashed} crashed` : "";
        })()}
        {" — interrupted and crash runs are excluded from every aggregate above."}
      </Typography>

      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
        Untick a run in the Runs table below to drop it from these aggregates (recomputes immediately).
      </Typography>
    </>
  );
}

function LegendSwatch({ token, label }: { token: "success" | "error"; label: string }) {
  return (
    <Box sx={{ display: "inline-flex", alignItems: "center", gap: 0.75 }}>
      <Box sx={{ width: 13, height: 13, borderRadius: "4px", bgcolor: (th: Theme) => alpha(th.palette[token].main, 0.18), border: 1, borderColor: (th: Theme) => alpha(th.palette[token].main, 0.4) }} />
      {label}
    </Box>
  );
}
