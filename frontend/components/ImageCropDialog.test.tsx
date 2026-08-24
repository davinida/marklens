import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ImageCropDialog from "@/components/ImageCropDialog";

describe("ImageCropDialog", () => {
  it("keeps the crop controls in a viewport-bounded scroll area", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(
      <ImageCropDialog
        file={new File(["image"], "logo.png", { type: "image/png" })}
        sourceUrl="blob:logo-preview"
        onApply={vi.fn()}
        onCancel={onCancel}
      />,
    );

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveClass(
      "max-h-[calc(100dvh-1rem)]",
      "overflow-y-auto",
      "overscroll-contain",
    );
    const workspace = Array.from(dialog.querySelectorAll("div")).find((node) =>
      node.classList.contains("max-h-[52dvh]"),
    );
    expect(workspace).toHaveClass(
      "min-h-[min(18rem,40dvh)]",
      "overflow-auto",
    );

    await user.click(screen.getByRole("button", { name: "취소" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
