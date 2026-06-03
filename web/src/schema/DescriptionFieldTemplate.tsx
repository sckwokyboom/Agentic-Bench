import type { DescriptionFieldProps } from "@rjsf/utils";
import { Typography } from "@mui/material";

export default function DescriptionFieldTemplate({ description }: DescriptionFieldProps) {
  if (!description) return null;
  return (
    <Typography
      variant="caption"
      color="text.secondary"
      sx={{ display: "block", fontWeight: 400, mt: 0.25, mb: 0.75, lineHeight: 1.4 }}
    >
      {description}
    </Typography>
  );
}
