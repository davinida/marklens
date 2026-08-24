// @vitest-environment node

import { describe, expect, it } from "vitest";
import nextConfig from "@/next.config";

describe("content security policy", () => {
  it("limits result images to same-origin and local preview schemes", async () => {
    const rules = await nextConfig.headers?.();
    const csp = rules?.[0]?.headers.find(
      (header) => header.key === "Content-Security-Policy",
    )?.value;

    expect(csp).toContain("img-src 'self' blob: data:");
    expect(csp).not.toMatch(/img-src[^;]*https:/);
  });
});
