import type { ReactElement } from "react";
import type { ArrayFieldTemplateItemType } from "@rjsf/utils";
import { Box, Typography } from "@mui/material";

// rjsf renders each array item's content as a SchemaField element whose props
// carry the item's own formData. We read `name` from there to title the item by
// data rather than by index. (Verified against @rjsf/core 5.24 ArrayField.)
function itemName(children: ReactElement): string | undefined {
  const props = children.props as { formData?: { name?: unknown } } | undefined;
  const name = props?.formData?.name;
  return typeof name === "string" && name.length > 0 ? name : undefined;
}

/**
 * ArrayFieldItemTemplate for the `conditions` array: prefixes each item with a
 * "Condition: <name>" header (falling back to the 1-based index), then delegates
 * to the theme's default item template so the move/copy/remove toolbar is
 * preserved unchanged.
 */
export default function ConditionItemTemplate(props: ArrayFieldTemplateItemType) {
  const Default = props.registry.templates.ArrayFieldItemTemplate;
  const label = itemName(props.children) ?? `${props.index + 1}`;
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ mt: 1 }}>
        Condition: {label}
      </Typography>
      <Default {...props} />
    </Box>
  );
}
