import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ResultViewV2, { toPercent } from "@/components/ResultViewV2";
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

describe("ResultViewV2 — % 표시는 내림(v1 결과 화면 시험에서 옮김)", () => {
  it("기준 바로 아래 값이 기준을 넘은 것처럼 보이지 않는다", () => {
    // 시각 상태 0.75·0.55·0.45, 도형 규칙 0.9, 단독 x1 0.98
    expect(toPercent(0.7499)).toBe(74);
    expect(toPercent(0.75)).toBe(75);
    expect(toPercent(0.5499)).toBe(54);
    expect(toPercent(0.55)).toBe(55);
    expect(toPercent(0.4499)).toBe(44);
    expect(toPercent(0.8999)).toBe(89);
    expect(toPercent(0.9799)).toBe(97);
    expect(toPercent(0.98)).toBe(98);
  });

  it("이진 표현 오차로 한 칸 내려가지 않고 0–1 밖은 자른다", () => {
    expect(toPercent(0.57)).toBe(57); // 0.57 * 100 = 56.99…
    expect(toPercent(0.29)).toBe(29); // 0.29 * 100 = 28.99…
    expect(toPercent(1)).toBe(100);
    expect(toPercent(1.2)).toBe(100);
    expect(toPercent(-0.1)).toBe(0);
  });

  it("화면의 이미지 유사도·위험도도 내린 값으로 보인다", async () => {
    const user = userEvent.setup();
    const figure = structuredClone(SEARCH_V2_FIGURE_FIXTURE);
    figure.candidates[0].axes.x2_img = 0.8999;
    const { unmount } = render(
      <ResultViewV2 result={figure} queryPreview={null} queryHasName={false} onReset={vi.fn()} />,
    );
    await user.click(screen.getAllByRole("button", { name: /이름 미등록 상표/ })[0]);
    expect(screen.getAllByText("이미지 89%").length).toBeGreaterThan(0);
    expect(screen.queryByText("이미지 90%")).toBeNull();
    unmount();

    render(
      <ResultViewV2
        result={{ ...SEARCH_V2_TEXT_FIXTURE, overall: { ...SEARCH_V2_TEXT_FIXTURE.overall, prob: 0.7499 } }}
        queryPreview={null}
        queryHasName
        onReset={vi.fn()}
      />,
    );
    expect(screen.getByTestId("overall-prob")).toHaveTextContent("위험도 74%");
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
      screen.getByText(/'위험'으로 나온 상표 쌍은 검증 데이터 기준 10건 중 7건이 심결에서 유사로 판단됐어요/),
    ).toBeVisible();
    // 후보 카드: "위험" 등급(후보 1)에만 정밀도 문구, 검토 권장 후보(2~4)에는 없음
    expect(screen.getAllByText("검증 데이터 기준 10건 중 7건")).toHaveLength(1);
    expect(
      screen.getByText("이미지가 없어 외관(이미지) 축은 비교하지 않았어요"),
    ).toBeVisible();
    expect(screen.getAllByText("BLUE CAFE 블루카페").length).toBeGreaterThan(0);
    // 이름 있는 판단: 등급 눈금에 위험도 위치 표식, 이름 없는 질의 안내는 없음
    expect(screen.getByTestId("grade-scale-marker")).toBeInTheDocument();
    expect(screen.queryByTestId("nameless-guidance")).toBeNull();
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

    await user.click(screen.getByRole("button", { name: "도형으로 고치기" }));
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

    const figureText = "로고 파일끼리 비교한 결과예요. 도형 유사는 검증 데이터가 적어 참고용이에요";
    expect(screen.getByText(figureText)).toBeVisible();
    // v1 결과 화면과 같은 4상태 문구(코드가 아니라)
    expect(screen.getByText(/시각 유사 상태: 매우 닮은 등록상표가 있어요/)).toBeVisible();
    expect(screen.queryByText(/STRONG_MATCH/)).toBeNull();
    // 전체 등급이 이름 없는 판단(noname:x2_whole)에서 나왔다 → 위험도 %·정밀도 문구를 숨긴다(§4-3·§4-4)
    expect(screen.getByTestId("overall-grade")).toHaveTextContent("위험");
    expect(screen.queryByTestId("overall-prob")).toBeNull();
    expect(screen.queryByText(/검증 데이터 기준 10건 중/)).toBeNull();
    expect(screen.getByTestId("nameless-guidance")).toHaveTextContent(
      "상표명·업종을 넣으면 더 정확하게 판단해요",
    );
    // 등급 눈금은 이름 없는 하한으로, 위험도 위치 표식 없음
    const scale = screen.getAllByTestId("grade-scale")[0];
    expect(scale.querySelectorAll("[data-grade]")).toHaveLength(4);
    expect(screen.queryByTestId("grade-scale-marker")).toBeNull();

    await user.click(
      screen.getAllByRole("button", { name: /이름 미등록 상표/ })[0],
    );
    expect(
      screen.getByText("도형이 매우 비슷해서 검토 권장 이상으로 봤어요. 도형 비교는 검증 데이터가 적어 참고용이에요"),
    ).toBeVisible();
    expect(screen.getByTestId("nameless-judgment")).toHaveTextContent(
      "이름 없이 로고만으로 본 판단이라 위험도 %는 보이지 않아요",
    );
    expect(screen.getAllByText(figureText)).toHaveLength(2); // 전체 caveat + 펼친 카드
    expect(screen.getAllByText("이미지 93%").length).toBeGreaterThan(0); // 이미지 유사도는 보인다
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
    expect(screen.getAllByText(/^비교할 후보가 없어요\.?$/).length).toBeGreaterThan(0);
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


describe("ResultViewV2 — 이름 있는·없는 판단이 섞인 응답(v1.4, §4-4)", () => {
  const named = SEARCH_V2_TEXT_FIXTURE.candidates[0];
  const nameless = SEARCH_V2_FIGURE_FIXTURE.candidates[0];

  it("판별은 요청 상태가 아니라 pattern 으로 — 이름 있는 질의라도 전체가 이름 없는 판단이면 %를 숨긴다", () => {
    render(
      <ResultViewV2
        result={{
          ...SEARCH_V2_TEXT_FIXTURE,
          overall: { ...SEARCH_V2_TEXT_FIXTURE.overall, pattern: "noname:x2_whole" },
          candidates: [nameless, named],
        }}
        queryPreview={null}
        queryHasName
        onReset={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("overall-prob")).toBeNull();
    expect(screen.queryByTestId("nameless-guidance")).toBeNull(); // 이름을 넣은 질의
    // 이름 있는 "위험" 카드에만 정밀도 문구 — 이름 없는 "위험" 카드에는 없다
    expect(screen.getAllByText("검증 데이터 기준 10건 중 7건")).toHaveLength(1);
  });

  it("전체가 이름 있는 판단이면 이름 없는 후보가 섞여도 전체 %를 보인다", () => {
    render(
      <ResultViewV2
        result={{ ...SEARCH_V2_TEXT_FIXTURE, candidates: [named, nameless] }}
        queryPreview={null}
        queryHasName
        onReset={vi.fn()}
      />,
    );
    expect(screen.getByTestId("overall-prob")).toHaveTextContent("위험도 60%");
  });

  it("goods_floor 규칙 문구를 보여준다", async () => {
    const user = userEvent.setup();
    render(
      <ResultViewV2
        result={{
          ...SEARCH_V2_FIGURE_FIXTURE,
          candidates: [
            {
              ...nameless,
              axes: { ...nameless.axes, x4: 0.33 },
              risk: { ...nameless.risk, rule_triggers: ["figure_x2_img", "goods_floor"] },
            },
          ],
        }}
        queryPreview={null}
        queryHasName={false}
        onReset={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: /이름 미등록 상표/ }));
    expect(screen.getByText("업종이 겹쳐서 로고만 봤을 때의 등급 이상으로 봤어요")).toBeVisible();
  });

  it("goods_cap 규칙 문구를 보여준다(업종 상한, v1.4.6)", async () => {
    const user = userEvent.setup();
    render(
      <ResultViewV2
        result={{
          ...SEARCH_V2_FIGURE_FIXTURE,
          candidates: [
            {
              ...nameless,
              axes: { ...nameless.axes, x4: 0 },
              risk: { ...nameless.risk, rule_triggers: ["goods_cap"] },
            },
          ],
        }}
        queryPreview={null}
        queryHasName={false}
        onReset={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: /이름 미등록 상표/ }));
    expect(screen.getByText("업종이 달라서 등급을 더 높이지 않았어요")).toBeVisible();
    expect(screen.queryByText("goods_cap")).not.toBeInTheDocument();
  });

  it("nameless_floor 규칙 문구를 보여준다", async () => {
    const user = userEvent.setup();
    render(
      <ResultViewV2
        result={{
          ...SEARCH_V2_FIGURE_FIXTURE,
          candidates: [
            {
              ...nameless,
              title: "블루커피",
              risk: { ...nameless.risk, rule_triggers: ["figure_x2_img", "nameless_floor"] },
            },
          ],
        }}
        queryPreview={null}
        queryHasName
        onReset={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: /블루커피/ }));
    expect(
      screen.getByText("로고만 봤을 때의 등급이 더 높아서 그 등급 이상으로 봤어요"),
    ).toBeVisible();
  });
});
