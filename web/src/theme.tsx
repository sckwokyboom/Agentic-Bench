import {
  createContext, useContext, useEffect, useMemo, useState, type ReactNode,
} from "react";
import { createTheme, ThemeProvider, type Theme } from "@mui/material/styles";
import CssBaseline from "@mui/material/CssBaseline";

export type ColorMode = "light" | "dark";

export const selectable = { userSelect: "text", cursor: "text" } as const;

export function makeTheme(mode: ColorMode): Theme {
  const primary =
    mode === "dark"
      ? { main: "#cbd5e1", contrastText: "#0d1117" }
      : { main: "#1f2937", contrastText: "#ffffff" };
  return createTheme({
    palette: {
      mode,
      primary,
      ...(mode === "dark"
        ? { background: { default: "#0d1117", paper: "#161b22" } }
        : { background: { default: "#fafafa", paper: "#ffffff" } }),
    },
    typography: {
      fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
      fontSize: 14,
    },
    shape: { borderRadius: 6 },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          // Static UI text must not look editable: chrome is non-selectable with a
          // default cursor; genuine content opts back in via `selectable`.
          body: { cursor: "default", userSelect: "none" },
        },
      },
    },
  });
}

interface ColorModeCtx {
  mode: ColorMode;
  toggle: () => void;
}

// Default value keeps components renderable without a provider (e.g. in tests).
const ColorModeContext = createContext<ColorModeCtx>({
  mode: "light",
  toggle: () => {},
});

export function useColorMode(): ColorModeCtx {
  return useContext(ColorModeContext);
}

const STORAGE_KEY = "abench-color-mode";

function initialMode(): ColorMode {
  if (typeof window !== "undefined") {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "light" || saved === "dark") return saved;
    if (window.matchMedia?.("(prefers-color-scheme: dark)")?.matches) return "dark";
  }
  return "light";
}

export function ColorModeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ColorMode>(initialMode);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      /* localStorage unavailable — ignore */
    }
  }, [mode]);

  const ctx = useMemo<ColorModeCtx>(
    () => ({
      mode,
      toggle: () => setMode((m) => (m === "light" ? "dark" : "light")),
    }),
    [mode],
  );
  const theme = useMemo(() => makeTheme(mode), [mode]);

  return (
    <ColorModeContext.Provider value={ctx}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </ThemeProvider>
    </ColorModeContext.Provider>
  );
}
