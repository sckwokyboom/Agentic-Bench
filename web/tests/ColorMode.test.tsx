import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { ColorModeProvider } from "../src/theme";
import App from "../src/App";

// Node 25 ships an experimental global localStorage that lacks a usable clear();
// stub a clean in-memory Storage so persistence is deterministic in tests.
function makeStorage(): Storage {
  let store: Record<string, string> = {};
  return {
    getItem: (k) => (k in store ? store[k]! : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
    clear: () => { store = {}; },
    key: (i) => Object.keys(store)[i] ?? null,
    get length() { return Object.keys(store).length; },
  } as Storage;
}

beforeEach(() => { vi.stubGlobal("localStorage", makeStorage()); });
afterEach(() => { vi.unstubAllGlobals(); });

function renderApp() {
  return render(
    <ColorModeProvider>
      <MemoryRouter>
        <Routes><Route path="/" element={<App />} /></Routes>
      </MemoryRouter>
    </ColorModeProvider>,
  );
}

test("toggle flips the icon between light and dark", async () => {
  renderApp();
  // Light mode shows the "go dark" icon.
  expect(screen.getByTestId("Brightness4Icon")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /toggle color mode/i }));
  // Dark mode shows the "go light" icon.
  expect(screen.getByTestId("Brightness7Icon")).toBeInTheDocument();
});

test("toggle persists the chosen mode to localStorage", async () => {
  renderApp();
  await userEvent.click(screen.getByRole("button", { name: /toggle color mode/i }));
  expect(window.localStorage.getItem("abench-color-mode")).toBe("dark");
  await userEvent.click(screen.getByRole("button", { name: /toggle color mode/i }));
  expect(window.localStorage.getItem("abench-color-mode")).toBe("light");
});

test("restores saved dark mode from localStorage on mount", () => {
  window.localStorage.setItem("abench-color-mode", "dark");
  renderApp();
  // Restored to dark → the "go light" icon is shown.
  expect(screen.getByTestId("Brightness7Icon")).toBeInTheDocument();
});
