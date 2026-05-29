import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import App from "../src/App";

test("App renders the top-bar title", () => {
  render(
    <MemoryRouter>
      <Routes><Route path="/" element={<App />} /></Routes>
    </MemoryRouter>,
  );
  expect(screen.getByText("Agentic-Bench")).toBeInTheDocument();
});
