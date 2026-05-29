import { createBrowserRouter, Navigate } from "react-router-dom";
import App from "./App";
import ExperimentList from "./pages/ExperimentList";
import ExperimentEdit from "./pages/ExperimentEdit";
import RunsIndex from "./pages/RunsIndex";
import ExperimentResults from "./pages/ExperimentResults";
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
      { path: "runs", element: <RunsIndex /> },
      { path: "runs/sessions/:sid", element: <Run /> },
      { path: "runs/:name", element: <ExperimentResults /> },
      { path: "runs/:name/:condition/:rep", element: <TraceView /> },
    ],
  },
]);
