import { forwardRef, useEffect, useImperativeHandle } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SearchForm from "@/components/SearchForm";

vi.mock("@/components/TurnstileWidget", () => ({
  default: forwardRef<
    { reset: () => void },
    { onTokenChange: (token: string | null) => void }
  >(function MockTurnstile({ onTokenChange }, ref) {
    useImperativeHandle(ref, () => ({
      reset: () => onTokenChange("test-token"),
    }));
    useEffect(() => onTokenChange("test-token"), [onTokenChange]);
    return <div>자동 요청 확인 완료</div>;
  }),
}));

describe("SearchForm name check", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));

  it("posts the name and presents partial coverage without a goods field", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          available: false,
          normalized_name: "MARKLENS",
          similar_count: 2,
          exact_count: 1,
          exact_title_count: 2,
          candidates: [
            {
              application_number: "4020260012345",
              registration_number: "4012345670000",
              title: "MARKLENS",
              status: "등록",
              applicant: "테스트 출원인",
              right_holder: "테스트 권리자",
              nice_classes: ["43"],
              vienna_codes: ["27.05.01"],
              similarity_codes: ["S1201"],
              exact_title_match: true,
              is_registered: true,
              local_image_url: "/images/marklens.png",
            },
          ],
          candidates_returned: 1,
          candidates_truncated: false,
          status_counts: { "등록": 2, "소멸": 1 },
          message: "동일하거나 유사한 이름이 있어요.",
          complete: false,
          scanned_count: 25,
          total_found: 100,
          source: "KIPRIS test fixture",
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    const user = userEvent.setup();
    render(<SearchForm onSubmit={vi.fn()} />);

    expect(screen.queryByLabelText(/상품/)).not.toBeInTheDocument();
    await user.type(
      screen.getByRole("textbox", { name: "상표 이름" }),
      "MarkLens",
    );
    const checkButton = screen.getByRole("button", { name: "이름 확인" });
    await waitFor(() => expect(checkButton).toBeEnabled());
    await user.click(checkButton);

    expect(await screen.findByText("동일하거나 유사한 이름이 있어요.")).toBeVisible();
    expect(
      screen.getByText("동일 명칭의 등록상표를 최소 1건 확인했어요"),
    ).toBeVisible();
    expect(screen.getByText("25/100건 확인")).toBeVisible();
    expect(screen.getByText("동일 명칭 등록")).toBeVisible();
    expect(screen.getByText("동일 명칭 전체")).toBeVisible();
    expect(screen.getByRole("progressbar", { name: "명칭 검색 범위" })).toHaveAttribute(
      "aria-valuenow",
      "25",
    );

    await user.click(screen.getByRole("button", { name: /MARKLENS/ }));
    expect(screen.getByText("4020260012345")).toBeVisible();
    expect(screen.getByText("테스트 권리자")).toBeVisible();

    expect(fetch).toHaveBeenCalledWith(
      "/api/name-check",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        body: JSON.stringify({ name: "MarkLens", turnstileToken: "test-token" }),
      }),
    );
  });
});
