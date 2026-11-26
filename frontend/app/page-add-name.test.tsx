import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Home from "@/app/page";

// 로고만 넣은 결과의 "이름 넣고 다시 확인하기"(API 계약 v2 §4-9) — 입력 화면으로 돌아갈 때 이름 칸에
// 채울 값과, 로고·업종·사용자가 고친 유형이 그대로 남는지 본다. 바로 다시 검색하지 않는다.

const searchMock = vi.hoisted(() => vi.fn());

const COFFEE = { name: "커피", nice_class: 30, similarity_codes: ["G0502"] };
const LOGO = new File(["logo"], "logo.png", { type: "image/png" });

vi.mock("@/lib/api", () => ({ searchV2: searchMock }));
vi.mock("@/lib/useObjectUrl", () => ({ useObjectUrl: () => "blob:logo" }));
vi.mock("@/components/SearchForm", () => ({
  default: ({
    onSubmit,
    initialValue,
  }: {
    onSubmit: (value: Record<string, unknown>) => void;
    initialValue?: {
      file: File | null;
      markName: string;
      goods?: { name: string }[] | null;
      typeOverride?: string | null;
      nameFromSuggestion?: boolean;
    } | null;
  }) => (
    <div>
      <input id="mark-text" aria-label="상표 이름" defaultValue={initialValue?.markName ?? ""} />
      <span data-testid="draft">
        {JSON.stringify({
          file: initialValue?.file?.name ?? null,
          goods: (initialValue?.goods ?? []).map((good) => good.name),
          typeOverride: initialValue?.typeOverride ?? null,
          nameFromSuggestion: initialValue?.nameFromSuggestion ?? false,
        })}
      </span>
      <button
        type="button"
        onClick={() =>
          onSubmit({
            file: LOGO,
            markName: "",
            topK: 5,
            goods: [COFFEE],
            goodsCodes: ["G0502"],
            typeOverride: "도형",
            turnstileToken: "fresh-token",
          })
        }
      >
        start search
      </button>
    </div>
  ),
}));
vi.mock("@/components/ResultViewV2", () => ({
  default: ({
    onAddName,
    query,
  }: {
    onAddName: (name: string | null) => void;
    query: { name: string; logo: string | null; goods: string[] } | null;
  }) => (
    <div>
      <span data-testid="query">{JSON.stringify(query)}</span>
      <button type="button" onClick={() => onAddName("STARBUCKS")}>
        add read name
      </button>
      <button type="button" onClick={() => onAddName(null)}>
        add name
      </button>
    </div>
  ),
}));

function resultWith(source: "ocr" | "user", type: string) {
  return { overall: { query_type: { type, source, detail: null, suggested_name: null } } };
}

const draft = () => JSON.parse(screen.getByTestId("draft").textContent ?? "{}");

describe("Home — 로고만 넣은 결과에서 이름을 넣으러 돌아가기", () => {
  beforeEach(() => searchMock.mockReset());

  it("결과 화면에 입력 상태(이름·로고·업종 이름)를 넘긴다", async () => {
    searchMock.mockResolvedValueOnce(resultWith("ocr", "도형"));
    const user = userEvent.setup();
    render(<Home />);
    await user.click(screen.getByRole("button", { name: "start search" }));
    expect(JSON.parse((await screen.findByTestId("query")).textContent ?? "")).toEqual({
      name: "",
      logo: "blob:logo",
      goods: ["커피"],
    });
  });

  it("A형 — 이름 칸에 읽은 글자 전체를 채우고 포커스, 로고·업종은 그대로, 다시 검색하지 않는다", async () => {
    searchMock.mockResolvedValueOnce(resultWith("ocr", "결합-도형요부"));
    const user = userEvent.setup();
    render(<Home />);
    await user.click(screen.getByRole("button", { name: "start search" }));
    await user.click(await screen.findByRole("button", { name: "add read name" }));

    const input = screen.getByRole("textbox", { name: "상표 이름" }) as HTMLInputElement;
    expect(input.value).toBe("STARBUCKS");
    await vi.waitFor(() => expect(input).toHaveFocus());
    expect(draft()).toEqual({
      file: "logo.png",
      goods: ["커피"],
      typeOverride: null, // 자동으로 정한 유형이면 고친 유형이 없다
      nameFromSuggestion: true,
    });
    expect(searchMock).toHaveBeenCalledTimes(1);
  });

  it("B형 — 이름 칸은 비운 채 포커스만, 사용자가 고친 유형은 유지한다", async () => {
    searchMock.mockResolvedValueOnce(resultWith("user", "도형"));
    const user = userEvent.setup();
    render(<Home />);
    await user.click(screen.getByRole("button", { name: "start search" }));
    await user.click(await screen.findByRole("button", { name: "add name" }));

    const input = screen.getByRole("textbox", { name: "상표 이름" }) as HTMLInputElement;
    expect(input.value).toBe("");
    await vi.waitFor(() => expect(input).toHaveFocus());
    expect(draft()).toEqual({
      file: "logo.png",
      goods: ["커피"],
      typeOverride: "도형",
      nameFromSuggestion: false,
    });
    expect(searchMock).toHaveBeenCalledTimes(1);
  });

  it("고친 유형이 결합이면 '결합'으로 유지한다(응답의 결합-…요부 표기를 되돌린다)", async () => {
    searchMock.mockResolvedValueOnce(resultWith("user", "결합-문자요부"));
    const user = userEvent.setup();
    render(<Home />);
    await user.click(screen.getByRole("button", { name: "start search" }));
    await user.click(await screen.findByRole("button", { name: "add name" }));
    expect(draft().typeOverride).toBe("결합");
  });
});
