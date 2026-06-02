import type { ComponentType } from "react";
import type { ObjectFieldTemplateProps, ObjectFieldTemplatePropertyType } from "@rjsf/utils";
import {
  Accordion, AccordionDetails, AccordionSummary, Box, Stack, Typography,
} from "@mui/material";
// The MUI theme's default ObjectFieldTemplate. We import it directly rather than
// reading props.registry.templates.ObjectFieldTemplate, because once this custom
// template is registered the registry slot IS this component — delegating to it
// would recurse infinitely. The sub-path import gives us the true theme default.
import MuiObjectFieldTemplate from "@rjsf/mui/lib/ObjectFieldTemplate/ObjectFieldTemplate.js";

// Root properties that belong in the collapsible "Advanced" accordion. Everything
// else stays in the always-visible core section.
const ADVANCED = new Set<string>([
  "metrics",
  "isolation",
  "opencode",
  "timeout_s",
  "min_seconds_between_runs",
  "output_dir",
  "target_file",
  "target_methods",
  "fixture_path",
  "reference_path",
]);

/**
 * Custom ObjectFieldTemplate. Only the ROOT object is special-cased: its
 * properties are split into a core section and a collapsed "Advanced" accordion.
 * Every non-root object delegates to the theme's default ObjectFieldTemplate so
 * nested objects (verify, conditions items, isolation, ...) render normally.
 */
export default function RootObjectFieldTemplate(props: ObjectFieldTemplateProps) {
  const Default = MuiObjectFieldTemplate as ComponentType<ObjectFieldTemplateProps>;
  if (props.idSchema.$id !== "root") return <Default {...props} />;

  const core: ObjectFieldTemplatePropertyType[] = [];
  const advanced: ObjectFieldTemplatePropertyType[] = [];
  for (const p of props.properties) {
    (ADVANCED.has(p.name) ? advanced : core).push(p);
  }

  return (
    <Box>
      {props.title && (
        <Typography variant="h6" sx={{ mb: 1 }}>{props.title}</Typography>
      )}
      {props.description && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {props.description}
        </Typography>
      )}

      <Stack spacing={1}>
        {core.map((p) => (
          <Box key={p.name}>{p.content}</Box>
        ))}
      </Stack>

      {advanced.length > 0 && (
        <Accordion defaultExpanded={false} sx={{ mt: 2 }}>
          <AccordionSummary expandIcon={<span aria-hidden>▾</span>}>
            <Typography>Advanced (metrics, isolation, paths, tuning)</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Stack spacing={1}>
              {advanced.map((p) => (
                <Box key={p.name}>{p.content}</Box>
              ))}
            </Stack>
          </AccordionDetails>
        </Accordion>
      )}
    </Box>
  );
}
