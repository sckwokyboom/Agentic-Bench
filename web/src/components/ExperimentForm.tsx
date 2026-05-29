import { useEffect, useMemo, useState } from "react";
import { Form } from "@rjsf/mui";
import validator from "@rjsf/validator-ajv8";
import type { RJSFSchema, RJSFValidationError, UiSchema } from "@rjsf/utils";
import { Box, Button, Stack } from "@mui/material";

interface Props {
  schema: RJSFSchema;
  uiSchema: UiSchema;
  formData: Record<string, unknown>;
  widgets?: Record<string, React.ComponentType<any>>;
  onSave: (data: Record<string, unknown>) => void;
  onFormChange?: (data: Record<string, unknown>, hasErrors: boolean) => void;
  onErrorsChange?: (errors: RJSFValidationError[]) => void;
}

export default function ExperimentForm({
  schema, uiSchema, formData, widgets, onSave, onFormChange, onErrorsChange,
}: Props) {
  const [data, setData] = useState<Record<string, unknown>>(formData);
  const errors = useMemo(
    () => validator.validateFormData(data, schema).errors,
    [data, schema],
  );
  const hasErrors = errors.length > 0;

  // Push errors to the parent without setState-during-render. Key the effect on a
  // content signature so a fresh-but-equal error array doesn't loop.
  const errorSignature = errors.map((e) => `${e.property ?? e.schemaPath}:${e.message}`).join("|");
  useEffect(() => {
    onErrorsChange?.(errors);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [errorSignature]);

  return (
    <Stack spacing={2}>
      <Box>
        <Form
          schema={schema}
          uiSchema={uiSchema}
          formData={data}
          widgets={widgets}
          validator={validator}
          liveValidate
          showErrorList={false}
          onChange={({ formData: f }) => {
            const next = f as Record<string, unknown>;
            setData(next);
            const nextErrors = validator.validateFormData(next, schema).errors;
            onFormChange?.(next, nextErrors.length > 0);
          }}
        />
      </Box>
      <Stack direction="row" justifyContent="flex-end">
        <Button
          variant="contained"
          disabled={hasErrors}
          onClick={() => onSave(data)}
        >Save</Button>
      </Stack>
    </Stack>
  );
}
