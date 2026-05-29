import { Card, CardContent, Typography, Stack, Alert } from "@mui/material";
import type { RJSFValidationError } from "@rjsf/utils";

interface Props { errors: RJSFValidationError[]; }

export default function ValidationPanel({ errors }: Props) {
  if (errors.length === 0) {
    return (
      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle2" gutterBottom>Validation</Typography>
          <Alert severity="success" variant="outlined">No errors.</Alert>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>
          Validation ({errors.length})
        </Typography>
        <Stack spacing={0.5}>
          {errors.map((e, i) => (
            <Typography key={i} variant="body2" color="error">
              <code>{e.property ?? e.schemaPath}</code> — {e.message}
            </Typography>
          ))}
        </Stack>
      </CardContent>
    </Card>
  );
}
