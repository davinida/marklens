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

const COFFEE = { name: "커피", nice_class: 30, similarity_codes: ["G0502"], matched_alias: null };

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("SearchForm goods picker", () => {
  it("keeps the selected goods after a name check and restores them from a draft", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.startsWith("/api/goods/search")) {
          return Promise.resolve(
            jsonResponse({ query: "커피", matches: [COFFEE], total: 1, offset: 0 }),
          );
        }
        if (url === "/api/name-check") {
          return Promise.resolve(
            jsonResponse({
              available: true,
              normalized_name: "MARKLENS",
              similar_count: 0,
              exact_count: 0,
              exact_title_count: 0,
              candidates: [],
              candidates_returned: 0,
              candidates_truncated: false,
              status_counts: {},
              message: "같은 이름을 찾지 못했어요.",
              complete: true,
              scanned_count: 0,
              total_found: 0,
              source: "KIPRIS test fixture",
            }),
          );
        }
        return Promise.resolve(jsonResponse({ detail: "not mocked" }, 503));
      }),
    );
    const user = userEvent.setup();
    render(<SearchForm onSubmit={vi.fn()} />);

    await user.type(screen.getByRole("combobox", { name: "지정상품 검색" }), "커피");
    await user.click(await screen.findByRole("option", { name: /^커피 제30류/ }));
    expect(screen.getByRole("button", { name: "커피 제거" })).toBeVisible();
    expect(screen.getByText("선택 1개")).toBeVisible();

    await user.type(screen.getByRole("textbox", { name: "상표 이름" }), "MarkLens");
    const checkButton = screen.getByRole("button", { name: "이름 확인" });
    await waitFor(() => expect(checkButton).toBeEnabled());
    await user.click(checkButton);
    expect(await screen.findByText("같은 이름을 찾지 못했어요.")).toBeVisible();
    // 이름 확인(발음·관념 검색 포함)을 거쳐도 지정상품 선택은 그대로
    expect(screen.getByRole("button", { name: "커피 제거" })).toBeVisible();

    // 결과 화면에서 "수정"으로 돌아오면 draft 에서 복원된다
    render(
      <SearchForm
        onSubmit={vi.fn()}
        initialValue={{
          file: new File(["logo"], "logo.png", { type: "image/png" }),
          markName: "",
          topK: 5,
          goods: [{ name: "커피전문점업", nice_class: 43, similarity_codes: ["S120602"] }],
        }}
      />,
    );
    expect(screen.getByRole("button", { name: "커피전문점업 제거" })).toBeVisible();
  });
});

describe("SearchForm name check", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));

  it("posts the name and presents partial coverage", async () => {
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

    const nameInput = screen.getByRole("textbox", { name: "상표 이름" });
    // Safari 연락처 자동완성 아이콘 방지: autocomplete=off, id 에 'name' 없음
    expect(nameInput).toHaveAttribute("autocomplete", "off");
    expect(nameInput.id).not.toMatch(/name/i);
    await user.type(nameInput, "MarkLens");
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
