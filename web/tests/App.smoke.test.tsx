import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import App from "../src/App";

test("App renders the top-bar title", () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Routes><Route path="/" element={<App />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(screen.getByText("Agentic-Bench")).toBeInTheDocument();
});
