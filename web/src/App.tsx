import { AppBar, Box, Toolbar, Typography } from "@mui/material";
import { Outlet, NavLink } from "react-router-dom";

const linkStyle = { color: "white", textDecoration: "none", marginLeft: 24 };

export default function App() {
  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <AppBar position="static">
        <Toolbar>
          <Typography variant="h6" sx={{ flexGrow: 0 }}>Agentic-Bench</Typography>
          <NavLink to="/experiments" style={linkStyle}>Experiments</NavLink>
        </Toolbar>
      </AppBar>
      <Box component="main" sx={{ flexGrow: 1, overflow: "auto", p: 3 }}>
        <Outlet />
      </Box>
    </Box>
  );
}
