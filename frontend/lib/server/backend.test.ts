// @vitest-environment node

import { describe, expect, it, vi } from "vitest";
import { getBackendConfig } from "@/lib/server/backend";
import { getRequestId } from "@/lib/server/request-id";

describe("backend server configuration", () => {
  it("fails closed when the production API key is blank", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("MARKLENS_BACKEND_URL", "https://backend.example");
    vi.stubEnv("MARKLENS_BACKEND_API_KEY", "   ");

    expect(() => getBackendConfig()).toThrow("MARKLENS_BACKEND_API_KEY");
  });

  it("normalizes a complete production configuration", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("MARKLENS_BACKEND_URL", " https://backend.example/ ");
    vi.stubEnv("MARKLENS_BACKEND_API_KEY", " private-key ");

    expect(getBackendConfig()).toEqual({
      baseUrl: "https://backend.example",
      apiKey: "private-key",
    });
  });
});

describe("request IDs", () => {
  it("preserves a bounded safe ingress request ID", () => {
    expect(getRequestId(new Headers({ "x-request-id": "edge.req-123" }))).toBe(
      "edge.req-123",
    );
  });

  it("replaces an unsafe ingress request ID", () => {
    const requestId = getRequestId(
      new Headers({ "x-request-id": "unsafe request id" }),
    );

    expect(requestId).not.toContain("unsafe");
    expect(requestId).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });
});
