import type { ObjectFieldTemplateProps, ObjectFieldTemplatePropertyType } from "@rjsf/utils";
import {
  Accordion, AccordionDetails, AccordionSummary, Box, Stack, Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";

// Primary fields grouped under light headers; everything else falls to Advanced.
const GROUPS: { title: string; fields: string[] }[] = [
  { title: "Basics", fields: ["name", "model", "model_context_window"] },
  { title: "Task", fields: ["task_prompt", "system_prompt", "target_file", "target_methods", "fixture_path", "reference_path"] },
  { title: "Conditions", fields: ["conditions"] },
  { title: "Run", fields: ["repetitions", "verify"] },
];
const PRIMARY = new Set<string>(GROUPS.flatMap((g) => g.fields));

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

  const grouped = new Map(props.properties.map((p) => [p.name, p]));
  const advanced: ObjectFieldTemplatePropertyType[] = [];
  for (const p of props.properties) {
    if (!PRIMARY.has(p.name)) advanced.push(p);
  }

  return (
    <Box>
      {header}
      {GROUPS.map((g) => {
        const items = g.fields
          .map((f) => grouped.get(f))
          .filter((p): p is ObjectFieldTemplatePropertyType => Boolean(p));
        if (items.length === 0) return null;
        return (
          <Box key={g.title} sx={{ mb: 2 }}>
            <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 0.5 }}>{g.title}</Typography>
            {renderProps(items)}
          </Box>
        );
      })}
      {advanced.length > 0 && (
        <Accordion defaultExpanded={false} sx={{ mt: 1 }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography>Advanced (output, timeouts, isolation, metrics, opencode, orchestration)</Typography>
          </AccordionSummary>
          <AccordionDetails>{renderProps(advanced)}</AccordionDetails>
        </Accordion>
      )}
    </Box>
  );
}
