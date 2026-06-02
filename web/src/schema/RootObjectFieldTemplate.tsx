import type { ObjectFieldTemplateProps, ObjectFieldTemplatePropertyType } from "@rjsf/utils";
import {
  Accordion, AccordionDetails, AccordionSummary, Box, Stack, Typography,
} from "@mui/material";

// Root properties that belong in the collapsible "Advanced" accordion. Everything
// else (including the REQUIRED identity fields name/model/prompts/paths) stays in
// the always-visible core section so a blocking validation error is never hidden.
const ADVANCED = new Set<string>([
  "metrics",
  "isolation",
  "opencode",
  "timeout_s",
  "min_seconds_between_runs",
  "target_file",
  "target_methods",
]);

function renderProps(properties: ObjectFieldTemplatePropertyType[]) {
  return (
    <Stack spacing={1}>
      {properties.map((p) => (
        <Box key={p.name}>{p.content}</Box>
      ))}
    </Stack>
  );
}

/**
 * Custom ObjectFieldTemplate. The ROOT object is split into a core section and a
 * collapsed "Advanced" accordion. Every non-root object (isolation, opencode,
 * condition items, ...) renders its properties as a simple vertical stack — we
 * render `properties` ourselves rather than delegating to the theme default,
 * which both avoids an infinite recursion (the registry slot IS this component
 * once registered) and avoids a fragile deep import of an @rjsf/mui internal path.
 */
export default function RootObjectFieldTemplate(props: ObjectFieldTemplateProps) {
  const isRoot = props.idSchema.$id === "root";

  const header = (
    <>
      {props.title && (
        <Typography variant={isRoot ? "h6" : "subtitle2"} sx={{ mb: isRoot ? 1 : 0.5 }}>
          {props.title}
        </Typography>
      )}
      {props.description && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          {props.description}
        </Typography>
      )}
    </>
  );

  if (!isRoot) {
    return <Box>{header}{renderProps(props.properties)}</Box>;
  }

  const core: ObjectFieldTemplatePropertyType[] = [];
  const advanced: ObjectFieldTemplatePropertyType[] = [];
  for (const p of props.properties) {
    (ADVANCED.has(p.name) ? advanced : core).push(p);
  }

  return (
    <Box>
      {header}
      {renderProps(core)}
      {advanced.length > 0 && (
        <Accordion defaultExpanded={false} sx={{ mt: 2 }}>
          <AccordionSummary expandIcon={<span aria-hidden>▾</span>}>
            <Typography>Advanced (metrics, isolation, tuning)</Typography>
          </AccordionSummary>
          <AccordionDetails>{renderProps(advanced)}</AccordionDetails>
        </Accordion>
      )}
    </Box>
  );
}
