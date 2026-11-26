import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ResultViewV2, {
  gradeDescription,
  retypeLabel,
  ruleTriggerLines,
} from "@/components/ResultViewV2";
import { SearchV2ResponseSchema, type SearchV2Grade, type SearchV2Response } from "@/lib/contracts";
import descriptiveFixture from "@/test/fixtures/search-v2-descriptive.json";
import famousFixture from "@/test/fixtures/search-v2-famous.json";
import imageFixture from "@/test/fixtures/search-v2-image.json";
import textFixture from "@/test/fixtures/search-v2-text.json";

// 결과 화면의 문구(API 계약 v2 §4-1·§4-4) — 규칙 사유는 카드의 최종 등급이 무엇이든 참이어야 하고,
// 등급 설명은 축 수를 말하지 않으며, 프런트가 만든 문장은 해요체다.
const GRADES: SearchV2Grade[] = ["안전", "주의", "검토 권장", "위험"];
const rank = (grade: SearchV2Grade) => GRADES.indexOf(grade);

// 엔진이 응답에 실을 수 있는 규칙 코드(backend/src/core/multi_search.py) — [코드, 하한·상한, 문장이
// 말하는 등급(없으면 null), 문구]
const RULES: Array<[string, "하한" | "상한", SearchV2Grade | null, string]> = [
  ["standalone_x1", "하한", "검토 권장", "발음이 거의 같아서 검토 권장 이상으로 봤어요"],
  ["standalone_x2_text", "하한", "검토 권장", "철자가 매우 비슷해서 검토 권장 이상으로 봤어요"],
  ["standalone_x3", "하한", "검토 권장", "뜻이 매우 비슷해서 검토 권장 이상으로 봤어요"],
  [
    "figure_x2_img",
    "하한",
    "검토 권장",
    "도형이 매우 비슷해서 검토 권장 이상으로 봤어요. 도형 비교는 검증 데이터가 적어 참고용이에요",
  ],
  ["nameless_floor", "하한", null, "로고만 봤을 때의 등급이 더 높아서 그 등급 이상으로 봤어요"],
  ["goods_floor", "하한", null, "업종이 겹쳐서 로고만 봤을 때의 등급 이상으로 봤어요"],
  ["goods_floor_named", "하한", null, "업종이 겹쳐서 업종 없이 봤을 때의 등급 이상으로 봤어요"],
  ["goods_cap", "상한", null, "업종이 달라서 등급을 더 높이지 않았어요"],
];
const FALLBACK = "따로 정한 규칙이 적용됐어요";
const BANNED = ["올렸", "내렸", "여러 축", "일부 축"];
const FORMAL = /니다|십시오/;

describe("규칙 사유 — 규칙 코드 전부 × 카드 등급 넷", () => {
  it.each(RULES)("%s(%s)", (code, kind, named, text) => {
    for (const grade of GRADES) {
      const lines = ruleTriggerLines([code], grade, false);
      // 문장이 등급을 말하면 카드의 등급이 그보다 낮을 때는 보이지 않는다(어긋나지 않게)
      const hidden = named !== null && rank(grade) < rank(named);
      expect(lines).toEqual(hidden ? [] : [text]);
      for (const line of lines) {
        for (const word of BANNED) expect(line).not.toContain(word);
        expect(line).not.toMatch(FORMAL);
        expect(line).toMatch(kind === "상한" ? /더 높이지 않았어요$/ : /(어요|에요)$/);
        if (kind === "하한") expect(line).toContain("이상으로 봤어요");
        // 문장에 나온 등급은 카드의 등급보다 높지 않다
        for (const mentioned of GRADES.filter((item) => line.includes(item))) {
          expect(rank(mentioned)).toBeLessThanOrEqual(rank(grade));
        }
      }
    }
  });

  it("문구가 없는 코드는 코드를 그대로 보이지 않는다 — 같은 문장은 한 번만", () => {
    for (const grade of GRADES) {
      expect(ruleTriggerLines(["standalone_x2_img"], grade, false)).toEqual([FALLBACK]);
      expect(ruleTriggerLines(["future_rule", "another_rule"], grade, false)).toEqual([FALLBACK]);
    }
  });

  it("같은 카드에 '업종 다름' 표시가 있으면 업종 상한 줄은 숨긴다", () => {
    for (const grade of GRADES) {
      expect(ruleTriggerLines(["goods_cap"], grade, true)).toEqual([]);
      expect(ruleTriggerLines(["standalone_x1", "goods_cap"], "검토 권장", true)).toEqual([
        RULES[0][3],
      ]);
      expect(ruleTriggerLines(["standalone_x1", "goods_cap"], "검토 권장", false)).toEqual([
        RULES[0][3],
        RULES[7][3],
      ]);
    }
  });
});

describe("등급 한 줄 설명 — 로고만 여부 둘 × 등급 넷", () => {
  it.each([
    ["위험", "많이 닮은 선행 상표가 있어요", "로고가 많이 닮은 선행 상표가 있어요"],
    [
      "검토 권장",
      "닮은 선행 상표가 있을 수 있어요. 전문가 검토를 권해요",
      "로고가 닮은 선행 상표가 있을 수 있어요. 전문가 검토를 권해요",
    ],
    ["주의", "조금 닮은 상표가 있어요", "로고가 조금 닮은 상표가 있어요"],
    [
      "안전",
      "비교한 상표 가운데 가까운 것을 찾지 못했어요. 안전하다는 뜻은 아니에요",
      "로고가 가까운 상표를 찾지 못했어요. 안전하다는 뜻은 아니에요",
    ],
  ] as const)("%s", (grade, plain, logoOnly) => {
    expect(gradeDescription(grade, false)).toBe(plain);
    expect(gradeDescription(grade, true)).toBe(logoOnly);
    for (const line of [plain, logoOnly]) {
      expect(line).not.toContain("축");
      expect(line).not.toMatch(FORMAL);
    }
  });

  it("로고만 넣은 검색 = 이름이 없고 이미지가 있는 질의 — 이름이 있으면 로고가 있어도 앞쪽 문구", () => {
    const image = SearchV2ResponseSchema.parse(imageFixture); // 이미지만, 전체 위험
    const view = render(
      <ResultViewV2 result={image} queryPreview={null} queryHasName={false} onReset={vi.fn()} />,
    );
    expect(screen.getByText("로고가 많이 닮은 선행 상표가 있어요")).toBeVisible();
    view.unmount();
    render(<ResultViewV2 result={image} queryPreview={null} queryHasName onReset={vi.fn()} />);
    expect(screen.getByText("많이 닮은 선행 상표가 있어요")).toBeVisible();
    expect(screen.queryByText("로고가 많이 닮은 선행 상표가 있어요")).toBeNull();
  });

  it("이름도 이미지도 없는 질의(지정상품만)는 앞쪽 문구", () => {
    const text = SearchV2ResponseSchema.parse(textFixture); // 이미지 없음(visual_status null)
    render(<ResultViewV2 result={text} queryPreview={null} queryHasName={false} onReset={vi.fn()} />);
    expect(screen.getByText(gradeDescription(text.overall.grade!, false))).toBeVisible();
  });
});

describe("유형 고치기 버튼의 조사", () => {
  it("문자로 / 도형으로 / 결합으로 고치기", () => {
    expect(["문자", "도형", "결합"].map(retypeLabel)).toEqual([
      "문자로 고치기",
      "도형으로 고치기",
      "결합으로 고치기",
    ]);
  });
});

describe("정밀도 문장 — 모델이 낸 '위험'에만", () => {
  const SENTENCE = /'위험'으로 나온 상표 쌍은 검증 데이터 기준 10건 중 \d+건이 심결에서 유사로 판단됐어요/;

  function risky(famousFloor: boolean): SearchV2Response {
    const result = SearchV2ResponseSchema.parse(textFixture);
    result.overall = { ...result.overall, grade: "위험", famous_floor: famousFloor };
    return result;
  }

  it("모델이 낸 '위험'에서는 보인다", () => {
    render(<ResultViewV2 result={risky(false)} queryPreview={null} queryHasName onReset={vi.fn()} />);
    expect(screen.getByText(SENTENCE)).toBeVisible();
  });

  it("유명 상표 확인이 올린 전체 등급에서는 보이지 않는다", () => {
    render(<ResultViewV2 result={risky(true)} queryPreview={null} queryHasName onReset={vi.fn()} />);
    expect(screen.queryByText(SENTENCE)).toBeNull();
    // 계약 픽스처(스타벅스 + 의류 — 유명 상표 바닥이 전체 등급을 정함)도 같다
    const famous = SearchV2ResponseSchema.parse(famousFixture);
    expect(famous.overall.famous_floor).toBe(true);
  });
});

describe("계약 픽스처 전부로 그린 결과 화면 — 프런트가 만든 문장", () => {
  const FIXTURES: Array<[string, unknown, boolean]> = [
    ["text", textFixture, true],
    ["image", imageFixture, false],
    ["famous", famousFixture, true],
    ["descriptive", descriptiveFixture, true],
  ];

  /** 서버가 보낸 글(주의 문구·상표명·출원인·데이터 설명 등)을 뺀 화면 글자. */
  function frontendText(container: HTMLElement, result: SearchV2Response): string {
    const server = new Set<string>([
      ...result.overall.caveats,
      result.dataset_info.데이터_기준,
      result.dataset_info.출원일자_범위,
    ]);
    const all = [...result.candidates, ...(result.cross_goods_more?.candidates ?? [])];
    for (const candidate of all) {
      for (const value of [candidate.title, candidate.applicant]) if (value) server.add(value);
      for (const item of candidate.salient.removed) server.add(item.reason);
    }
    let text = container.textContent ?? "";
    for (const value of [...server].sort((a, b) => b.length - a.length)) {
      text = text.split(value).join(" ");
    }
    return text;
  }

  it.each(FIXTURES)("%s: 올렸·내렸·여러 축·일부 축·합니다체가 없다", (_name, fixture, hasName) => {
    const result = SearchV2ResponseSchema.parse(fixture);
    const { container } = render(
      <ResultViewV2 result={result} queryPreview={null} queryHasName={hasName} onReset={vi.fn()} />,
    );
    // 접힌 것을 모두 편다(후보 카드·접힌 칸·제외 사유·안내의 자세히)
    for (let pass = 0; pass < 3; pass += 1) {
      for (const button of container.querySelectorAll('button[aria-expanded="false"]')) {
        fireEvent.click(button);
      }
    }
    for (const details of container.querySelectorAll("details")) details.open = true;
    const text = frontendText(container, result);
    for (const word of BANNED) expect(text).not.toContain(word);
    expect(text).not.toMatch(FORMAL);
  });

  it("사유 문장에 나온 등급이 그 카드의 등급보다 높은 카드는 없다(숨긴 문장 0)", () => {
    let hidden = 0;
    let cards = 0;
    for (const [, fixture] of FIXTURES) {
      const result = SearchV2ResponseSchema.parse(fixture);
      for (const candidate of [
        ...result.candidates,
        ...(result.cross_goods_more?.candidates ?? []),
      ]) {
        cards += 1;
        const { rule_triggers: triggers, grade } = candidate.risk;
        const lines = ruleTriggerLines(triggers, grade, false);
        for (const line of lines) {
          for (const mentioned of GRADES.filter((item) => line.includes(item))) {
            expect(rank(mentioned)).toBeLessThanOrEqual(rank(grade));
          }
        }
        // 등급을 말하는 하한 규칙인데 카드의 등급이 낮아 숨긴 것
        hidden += triggers.filter(
          (trigger) =>
            RULES.some(([code, , named]) => code === trigger && named !== null && rank(grade) < rank(named)),
        ).length;
      }
    }
    expect(cards).toBeGreaterThan(10);
    expect(hidden).toBe(0);
  });
});
