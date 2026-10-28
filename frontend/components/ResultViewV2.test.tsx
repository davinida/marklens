import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ResultViewV2 from "@/components/ResultViewV2";
import { SearchV2ResponseSchema } from "@/lib/contracts";
import {
  SEARCH_V2_EMPTY_FIXTURE,
  SEARCH_V2_FIGURE_FIXTURE,
  SEARCH_V2_TEXT_FIXTURE,
} from "@/lib/searchV2Fixtures";

describe("API 계약 v2 §3 픽스처", () => {
  it("문자상표 예시(§3-1)가 zod 스키마를 통과한다", () => {
    expect(SearchV2ResponseSchema.safeParse(SEARCH_V2_TEXT_FIXTURE).success).toBe(true);
  });

  it("도형상표 예시(§3-2)가 zod 스키마를 통과한다", () => {
    expect(SearchV2ResponseSchema.safeParse(SEARCH_V2_FIGURE_FIXTURE).success).toBe(true);
  });

  it("후보 0건 예시(§5-4)가 zod 스키마를 통과한다", () => {
    expect(SearchV2ResponseSchema.safeParse(SEARCH_V2_EMPTY_FIXTURE).success).toBe(true);
  });
});

describe("ResultViewV2 — 문자상표(§3-1)", () => {
  it("등급 배지·정밀도 문구·주의 문구를 보여준다", () => {
    render(
      <ResultViewV2
        result={SEARCH_V2_TEXT_FIXTURE}
        queryPreview={null}
        queryHasName
        onReset={vi.fn()}
      />,
    );

    expect(screen.getByTestId("overall-grade")).toHaveTextContent("위험");
    expect(screen.getByTestId("overall-prob")).toHaveTextContent("위험도 60%"); // 0.604
    expect(
      screen.getByText(/'위험'으로 분류된 상표 쌍은 검증 데이터 기준 10건 중 7건/),
    ).toBeVisible();
    // 후보 카드: "위험" 등급(후보 1)에만 정밀도 문구, 검토 권장 후보(2~4)에는 없음
    expect(screen.getAllByText("검증 데이터 기준 10건 중 7건")).toHaveLength(1);
    expect(
      screen.getByText("이미지가 없어 외관(이미지) 축은 비교하지 않았습니다"),
    ).toBeVisible();
    expect(screen.getAllByText("BLUE CAFE 블루카페").length).toBeGreaterThan(0);
  });

  it("후보 카드를 펼치면 요부 제외 문장(§4-2)을 보여준다", async () => {
    const user = userEvent.setup();
    render(
      <ResultViewV2
        result={SEARCH_V2_TEXT_FIXTURE}
        queryPreview={null}
        queryHasName
        onReset={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /BLUE CAFE 블루카페/ }));

    expect(screen.getByText("'커피'는 흔한 말이라 제외, '블루'로 비교")).toBeVisible();
    expect(
      screen.getByText("'blue·cafe'는 흔한 말이라 제외, '블루카페'로 비교"),
    ).toBeVisible();
  });

  it("제외 사유 원문을 툴팁과 '자세히' 토글로 그대로 보여준다", async () => {
    const user = userEvent.setup();
    render(
      <ResultViewV2
        result={SEARCH_V2_TEXT_FIXTURE}
        queryPreview={null}
        queryHasName
        onReset={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /BLUE CAFE 블루카페/ }));

    expect(screen.getByText("'커피'는 흔한 말이라 제외, '블루'로 비교")).toHaveAttribute(
      "title",
      expect.stringContaining("커피: 1호 보통명칭·3호 기술적 표장:원재료(류 30,35,43)"),
    );
    expect(screen.getByText("제외 사유 자세히")).toBeVisible();
    expect(
      screen.getByText("'커피'(입력) — 1호 보통명칭·3호 기술적 표장:원재료(류 30,35,43)"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("'blue'(후보) — 일반어(zipf 5.1)·다수 등록(A=53, N=54)"),
    ).toBeInTheDocument();
  });

  it("'both' 제외 토큰은 한 문장으로 합친다", async () => {
    const user = userEvent.setup();
    render(
      <ResultViewV2
        result={SEARCH_V2_TEXT_FIXTURE}
        queryPreview={null}
        queryHasName
        onReset={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /레드커피/ }));
    expect(screen.getByText("'커피'는 흔한 말이라 제외, '블루'로 비교")).toBeVisible();
  });

  it("'유형 고치기' 버튼이 눌리면 onRetypeTo 를 호출한다", async () => {
    const user = userEvent.setup();
    const onRetypeTo = vi.fn();
    render(
      <ResultViewV2
        result={SEARCH_V2_TEXT_FIXTURE}
        queryPreview={null}
        queryHasName
        onReset={vi.fn()}
        onRetypeTo={onRetypeTo}
      />,
    );

    await user.click(screen.getByRole("button", { name: "도형로 고치기" }));
    expect(onRetypeTo).toHaveBeenCalledWith("도형");
  });
});

describe("ResultViewV2 — 도형상표(§3-2)", () => {
  it("도형 참고 배지·시각 상태·단독 규칙 문구를 보여준다", async () => {
    const user = userEvent.setup();
    render(
      <ResultViewV2
        result={SEARCH_V2_FIGURE_FIXTURE}
        queryPreview={null}
        queryHasName={false}
        onReset={vi.fn()}
      />,
    );

    expect(screen.getByText("도형 유사는 검증 데이터가 적어 참고용")).toBeVisible();
    // v1 결과 화면과 같은 4상태 문구(코드가 아니라)
    expect(screen.getByText(/시각 유사 상태: 매우 닮은 등록상표가 있어요/)).toBeVisible();
    expect(screen.queryByText(/STRONG_MATCH/)).toBeNull();
    expect(screen.getByTestId("overall-prob")).toHaveTextContent("위험도 6%"); // 0.06

    await user.click(
      screen.getAllByRole("button", { name: /이름 미등록 상표/ })[0],
    );
    expect(
      screen.getByText("도형이 매우 비슷해 검토 권장으로 올렸습니다(검증 데이터 부족, 참고용)"),
    ).toBeVisible();
  });

  it("null 축은 '정보 없음'으로 표시한다", () => {
    render(
      <ResultViewV2
        result={SEARCH_V2_FIGURE_FIXTURE}
        queryPreview={null}
        queryHasName={false}
        onReset={vi.fn()}
      />,
    );
    expect(screen.getAllByText("호칭 정보 없음").length).toBeGreaterThan(0);
  });
});

describe("ResultViewV2 — 후보 0건(§5-4)", () => {
  it("등급 배지 대신 안내 문구를 보여준다", () => {
    render(
      <ResultViewV2
        result={SEARCH_V2_EMPTY_FIXTURE}
        queryPreview={null}
        queryHasName
        onReset={vi.fn()}
      />,
    );
    expect(screen.getAllByText("비교할 후보가 없습니다").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("overall-prob")).toBeNull(); // prob null → 숫자 없음
  });
});

describe("ResultViewV2 — 이미지에서 글자 제안(NAME_SUGGESTED)", () => {
  it("'상표명으로 넣기' 버튼이 onUseSuggestedName 을 호출한다", async () => {
    const user = userEvent.setup();
    const onUseSuggestedName = vi.fn();
    const fixtureWithSuggestion = {
      ...SEARCH_V2_FIGURE_FIXTURE,
      overall: {
        ...SEARCH_V2_FIGURE_FIXTURE.overall,
        query_type: {
          ...SEARCH_V2_FIGURE_FIXTURE.overall.query_type,
          suggested_name: "블루커피",
        },
      },
    };

    render(
      <ResultViewV2
        result={fixtureWithSuggestion}
        queryPreview={null}
        queryHasName={false}
        onReset={vi.fn()}
        onUseSuggestedName={onUseSuggestedName}
      />,
    );

    await user.click(screen.getByRole("button", { name: /상표명으로 넣기/ }));
    expect(onUseSuggestedName).toHaveBeenCalledWith("블루커피");
  });
});
