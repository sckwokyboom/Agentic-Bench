import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import FixturesPanel from "../src/components/FixturesPanel";

test("renders the detected command, system and an ambiguity warning icon", () => {
  const { container } = render(
    <FixturesPanel
      fixturePath="fixture/"
      referencePath="reference/"
      hasFixture
      hasReference
      verifyCommand="mvn test"
      verifySystem="maven"
      verifyAmbiguous
      verifyCandidates={["gradle", "maven"]}
    />,
  );
  expect(screen.getByText("mvn test")).toBeInTheDocument();
  expect(screen.getByText(/ambiguous \(gradle \+ maven\)/)).toBeInTheDocument();
  expect(screen.getByText(/using maven/)).toBeInTheDocument();
  expect(container.querySelector('[data-testid="WarningAmberIcon"]')).not.toBeNull();
});

test("explains the fixture vs reference paths for a newcomer", () => {
  render(
    <FixturesPanel
      fixturePath="fixture/"
      referencePath="reference/"
      hasFixture
      hasReference
      verifyCommand="pytest -q"
      verifySystem="pytest"
    />,
  );
  expect(screen.getByText(/working tree the agent edits/i)).toBeInTheDocument();
  expect(screen.getByText(/ground-truth original/i)).toBeInTheDocument();
});

test("shows the no-build-system hint when no command is detected", () => {
  render(
    <FixturesPanel
      fixturePath="fixture/"
      referencePath="reference/"
      hasFixture
      hasReference
      verifyCommand={null}
      verifySystem={null}
    />,
  );
  expect(screen.getByText(/no build system detected/i)).toBeInTheDocument();
});

test("renders no ambiguity caption when unambiguous", () => {
  render(
    <FixturesPanel
      fixturePath="fixture/"
      referencePath="reference/"
      hasFixture
      hasReference
      verifyCommand="pytest -q"
      verifySystem="pytest"
      verifyAmbiguous={false}
      verifyCandidates={[]}
    />,
  );
  expect(screen.getByText("pytest -q")).toBeInTheDocument();
  expect(screen.queryByText(/ambiguous/)).not.toBeInTheDocument();
});
