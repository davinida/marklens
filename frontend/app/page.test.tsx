import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Home from "@/app/page";
import type { NameCheckResult } from "@/lib/contracts";

const searchMock = vi.hoisted(() => vi.fn());

const NAME_CHECK: NameCheckResult = {
  available: false,
  normalizedName: "BBQ",
  similarCount: 2,
  exactCount: 1,
  exactRegisteredCount: 1,
  exactTitleCount: 2,
  candidates: [],
  candidatesReturned: 0,
  candidatesTruncated: false,
  statusCounts: { "등록": 2 },
  message: "동일 명칭이 있어요.",
  complete: true,
  scannedCount: 2,
  totalFound: 2,
  checkedAt: "2026-08-14T00:00:00Z",
  source: "KIPRIS fixture",
};

vi.mock("@/lib/api", () => ({ searchTrademark: searchMock }));
vi.mock("@/components/SearchForm", () => ({
  default: ({
    onSubmit,
    initialValue,
  }: {
    onSubmit: (value: {
      file: File;
      markName: string;
      topK: number;
      nameCheck?: NameCheckResult | null;
      turnstileToken: string;
    }) => void;
    initialValue?: { file: File } | null;
  }) => (
    <div>
      <span>{initialValue ? "draft restored" : "new draft"}</span>
      <button
        type="button"
        onClick={() =>
          onSubmit({
            file: new File(["logo"], "logo.png", { type: "image/png" }),
            markName: "MarkLens",
            topK: 5,
            nameCheck: NAME_CHECK,
            turnstileToken: "fresh-token",
          })
        }
      >
        start search
      </button>
    </div>
  ),
}));
vi.mock("@/components/LoadingView", () => ({
  default: ({ onCancel }: { onCancel: () => void }) => (
    <button type="button" onClick={onCancel}>
      cancel search
    </button>
  ),
}));
vi.mock("@/components/ResultView", () => ({
  default: ({ nameCheck }: { nameCheck?: NameCheckResult | null }) => (
    <div>
      search result
      {nameCheck && <span>name evidence {nameCheck.normalizedName}</span>}
    </div>
  ),
}));
vi.mock("@/components/ErrorView", () => ({
  default: () => <div>search error</div>,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("Home request lifecycle", () => {
  it("aborts an in-flight request and ignores its late response", async () => {
    const first = deferred<unknown>();
    searchMock.mockReturnValueOnce(first.promise);
    const user = userEvent.setup();
    render(<Home />);

    expect(screen.getByText("연구 베타 · 시각 비교")).toBeVisible();
    expect(
      screen.getByText("MarkLens · 선행 시각 후보 비교를 위한 연구 도구"),
    ).toBeVisible();

    await user.click(screen.getByRole("button", { name: "start search" }));
    const firstSignal = searchMock.mock.calls[0][3] as AbortSignal;
    expect(firstSignal.aborted).toBe(false);

    await user.click(screen.getByRole("button", { name: "cancel search" }));
    expect(firstSignal.aborted).toBe(true);
    expect(screen.getByText("draft restored")).toBeVisible();

    await act(async () => first.resolve({ stale: true }));
    expect(screen.queryByText("search result")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "start search" })).toBeVisible();
  });

  it("preserves the latest name check in the image result dashboard", async () => {
    searchMock.mockResolvedValueOnce({ result: true });
    const user = userEvent.setup();
    render(<Home />);

    await user.click(screen.getByRole("button", { name: "start search" }));

    expect(await screen.findByText("name evidence BBQ")).toBeVisible();
  });
});
