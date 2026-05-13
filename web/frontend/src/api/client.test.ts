import { describe, expect, it } from "vitest";
import { ApiError, formatApiError } from "./client";

describe("formatApiError", () => {
  it("includes endpoint and status", () => {
    const error = new ApiError("route missing", 404, { detail: "not found" }, "/api/example");

    expect(formatApiError(error)).toContain("/api/example");
    expect(formatApiError(error)).toContain("HTTP 404");
    expect(formatApiError(error)).toContain("route missing");
  });
});
