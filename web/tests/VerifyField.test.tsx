import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FieldProps } from "@rjsf/utils";
import VerifyField from "../src/components/VerifyField";

type VerifyData = { command: string | null; enabled: boolean; timeout_s: number };

// Build a minimal-but-typed FieldProps for the verify object. VerifyField only
// reads formData / onChange / formContext, so the rest can be permissive casts.
function makeProps(
  formData: Partial<VerifyData>,
  onChange: (v: unknown) => void,
  formContext?: Record<string, unknown>,
): FieldProps {
  const data: VerifyData = {
    command: formData.command ?? null,
    enabled: formData.enabled ?? true,
    timeout_s: formData.timeout_s ?? 300,
  };
  return {
    schema: { type: "object" },
    idSchema: { $id: "root_verify" },
    formData: data,
    onChange,
    formContext,
    registry: {} as never,
    name: "verify",
    onBlur: () => {},
    onFocus: () => {},
  } as unknown as FieldProps;
}

// A controlled harness mirroring how rjsf feeds onChange back as the next
// formData, so multi-keystroke inputs behave like they do in the real Form.
function Harness({
  initial,
  onChange,
  formContext,
}: {
  initial: Partial<VerifyData>;
  onChange: (v: unknown) => void;
  formContext?: Record<string, unknown>;
}) {
  const [data, setData] = useState<Partial<VerifyData>>(initial);
  return (
    <VerifyField
      {...makeProps(data, (v) => {
        setData(v as VerifyData);
        onChange(v);
      }, formContext)}
    />
  );
}

function getBuildSystemSelect(): HTMLElement {
  // MUI Select renders a combobox role.
  return screen.getByRole("combobox", { name: /build system/i });
}

async function selectBuildSystem(label: RegExp) {
  await userEvent.click(getBuildSystemSelect());
  const listbox = await screen.findByRole("listbox");
  await userEvent.click(within(listbox).getByRole("option", { name: label }));
}

test("selecting gradle sets command to the canonical 'gradle test'", async () => {
  const onChange = vi.fn();
  render(<VerifyField {...makeProps({ command: null }, onChange)} />);
  await selectBuildSystem(/^gradle/i);
  expect(onChange).toHaveBeenCalledWith(
    expect.objectContaining({ command: "gradle test", enabled: true, timeout_s: 300 }),
  );
});

test("selecting auto sets command to null", async () => {
  const onChange = vi.fn();
  // start from gradle so 'auto' is a real change
  render(<VerifyField {...makeProps({ command: "gradle test" }, onChange)} />);
  await selectBuildSystem(/^auto/i);
  expect(onChange).toHaveBeenCalledWith(
    expect.objectContaining({ command: null }),
  );
});

test("selecting custom reveals a Command text field and typing writes command", async () => {
  const onChange = vi.fn();
  render(<Harness initial={{ command: null }} onChange={onChange} />);
  // No command text field while on auto.
  expect(screen.queryByRole("textbox", { name: /command/i })).toBeNull();

  await selectBuildSystem(/^custom/i);
  const cmd = await screen.findByRole("textbox", { name: /command/i });
  expect(cmd).toBeInTheDocument();

  await userEvent.type(cmd, "X");
  expect(onChange).toHaveBeenCalledWith(
    expect.objectContaining({ command: "X" }),
  );
});

test("non-canonical command initialises the Select to custom and pre-fills the text field", () => {
  const onChange = vi.fn();
  render(<VerifyField {...makeProps({ command: "./gradlew check" }, onChange)} />);
  // Select shows the custom value.
  expect(getBuildSystemSelect()).toHaveTextContent(/custom/i);
  // Command text field is present and pre-filled.
  const cmd = screen.getByRole("textbox", { name: /command/i }) as HTMLInputElement;
  expect(cmd).toBeInTheDocument();
  expect(cmd.value).toBe("./gradlew check");
});

test("canonical maven command shows 'maven' selected and no custom text field", () => {
  const onChange = vi.fn();
  render(<VerifyField {...makeProps({ command: "mvn test" }, onChange)} />);
  expect(getBuildSystemSelect()).toHaveTextContent(/maven/i);
  expect(screen.queryByRole("textbox", { name: /command/i })).toBeNull();
});

test("toggling enabled writes back into the full verify object", async () => {
  const onChange = vi.fn();
  render(<VerifyField {...makeProps({ command: "pytest", enabled: true }, onChange)} />);
  const sw = screen.getByRole("checkbox", { name: /enabled/i });
  await userEvent.click(sw);
  expect(onChange).toHaveBeenCalledWith(
    expect.objectContaining({ enabled: false, command: "pytest" }),
  );
});

test("editing timeout writes a number back into the verify object", async () => {
  const onChange = vi.fn();
  render(<Harness initial={{ command: null, timeout_s: 300 }} onChange={onChange} />);
  const t = screen.getByRole("spinbutton", { name: /timeout/i });
  await userEvent.clear(t);
  await userEvent.type(t, "60");
  // last call should carry timeout_s 60
  const lastArg = onChange.mock.calls.at(-1)?.[0] as { timeout_s: number };
  expect(lastArg.timeout_s).toBe(60);
});

test("formContext.detectedVerify.system annotates the auto option label", async () => {
  const onChange = vi.fn();
  render(
    <VerifyField
      {...makeProps({ command: null }, onChange, { detectedVerify: { system: "gradle" } })}
    />,
  );
  // The auto option mentions the detected system somewhere in the field.
  await userEvent.click(getBuildSystemSelect());
  const listbox = await screen.findByRole("listbox");
  expect(within(listbox).getByRole("option", { name: /auto.*gradle/i })).toBeInTheDocument();
});
