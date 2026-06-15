import { useState } from "react";
import {
  Card, CardContent, Typography, Button, Alert, CircularProgress, Stack,
} from "@mui/material";
import NetworkCheckIcon from "@mui/icons-material/NetworkCheck";
import { useValidateReachability } from "../api/queries";
import type { ValidateReachabilityResp } from "../api/types";

interface Props {
  name: string;
  onResult?: (r: ValidateReachabilityResp | null) => void;
}

// A REAL reachability probe — distinct from ModelValidationChip's advisory
// "available" (catalog membership). This calls the configured endpoint with the
// key inside the run's sandbox, so it catches a wrong key, a blocked egress
// (corporate gateway), a TLS-intercept, or a model the endpoint does not serve.
export default function ReachabilityPanel({ name, onResult }: Props) {
  const mut = useValidateReachability();
  const [result, setResult] = useState<ValidateReachabilityResp | null>(null);

  async function test() {
    try {
      const r = await mut.mutateAsync(name);
      setResult(r);
      onResult?.(r);
    } catch (e) {
      const r: ValidateReachabilityResp = {
        reachable: false,
        reason: "request_failed",
        detail: (e as Error)?.message ?? "request failed",
      };
      setResult(r);
      onResult?.(r);
    }
  }

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>Model reachability</Typography>
        <Button
          size="small"
          variant="outlined"
          startIcon={mut.isPending ? <CircularProgress size={14} /> : <NetworkCheckIcon />}
          disabled={mut.isPending}
          onClick={test}
        >
          {mut.isPending ? "Testing…" : "Test reachability"}
        </Button>
        {result && (
          <Stack sx={{ mt: 1 }}>
            {result.reachable ? (
              <Alert severity="success" variant="outlined">Reachable.</Alert>
            ) : (
              <Alert severity="error" variant="outlined">
                Unreachable — <strong>{result.reason}</strong>
                {result.detail ? `: ${result.detail}` : ""}
              </Alert>
            )}
          </Stack>
        )}
        <Typography variant="caption" color="text.secondary"
                    sx={{ display: "block", mt: 1 }}>
          Real 1-token probe of the configured endpoint, run inside the run's
          sandbox (tests the SAVED experiment; takes a few seconds).
        </Typography>
      </CardContent>
    </Card>
  );
}
