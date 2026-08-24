import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

if (!URL.createObjectURL) {
  URL.createObjectURL = vi.fn(() => "blob:marklens-preview");
}
if (!URL.revokeObjectURL) {
  URL.revokeObjectURL = vi.fn();
}

if (typeof HTMLDialogElement !== "undefined") {
  HTMLDialogElement.prototype.showModal ??= function showModal() {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function close() {
    this.removeAttribute("open");
  };
}
