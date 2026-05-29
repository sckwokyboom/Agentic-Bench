import { AppBar, Box, Toolbar, Typography, IconButton, Tooltip } from "@mui/material";
import Brightness4Icon from "@mui/icons-material/Brightness4";
import Brightness7Icon from "@mui/icons-material/Brightness7";
import { Outlet, NavLink } from "react-router-dom";
import { useColorMode } from "./theme";

// `inherit` so the nav link reads against the AppBar in both light and dark.
const linkStyle = { color: "inherit", textDecoration: "none", marginLeft: 24 };

export default function App() {
  const { mode, toggle } = useColorMode();
  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <AppBar position="static">
        <Toolbar>
          <Typography variant="h6" sx={{ flexGrow: 0 }}>Agentic-Bench</Typography>
          <NavLink to="/experiments" style={linkStyle}>Experiments</NavLink>
          <Box sx={{ flexGrow: 1 }} />
          <Tooltip title={mode === "dark" ? "Switch to light theme" : "Switch to dark theme"}>
            <IconButton color="inherit" onClick={toggle} aria-label="toggle color mode">
              {mode === "dark" ? <Brightness7Icon /> : <Brightness4Icon />}
            </IconButton>
          </Tooltip>
        </Toolbar>
      </AppBar>
      <Box component="main" sx={{ flexGrow: 1, overflow: "auto", p: 3 }}>
        <Outlet />
      </Box>
    </Box>
  );
}
