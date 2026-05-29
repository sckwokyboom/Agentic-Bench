import { createTheme } from "@mui/material/styles";

export const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#1976d2" },
    success: { main: "#2e7d32" },
    warning: { main: "#ed6c02" },
    error:   { main: "#d32f2f" },
    background: { default: "#fafafa" },
  },
  typography: {
    fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    fontSize: 14,
  },
  shape: { borderRadius: 6 },
});
