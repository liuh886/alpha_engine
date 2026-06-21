import { describe, expect, it } from "vitest";

import { formatTimestamp } from "./types";

describe("formatTimestamp", () => {
  it("formats compact walk-forward timestamps", () => {
    expect(formatTimestamp("20260620_003612")).not.toContain("Invalid Date");
  });

  it("returns the source text for an invalid timestamp", () => {
    expect(formatTimestamp("legacy-invalid")).toBe("legacy-invalid");
  });
});
