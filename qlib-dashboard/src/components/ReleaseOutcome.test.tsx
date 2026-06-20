import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReleaseOutcome } from "./ReleaseOutcome";

describe("ReleaseOutcome", () => {
  it.each(["loading", "empty", "partial", "stale", "failed", "blocked", "success"] as const)(
    "exposes the %s outcome as text and machine-readable state",
    (state) => {
      render(<ReleaseOutcome state={state} reason={`${state} reason`} />);

      expect(screen.getByRole(state === "failed" || state === "blocked" ? "alert" : "status"))
        .toHaveAttribute("data-outcome", state);
      expect(screen.getByText(state[0].toUpperCase() + state.slice(1), { exact: true })).toBeVisible();
      expect(screen.getByText(`${state} reason`)).toBeVisible();
    },
  );

  it("renders detail list when details are provided", () => {
    render(
      <ReleaseOutcome
        state="blocked"
        reason="Promotion blocked."
        details={["Sharpe ratio below threshold", "Max drawdown exceeds limit"]}
      />,
    );

    expect(screen.getByRole("alert")).toHaveAttribute("data-outcome", "blocked");
    expect(screen.getByText("Promotion blocked.")).toBeVisible();
    expect(screen.getByText("Sharpe ratio below threshold")).toBeVisible();
    expect(screen.getByText("Max drawdown exceeds limit")).toBeVisible();
  });

  it("does not render details list when details is empty", () => {
    const { container } = render(
      <ReleaseOutcome state="blocked" reason="No details." details={[]} />,
    );

    expect(container.querySelector("[data-outcome-details]")).toBeNull();
  });

  it("does not render details list when details is undefined", () => {
    const { container } = render(
      <ReleaseOutcome state="success" reason="All good." />,
    );

    expect(container.querySelector("[data-outcome-details]")).toBeNull();
  });

  it("renders gate failure details in blocked state", () => {
    render(
      <ReleaseOutcome
        state="blocked"
        reason="Snapshot quality checks block training."
        details={[
          "Sharpe ratio 0.3 below minimum 0.5",
          "Max drawdown -0.25 exceeds limit -0.15",
        ]}
      />,
    );

    const detailsList = screen.getByRole("alert").querySelector("[data-outcome-details]");
    expect(detailsList).not.toBeNull();
    expect(detailsList!.children).toHaveLength(2);
  });
});
