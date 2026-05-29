import { useMemo, useState } from "react";
import { Form } from "@rjsf/mui";
import validator from "@rjsf/validator-ajv8";
import type { RJSFSchema, UiSchema } from "@rjsf/utils";
import { Box, Button, Stack } from "@mui/material";

interface Props {
  schema: RJSFSchema;
  uiSchema: UiSchema;
  formData: Record<string, unknown>;
  widgets?: Record<string, React.ComponentType<any>>;
  onSave: (data: Record<string, unknown>) => void;
  onFormChange?: (data: Record<string, unknown>, hasErrors: boolean) => void;
}

export default function ExperimentForm({
  schema, uiSchema, formData, widgets, onSave, onFormChange,
}: Props) {
  const [data, setData] = useState<Record<string, unknown>>(formData);
  const errors = useMemo(
    () => validator.validateFormData(data, schema).errors,
    [data, schema],
  );
  const hasErrors = errors.length > 0;

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
