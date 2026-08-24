import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import LoadingView from "@/components/LoadingView";

describe("LoadingView", () => {
  afterEach(() => vi.useRealTimers());

  it("describes a visual candidate state instead of legal risk", () => {
    vi.useFakeTimers();
    render(<LoadingView queryPreview={null} onCancel={vi.fn()} />);

    act(() => vi.advanceTimersByTime(3_600));

    expect(
      screen.getByText("유사도와 시각 후보 상태를 계산하고 있어요"),
    ).toBeVisible();
    expect(screen.queryByText(/위험 단계/)).not.toBeInTheDocument();
  });
});
