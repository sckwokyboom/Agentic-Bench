import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Stack, Box, Typography, CircularProgress, Alert } from "@mui/material";
import ExperimentForm from "../components/ExperimentForm";
import { useExperiment, useSaveExperiment } from "../api/queries";
import { loadSchema, type JsonSchema } from "../api/schemaCache";
import { uiSchema } from "../schema/uiSchema";

export default function ExperimentEdit() {
  const { name } = useParams<{ name: string }>();
  const [schema, setSchema] = useState<JsonSchema | null>(null);
  const exp = useExperiment(name);
  const save = useSaveExperiment();

  useEffect(() => { loadSchema().then(setSchema); }, []);

  async function handleSave(data: Record<string, unknown>) {
    if (!name) return;
    await save.mutateAsync({ name, body: data });
  }

  // NOTE: Run button + handleRun wired in Task 4b. Custom widgets referenced by
  // uiSchema (ModelValidationWidget/TargetMethodsWidget/AugmentationWidget) are
  // registered in Tasks 4c-4e; until then the live /api/schema form may warn on
  // unregistered widgets at runtime (covered by Task 4f smoke), not in unit tests.

  if (!schema || !exp.data) return <CircularProgress />;
  if (exp.error) return <Alert severity="error">Failed to load experiment.</Alert>;

  return (
    <Stack direction="row" spacing={2} sx={{ height: "100%" }}>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography variant="h5" gutterBottom>Edit {name}</Typography>
        <ExperimentForm
          schema={schema as never}
          uiSchema={uiSchema}
          formData={exp.data}
          onSave={handleSave}
        />
      </Box>
      <Box sx={{ width: 320, position: "sticky", top: 0, alignSelf: "flex-start" }}>
        {/* Right panel cards added in Task 4b. */}
      </Box>
    </Stack>
  );
}
