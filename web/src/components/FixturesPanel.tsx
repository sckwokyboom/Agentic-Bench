import { Card, CardContent, Typography, Stack } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";

interface Props {
  fixturePath?: string;
  referencePath?: string;
  hasFixture: boolean;
  hasReference: boolean;
  verifyCommand?: string | null;
  verifySystem?: string | null;
  verifyAmbiguous?: boolean;
  verifyCandidates?: string[];
}

function Row({ ok, label, path }: { ok: boolean; label: string; path?: string }) {
  return (
    <Stack direction="row" spacing={1} alignItems="center">
      {ok
        ? <CheckCircleIcon color="success" fontSize="small" />
        : <CancelIcon color="error" fontSize="small" />}
      <Typography variant="body2">
        <b>{label}:</b> <code>{path ?? "(unset)"}</code>
      </Typography>
    </Stack>
  );
}

export default function FixturesPanel({
  fixturePath, referencePath, hasFixture, hasReference, verifyCommand, verifySystem,
  verifyAmbiguous, verifyCandidates,
}: Props) {
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>Fixtures</Typography>
        <Stack spacing={0.5}>
          <Row ok={hasFixture}   label="fixture"   path={fixturePath} />
          <Row ok={hasReference} label="reference" path={referencePath} />
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
            <Typography variant="body2">
              <b>build:</b>{" "}
              {verifyCommand
                ? <>{verifySystem ?? "custom"} · <code>{verifyCommand}</code></>
                : <i>no build system detected — set <code>verify.command</code></i>}
            </Typography>
            {verifyAmbiguous && (
              <Typography variant="caption" color="warning.main">
                ⚠ ambiguous ({(verifyCandidates ?? []).join(" + ")}) — using {verifySystem};
                set verify.command if wrong
              </Typography>
            )}
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}
