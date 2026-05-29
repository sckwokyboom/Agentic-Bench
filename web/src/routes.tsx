import { createBrowserRouter, Navigate } from "react-router-dom";
import App from "./App";
import ExperimentList from "./pages/ExperimentList";
import ExperimentEdit from "./pages/ExperimentEdit";
import Run from "./pages/Run";
import TraceView from "./pages/TraceView";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <Navigate to="/experiments" replace /> },
      { path: "experiments", element: <ExperimentList /> },
      { path: "experiments/:name", element: <ExperimentEdit /> },
      { path: "runs/sessions/:sid", element: <Run /> },
      { path: "runs/:name/:condition/:rep", element: <TraceView /> },
    ],
  },
]);
