import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Stack, Box, Typography, CircularProgress, Alert, Button, Snackbar,
} from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import type { RJSFValidationError } from "@rjsf/utils";
import ExperimentForm from "../components/ExperimentForm";
import SavedExperimentCard from "../components/SavedExperimentCard";
import { type CustomEndpointInput } from "../components/CustomEndpointDialog";
import ValidationPanel from "../components/ValidationPanel";
import ReachabilityPanel from "../components/ReachabilityPanel";
import type { ValidateReachabilityResp } from "../api/types";
import PlanPanel from "../components/PlanPanel";
import FixturesPanel from "../components/FixturesPanel";
import PreviousRunsPanel from "../components/PreviousRunsPanel";
import {
  useExperiment, useExperiments, useSaveExperiment, useStartRun, useDetectedVerify,
  useWriteProviderCredentials,
} from "../api/queries";
import { applyCustomEndpoint } from "../lib/customEndpoint";
import { loadSchema, type JsonSchema } from "../api/schemaCache";
import { uiSchema } from "../schema/uiSchema";
import {
  ModelValidationWidget, TargetMethodsWidget, AugmentationWidget,
} from "../schema/widgets";
import RootObjectFieldTemplate from "../schema/RootObjectFieldTemplate";
import DescriptionFieldTemplate from "../schema/DescriptionFieldTemplate";
import VerifyField from "../components/VerifyField";

const customWidgets = { ModelValidationWidget, TargetMethodsWidget, AugmentationWidget };
const customFields = { VerifyField };
const customTemplates = {
  ObjectFieldTemplate: RootObjectFieldTemplate,
  DescriptionFieldTemplate,
};

export default function ExperimentEdit() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const [schema, setSchema] = useState<JsonSchema | null>(null);
  const exp = useExperiment(name);
  const detected = useDetectedVerify(name);
  const list = useExperiments();
  const save = useSaveExperiment();
  const start = useStartRun();
  const writeCreds = useWriteProviderCredentials();
  const [formData, setFormData] = useState<Record<string, unknown> | null>(null);
  const [errors, setErrors] = useState<RJSFValidationError[]>([]);
  const [saved, setSaved] = useState(false);
  const [toastOpen, setToastOpen] = useState(false);
  const [formKey, setFormKey] = useState(0);
  const [reach, setReach] = useState<ValidateReachabilityResp | null>(null);

  useEffect(() => { loadSchema().then(setSchema); }, []);
  useEffect(() => { if (exp.data && formData === null) setFormData(exp.data); }, [exp.data, formData]);

  const summary = list.data?.find((e) => e.name === name);
  const canRun = errors.length === 0 && Boolean(summary?.has_fixture);

  async function handleSave(data: Record<string, unknown>) {
    if (!name) return;
    await save.mutateAsync({ name, body: data });
    setSaved(true);
    setToastOpen(true);
  }

  async function handleRun() {
    if (!name) return;
    // Gate-with-override: if a reachability test failed, confirm before a run.
    if (reach && !reach.reachable) {
      const ok = window.confirm(
        `Model looks unreachable (${reach.reason}`
        + `${reach.detail ? ": " + reach.detail : ""}). Run anyway?`);
      if (!ok) return;
    }
    const { session_id } = await start.mutateAsync(name);
    navigate(`/runs/sessions/${session_id}`, { state: { experimentName: name } });
  }

  async function handleAddEndpoint({ id, baseUrl, model, apiKey }: CustomEndpointInput) {
    const next = applyCustomEndpoint(formData ?? {}, { id, baseUrl, model });
    setFormData(next);
    setSaved(false);
    setFormKey((k) => k + 1); // remount ExperimentForm so it re-initializes from next
    if (apiKey) {
      // Best-effort: the key lands only in opencode auth.json, never in formData.
      try {
        await writeCreds.mutateAsync({ provider: id, api_key: apiKey });
      } catch (e) {
        console.warn("Failed to write provider credentials; wiring kept anyway.", e);
      }
    }
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
            startIcon={<PlayArrowIcon />}
          >
            Run
          </Button>
        </Stack>
        {save.isError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            Failed to save: {(save.error as Error)?.message ?? "unknown error"}
          </Alert>
        )}
        {saved ? (
          <SavedExperimentCard
            name={name ?? ""}
            formData={formData}
            canRun={canRun}
            running={start.isPending}
            onRun={handleRun}
            onEdit={() => setSaved(false)}
          />
        ) : (
          <ExperimentForm
            key={formKey}
            schema={schema as never}
            uiSchema={uiSchema}
            formData={formData}
            widgets={customWidgets}
            fields={customFields}
            templates={customTemplates}
            formContext={{ detectedVerify: detected.data, onAddCustomEndpoint: handleAddEndpoint }}
            saving={save.isPending}
            onErrorsChange={setErrors}
            onFormChange={(f) => { setFormData(f); setSaved(false); setReach(null); }}
            onSave={handleSave}
          />
        )}
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
          {name && <ReachabilityPanel name={name} onResult={setReach} />}
          {name && <PreviousRunsPanel name={name} />}
        </Stack>
      </Box>
      <Snackbar
        open={toastOpen}
        autoHideDuration={4000}
        onClose={() => setToastOpen(false)}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      >
        <Alert severity="success" variant="filled" onClose={() => setToastOpen(false)}>
          Configuration saved
        </Alert>
      </Snackbar>
    </Stack>
  );
}
