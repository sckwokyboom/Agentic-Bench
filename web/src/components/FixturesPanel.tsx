import { Card, CardContent, Typography, Stack } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";

interface Props {
  fixturePath?: string;
  referencePath?: string;
  hasFixture: boolean;
  hasReference: boolean;
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

export default function FixturesPanel({ fixturePath, referencePath, hasFixture, hasReference }: Props) {
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>Fixtures</Typography>
        <Stack spacing={0.5}>
          <Row ok={hasFixture}   label="fixture"   path={fixturePath} />
          <Row ok={hasReference} label="reference" path={referencePath} />
        </Stack>
      </CardContent>
    </Card>
  );
}
