import { Card, CardContent, Typography, Stack, Box } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";

const inlineIcon = { fontSize: "inherit", verticalAlign: "middle", mr: 0.5 } as const;

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

function Row({ ok, label, path, caption }: { ok: boolean; label: string; path?: string; caption: string }) {
  return (
    <Box>
      <Stack direction="row" spacing={1} alignItems="center">
        {ok
          ? <CheckCircleIcon color="success" fontSize="small" />
          : <CancelIcon color="error" fontSize="small" />}
        <Typography variant="body2">
          <b>{label}:</b> <code>{path ?? "(unset)"}</code>
        </Typography>
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", pl: 4 }}>
        {caption}
      </Typography>
    </Box>
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
          <Row
            ok={hasFixture}
            label="fixture"
            path={fixturePath}
            caption="The working tree the agent edits — your stripped project (target code removed)."
          />
          <Row
            ok={hasReference}
            label="reference"
            path={referencePath}
            caption="The ground-truth original, used only for comparison — never shown to the agent."
          />
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
            <Typography variant="body2">
              <b>build:</b>{" "}
              {verifyCommand
                ? <>{verifySystem ?? "custom"} · <code>{verifyCommand}</code></>
                : <i>no build system detected — set <code>verify.command</code></i>}
            </Typography>
            {verifyAmbiguous && (
              <Typography variant="caption" color="warning.main">
                <WarningAmberIcon color="warning" sx={inlineIcon} />
                ambiguous ({(verifyCandidates ?? []).join(" + ")}) — using {verifySystem};
                set verify.command if wrong
              </Typography>
            )}
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}
