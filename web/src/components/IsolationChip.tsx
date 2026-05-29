import { Chip } from "@mui/material";

interface Props {
  nonce: boolean;
  shuffle: boolean;
}

export default function IsolationChip({ nonce, shuffle }: Props) {
  if (nonce && shuffle) {
    return <Chip size="small" color="success" label="🔒 isolated (nonce + shuffled)" variant="outlined" />;
  }
  if (!nonce && !shuffle) {
    return <Chip size="small" color="warning" label="🔓 isolation off" variant="outlined" />;
  }
  return <Chip size="small" color="warning"
    label={`🔒 isolated (${nonce ? "nonce" : "shuffle"} only)`} variant="outlined" />;
}
