import { Stack, Chip, Typography } from "@mui/material";
import { stopReasonHistogram } from "../lib/stopReasonHistogram";
import { formatTokens } from "../lib/formatTokens";
import type { TurnInfo } from "../api/types";

interface Props { turns: TurnInfo[]; }

export default function AggregateStatsBar({ turns }: Props) {
  const hist = stopReasonHistogram(turns);
  const tokensIn = turns.reduce((s, t) => s + (t.tokens_in ?? 0), 0);
  const tokensOut = turns.reduce((s, t) => s + (t.tokens_out ?? 0), 0);
  const cost = turns.reduce((s, t) => s + (t.cost ?? 0), 0);
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
      {Object.entries(hist).map(([reason, n]) => (
        <Chip key={reason} size="small" label={`${n} ${reason}`} variant="outlined" />
      ))}
      <Typography variant="body2" color="text.secondary">
        tokens in: {formatTokens(tokensIn)} · out: {formatTokens(tokensOut)} · cost: ${cost.toFixed(4)}
      </Typography>
    </Stack>
  );
}
