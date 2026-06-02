import { useEffect, useId, useState } from "react";
import type { FieldProps } from "@rjsf/utils";
import {
  Box, FormControl, FormControlLabel, InputLabel, MenuItem,
  Select, Stack, Switch, TextField, Typography,
} from "@mui/material";

// The verify object shape, mirroring abench.config.VerifyCfg.
interface VerifyData {
  command: string | null;
  enabled: boolean;
  timeout_s: number;
}

type BuildSystem = "auto" | "gradle" | "maven" | "pytest" | "custom";

// Canonical command for each non-auto/non-custom build system.
const CANONICAL: Record<"gradle" | "maven" | "pytest", string> = {
  gradle: "gradle test",
  maven: "mvn test",
  pytest: "pytest",
};

// Reverse lookup: canonical command string -> build system.
const FROM_CANONICAL: Record<string, "gradle" | "maven" | "pytest"> = {
  "gradle test": "gradle",
  "mvn test": "maven",
  pytest: "pytest",
};

// Derive the selected build system from the current command value.
function systemFor(command: string | null | undefined): BuildSystem {
  if (command == null || command === "") return "auto";
  const known = FROM_CANONICAL[command];
  return known ?? "custom";
}

function normalise(formData: Partial<VerifyData> | undefined): VerifyData {
  return {
    command: formData?.command ?? null,
    enabled: formData?.enabled ?? true,
    timeout_s: typeof formData?.timeout_s === "number" ? formData.timeout_s : 300,
  };
}

/**
 * Custom rjsf field for the `verify` object. Replaces the raw
 * command/enabled/timeout_s rendering with a build-system dropdown that maps to
 * a canonical command, plus a freeform "custom" command, an enabled switch and a
 * timeout input. Always emits the full verify object via `onChange`.
 */
export default function VerifyField(props: FieldProps) {
  const data = normalise(props.formData as Partial<VerifyData> | undefined);
  const derivedSystem = systemFor(data.command);

  // Track an explicit "custom" selection so it sticks even while the command is
  // empty (an empty command would otherwise read back as "auto"). When the data
  // disagrees with the explicit choice (e.g. user pivots to a canonical command),
  // the derived system wins.
  const [explicitCustom, setExplicitCustom] = useState(derivedSystem === "custom");
  useEffect(() => {
    if (derivedSystem !== "auto" && derivedSystem !== "custom") setExplicitCustom(false);
  }, [derivedSystem]);

  const system: BuildSystem =
    explicitCustom && derivedSystem !== "gradle" && derivedSystem !== "maven"
      && derivedSystem !== "pytest"
      ? "custom"
      : derivedSystem;
  const showCommand = system === "custom";

  const labelId = useId();

  const detected = (props.formContext as
    | { detectedVerify?: { system?: string | null } }
    | undefined)?.detectedVerify?.system;

  function emit(next: VerifyData) {
    props.onChange(next);
  }

  function onSystemChange(nextSystem: BuildSystem) {
    if (nextSystem === "auto") {
      setExplicitCustom(false);
      emit({ ...data, command: null });
      return;
    }
    if (nextSystem === "custom") {
      setExplicitCustom(true);
      // Keep an existing custom command; otherwise start empty for the user.
      const keep = system === "custom" ? (data.command ?? "") : "";
      emit({ ...data, command: keep });
      return;
    }
    setExplicitCustom(false);
    emit({ ...data, command: CANONICAL[nextSystem] });
  }

  const autoLabel = detected ? `auto (auto-detected: ${detected})` : "auto";

  return (
    <Box sx={{ mt: 1, mb: 1 }}>
      <Typography variant="subtitle1" sx={{ mb: 1 }}>Verify</Typography>
      <Stack spacing={2}>
        <FormControl fullWidth size="small">
          <InputLabel id={labelId}>Build system</InputLabel>
          <Select
            labelId={labelId}
            label="Build system"
            value={system}
            onChange={(e) => onSystemChange(e.target.value as BuildSystem)}
          >
            <MenuItem value="auto">{autoLabel}</MenuItem>
            <MenuItem value="gradle">gradle</MenuItem>
            <MenuItem value="maven">maven</MenuItem>
            <MenuItem value="pytest">pytest</MenuItem>
            <MenuItem value="custom">custom</MenuItem>
          </Select>
        </FormControl>

        {showCommand && (
          <TextField
            label="Command"
            size="small"
            fullWidth
            value={data.command ?? ""}
            onChange={(e) => emit({ ...data, command: e.target.value })}
            placeholder="e.g. ./gradlew check"
          />
        )}

        <FormControlLabel
          control={
            <Switch
              checked={data.enabled}
              onChange={(e) => emit({ ...data, enabled: e.target.checked })}
            />
          }
          label="Enabled"
        />

        <TextField
          label="Verify timeout (s)"
          type="number"
          size="small"
          value={Number.isFinite(data.timeout_s) ? data.timeout_s : ""}
          onChange={(e) => {
            const n = e.target.value === "" ? 0 : Number(e.target.value);
            emit({ ...data, timeout_s: Number.isNaN(n) ? 0 : n });
          }}
          sx={{ maxWidth: 220 }}
        />
      </Stack>
    </Box>
  );
}
