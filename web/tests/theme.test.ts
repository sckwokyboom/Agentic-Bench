import { expect, test } from "vitest";
import { makeTheme, selectable } from "../src/theme";

test("primary is a neutral (non-blue) color in both modes", () => {
  const light = makeTheme("light");
  const dark = makeTheme("dark");
  expect(light.palette.primary.main.toLowerCase()).toBe("#1f2937");
  expect(dark.palette.primary.main.toLowerCase()).toBe("#cbd5e1");
  expect(light.palette.primary.main).not.toBe("#1976d2");
});

test("selectable helper opts content back into text selection", () => {
  expect(selectable).toEqual({ userSelect: "text", cursor: "text" });
});
