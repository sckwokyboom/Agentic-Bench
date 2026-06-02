import { Chip, Tooltip } from "@mui/material";
import LockIcon from "@mui/icons-material/Lock";
import LockOpenIcon from "@mui/icons-material/LockOpen";

interface Props {
  nonce: boolean;
  shuffle: boolean;
}

const TOOLTIP =
  "nonce = a unique comment prefixed to the system prompt so each run misses " +
  "the provider's prompt cache; shuffle = randomized condition×rep order to " +
  "avoid ordering bias.";

export default function IsolationChip({ nonce, shuffle }: Props) {
  let chip;
  if (nonce && shuffle) {
    chip = (
      <Chip
        size="small"
        color="success"
        icon={<LockIcon fontSize="inherit" />}
        label="isolated (nonce + shuffled)"
        variant="outlined"
      />
    );
  } else if (!nonce && !shuffle) {
    chip = (
      <Chip
        size="small"
        color="warning"
        icon={<LockOpenIcon fontSize="inherit" />}
        label="isolation off"
        variant="outlined"
      />
    );
  } else {
    chip = (
      <Chip
        size="small"
        color="warning"
        icon={<LockIcon fontSize="inherit" />}
        label={`isolated (${nonce ? "nonce" : "shuffle"} only)`}
        variant="outlined"
      />
    );
  }
  return (
    <Tooltip title={TOOLTIP}>
      {/* aria-label mirrors the tooltip so it is assertable without hover. */}
      <span aria-label={TOOLTIP}>{chip}</span>
    </Tooltip>
  );
}
