import { useEffect, useState } from "react";
import {
  Stack, ToggleButton, ToggleButtonGroup, TextField, Typography, Chip,
} from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorIcon from "@mui/icons-material/Error";
import LongTextField from "./LongTextField";
import { verifyAugmentation } from "../api/queries";
import type { VerifyAugmentationResp } from "../api/types";

type Kind = "text" | "file";

interface Props {
  value: string;
  kind: Kind;
  onChange: (value: string, kind: Kind) => void;
  experimentName?: string;
  label?: string;
}

export default function AugmentationField({
  value, kind, onChange, experimentName, label = "Augmentation",
}: Props) {
  const [verify, setVerify] = useState<VerifyAugmentationResp | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (kind !== "file" || !value) { setVerify(null); return; }
    verifyAugmentation(value, experimentName)
      .then((r) => { if (!cancelled) setVerify(r); })
      .catch(() => { if (!cancelled) setVerify(null); });
    return () => { cancelled = true; };
  }, [kind, value, experimentName]);

  return (
    <Stack spacing={1}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <Typography variant="subtitle2">{label}</Typography>
        <ToggleButtonGroup
          size="small"
          exclusive
          value={kind}
          onChange={(_e, k: Kind | null) => k && onChange(value, k)}
        >
          <ToggleButton value="text">Inline</ToggleButton>
          <ToggleButton value="file">File</ToggleButton>
        </ToggleButtonGroup>
      </Stack>

      {kind === "text" ? (
        <LongTextField
          label="Inline markdown"
          value={value}
          onChange={(v) => onChange(v, "text")}
          helperText="Stored as slices/<condition>.md on Save."
          rows={6}
        />
      ) : (
        <Stack spacing={0.5}>
          <TextField
            label="File path"
            value={value}
            onChange={(e) => onChange(e.target.value, "file")}
            placeholder="./slices/graph.md or /abs/path.md"
            fullWidth
            size="small"
          />
          {value && verify && (
            verify.found ? (
              <Chip
                icon={<CheckCircleIcon />}
                color="success"
                variant="outlined"
                size="small"
                label={`found · ${verify.size} B · ${(verify.preview.split("\n")[0] ?? "").slice(0, 60)}`}
              />
            ) : (
              <Chip icon={<ErrorIcon />} color="error" variant="outlined" size="small" label="not found" />
            )
          )}
        </Stack>
      )}
    </Stack>
  );
}
