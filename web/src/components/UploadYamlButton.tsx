import { useRef } from "react";
import { Button } from "@mui/material";
import FileUploadIcon from "@mui/icons-material/FileUpload";
import { useUploadExperiment } from "../api/queries";

interface Props { onUploaded: (parsed: Record<string, unknown>) => void; }

export default function UploadYamlButton({ onUploaded }: Props) {
  const ref = useRef<HTMLInputElement>(null);
  const upload = useUploadExperiment();

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    const parsed = await upload.mutateAsync(text);
    onUploaded(parsed);
    if (ref.current) ref.current.value = "";
  }

  return (
    <>
      <Button
        variant="outlined" size="small"
        startIcon={<FileUploadIcon />}
        onClick={() => ref.current?.click()}
      >
        Upload YAML
      </Button>
      <input
        ref={ref}
        type="file"
        accept=".yaml,.yml"
        hidden
        onChange={handleFile}
      />
    </>
  );
}
