import { Card, CardContent, Stack, Typography, Chip, Box } from "@mui/material";
import { useMethodComparison, useExperiment } from "../api/queries";

interface Props {
  name: string;
  condition: string;
  rep: number;
  batch?: string;
}

function SideBySide({ original, regen }: { original: string[]; regen: string[] }) {
  return (
    <Box sx={{
      display: "grid", gridTemplateColumns: "1fr 1fr",
      gap: 1, mt: 1, fontFamily: "monospace", fontSize: 12,
    }}>
      <Box>
        <Typography variant="caption" color="text.secondary">Original (reference)</Typography>
        <Box component="pre" sx={{ m: 0, whiteSpace: "pre-wrap", bgcolor: (t) => t.palette.mode === "dark" ? "grey.900" : "grey.100", p: 1, borderRadius: 1, userSelect: "text" }}>
          {original.join("\n")}
        </Box>
      </Box>
      <Box>
        <Typography variant="caption" color="text.secondary">Agent's regeneration</Typography>
        <Box component="pre" sx={{ m: 0, whiteSpace: "pre-wrap", bgcolor: (t) => t.palette.mode === "dark" ? "grey.900" : "grey.100", p: 1, borderRadius: 1, userSelect: "text" }}>
          {regen.join("\n")}
        </Box>
      </Box>
    </Box>
  );
}

function MethodRow({ name, condition, rep, method, batch }: Props & { method: string }) {
  const cmp = useMethodComparison(name, condition, rep, method, batch);
  if (cmp.isLoading) return null;
  if (cmp.error || !cmp.data) return (
    <Typography variant="caption" color="error">{method}: failed to extract</Typography>
  );
  const diffCount = Math.max(0, cmp.data.original_lines.length - cmp.data.regen_lines.length)
    + Math.max(0, cmp.data.regen_lines.length - cmp.data.original_lines.length);
  return (
    <Box sx={{ mt: 2 }}>
      <Stack direction="row" spacing={1} alignItems="center">
        <Typography variant="subtitle2">{method}</Typography>
        {cmp.data.equivalent
          ? <Chip size="small" color="success" label="semantically equivalent ✓" />
          : <Chip size="small" color="warning" label={`divergent (${diffCount} lines differ)`} />}
      </Stack>
      <SideBySide original={cmp.data.original_lines} regen={cmp.data.regen_lines} />
    </Box>
  );
}

export default function MethodComparisonCard({ name, condition, rep, batch }: Props) {
  const exp = useExperiment(name);
  const targetFile = exp.data?.target_file as string | undefined;
  const targetMethods = exp.data?.target_methods as string[] | undefined;
  if (!targetFile) return null;
  const methods = (targetMethods && targetMethods.length > 0)
    ? targetMethods
    : [targetFile.split("/").pop()!.replace(/\.[^.]+$/, "")];
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="subtitle2">Method comparison · {targetFile}</Typography>
        {methods.map((m) => (
          <MethodRow key={m} name={name} condition={condition} rep={rep} method={m} batch={batch} />
        ))}
      </CardContent>
    </Card>
  );
}
