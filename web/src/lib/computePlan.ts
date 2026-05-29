export interface MiniExperiment {
  conditions: { name: string }[];
  reps_per_condition: number;
  timeout_s: number;
}

export interface Plan {
  total_runs: number;
  eta_seconds: number;
  per_condition: { name: string; runs: number }[];
}

export function computePlan(exp: MiniExperiment): Plan {
  const reps = Number(exp.reps_per_condition) || 0;
  const t = Number(exp.timeout_s) || 0;
  const total = exp.conditions.length * reps;
  return {
    total_runs: total,
    eta_seconds: total * t,
    per_condition: exp.conditions.map((c) => ({ name: c.name, runs: reps })),
  };
}
