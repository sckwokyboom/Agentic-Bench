import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Stack, Box, Typography, CircularProgress, Alert, Button,
} from "@mui/material";
import type { RJSFValidationError } from "@rjsf/utils";
import ExperimentForm from "../components/ExperimentForm";
import ValidationPanel from "../components/ValidationPanel";
import PlanPanel from "../components/PlanPanel";
import FixturesPanel from "../components/FixturesPanel";
import PreviousRunsPanel from "../components/PreviousRunsPanel";
import {
  useExperiment, useExperiments, useSaveExperiment, useStartRun, useDetectedVerify,
} from "../api/queries";
import { loadSchema, type JsonSchema } from "../api/schemaCache";
import { uiSchema } from "../schema/uiSchema";
import {
  ModelValidationWidget, TargetMethodsWidget, AugmentationWidget,
} from "../schema/widgets";

const customWidgets = { ModelValidationWidget, TargetMethodsWidget, AugmentationWidget };

export default function ExperimentEdit() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const [schema, setSchema] = useState<JsonSchema | null>(null);
  const exp = useExperiment(name);
  const detected = useDetectedVerify(name);
  const list = useExperiments();
  const save = useSaveExperiment();
  const start = useStartRun();
  const [formData, setFormData] = useState<Record<string, unknown> | null>(null);
  const [errors, setErrors] = useState<RJSFValidationError[]>([]);

  useEffect(() => { loadSchema().then(setSchema); }, []);
  useEffect(() => { if (exp.data && formData === null) setFormData(exp.data); }, [exp.data, formData]);

  const summary = list.data?.find((e) => e.name === name);

  async function handleSave(data: Record<string, unknown>) {
    if (!name) return;
    await save.mutateAsync({ name, body: data });
  }

  async function handleRun() {
    if (!name) return;
    const { session_id } = await start.mutateAsync(name);
    navigate(`/runs/sessions/${session_id}`, { state: { experimentName: name } });
  }

  // Error guard MUST come first: on a fetch error TanStack Query leaves
  // exp.data undefined, so a data-first guard would render a perpetual spinner.
  if (exp.error) return <Alert severity="error">Failed to load experiment.</Alert>;
  if (!schema || !formData) return <CircularProgress />;

  return (
    <Stack direction="row" spacing={2} sx={{ height: "100%" }}>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Stack direction="row" alignItems="center" sx={{ mb: 2 }}>
          <Typography variant="h5" sx={{ flexGrow: 1 }}>Edit {name}</Typography>
          <Button
            variant="contained"
            color="success"
            disabled={errors.length > 0 || !summary?.has_fixture || start.isPending}
            onClick={handleRun}
            startIcon={<span>▶</span>}
          >
            Run
          </Button>
        </Stack>
        <ExperimentForm
          schema={schema as never}
          uiSchema={uiSchema}
          formData={formData}
          widgets={customWidgets}
          onErrorsChange={setErrors}
          onFormChange={(f) => setFormData(f)}
          onSave={handleSave}
        />
      </Box>
      <Box sx={{ width: 320, position: "sticky", top: 0, alignSelf: "flex-start" }}>
        <Stack spacing={2}>
          <ValidationPanel errors={errors} />
          <PlanPanel formData={formData as never} />
          <FixturesPanel
            fixturePath={formData.fixture_path as string | undefined}
            referencePath={formData.reference_path as string | undefined}
            hasFixture={Boolean(summary?.has_fixture)}
            hasReference={Boolean(summary?.has_reference)}
            verifyCommand={detected.data?.command ?? null}
            verifySystem={detected.data?.system ?? null}
            verifyAmbiguous={detected.data?.ambiguous ?? false}
            verifyCandidates={detected.data?.candidates ?? []}
          />
          {name && <PreviousRunsPanel name={name} />}
        </Stack>
      </Box>
    </Stack>
  );
}
