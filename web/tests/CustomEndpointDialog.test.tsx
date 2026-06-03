import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CustomEndpointDialog from "../src/components/CustomEndpointDialog";

function setup(onAdd = vi.fn(), onClose = vi.fn()) {
  render(<CustomEndpointDialog open onClose={onClose} onAdd={onAdd} />);
  return { onAdd, onClose };
}

test("renders all fields", () => {
  setup();
  expect(screen.getByLabelText(/provider id/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/base url/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/model name/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/api key/i)).toBeInTheDocument();
});

test("Add disabled until id + base URL + model filled", async () => {
  setup();
  const add = screen.getByRole("button", { name: /^add$/i });
  expect(add).toBeDisabled();

  await userEvent.type(screen.getByLabelText(/provider id/i), "myllm");
  expect(add).toBeDisabled();
  await userEvent.type(screen.getByLabelText(/base url/i), "http://10.0.0.5:8000/v1");
  expect(add).toBeDisabled();
  await userEvent.type(screen.getByLabelText(/model name/i), "my-model");
  expect(add).not.toBeDisabled();
});

test("Add fires onAdd with all four fields then closes", async () => {
  const { onAdd, onClose } = setup();
  await userEvent.type(screen.getByLabelText(/provider id/i), "myllm");
  await userEvent.type(screen.getByLabelText(/base url/i), "http://10.0.0.5:8000/v1");
  await userEvent.type(screen.getByLabelText(/model name/i), "my-model");
  await userEvent.type(screen.getByLabelText(/api key/i), "sk-secret");
  await userEvent.click(screen.getByRole("button", { name: /^add$/i }));
  expect(onAdd).toHaveBeenCalledWith({
    id: "myllm",
    baseUrl: "http://10.0.0.5:8000/v1",
    model: "my-model",
    apiKey: "sk-secret",
  });
  expect(onClose).toHaveBeenCalled();
});

test("keyless (blank key) still allows Add and passes apiKey: ''", async () => {
  const { onAdd } = setup();
  await userEvent.type(screen.getByLabelText(/provider id/i), "myllm");
  await userEvent.type(screen.getByLabelText(/base url/i), "http://10.0.0.5:8000/v1");
  await userEvent.type(screen.getByLabelText(/model name/i), "my-model");
  const add = screen.getByRole("button", { name: /^add$/i });
  expect(add).not.toBeDisabled();
  await userEvent.click(add);
  expect(onAdd).toHaveBeenCalledWith({
    id: "myllm",
    baseUrl: "http://10.0.0.5:8000/v1",
    model: "my-model",
    apiKey: "",
  });
});

test("Cancel closes without onAdd", async () => {
  const { onAdd, onClose } = setup();
  await userEvent.click(screen.getByRole("button", { name: /cancel/i }));
  expect(onClose).toHaveBeenCalled();
  expect(onAdd).not.toHaveBeenCalled();
});
