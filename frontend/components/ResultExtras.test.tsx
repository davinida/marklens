import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ResultViewV2, { retypeLabel } from "@/components/ResultViewV2";
import { ApiError } from "@/lib/api";
import { SearchV2ResponseSchema, type SearchV2Response } from "@/lib/contracts";
import { josaEulReul, josaEunNeun, josaEuroRo, josaIGa, josaWaGwa } from "@/lib/josa";
import {
  LOGO_ONLY_TEXT,
  NAME_CHECK_FAILURE,
  NAME_CHECK_UNKNOWN,
  PHOTO_CAVEAT,
  QUERY_SUMMARY_TEXT,
  REFERENCE_NOTE,
  goodsSummary,
  isNameSuggestedCaveat,
  logoOnlyNoticeKind,
  logoReadLine,
  nameCheckFailureMessage,
  shorten,
  splitCaveats,
} from "@/lib/resultExtras";
import { SEARCH_V2_FIGURE_FIXTURE, SEARCH_V2_TEXT_FIXTURE } from "@/lib/searchV2Fixtures";
import descriptiveFixture from "@/test/fixtures/search-v2-descriptive.json";
import famousFixture from "@/test/fixtures/search-v2-famous.json";

// 결과 화면의 보완(API 계약 v2 §4-9) — 로고만 넣은 검색의 상표명 입력 안내, 검색 내용 한 줄, 참고용
// 안내, 사진 안내의 자리, 이름 확인 실패 안내, 조사.

const NO_NAME = "상표명이 없어 호칭·철자·관념 축은 비교하지 않았어요";
const nameSuggested = (text: string) =>
  `이미지에서 '${text}'를 읽었어요 — 상표명으로 넣으면 호칭·철자·관념도 비교해요`;

/** 로고만 넣은 검색의 응답 — 로고에서 읽은 글자·주의 문구·유명 상표를 바꿔 끼운다. */
function logoResult(
  options: {
    suggested?: string | null;
    caveats?: string[];
    famous?: SearchV2Response["famous"];
    nameWords?: SearchV2Response["name_words"];
  } = {},
): SearchV2Response {
  const suggested = options.suggested ?? null;
  return {
    ...SEARCH_V2_FIGURE_FIXTURE,
    famous: options.famous,
    name_words: options.nameWords,
    overall: {
      ...SEARCH_V2_FIGURE_FIXTURE.overall,
      caveats:
        options.caveats ?? [NO_NAME, ...(suggested ? [nameSuggested(suggested)] : [])],
      query_type: { ...SEARCH_V2_FIGURE_FIXTURE.overall.query_type, suggested_name: suggested },
    },
  };
}

function view(
  result: SearchV2Response,
  props: Partial<Parameters<typeof ResultViewV2>[0]> = {},
) {
  return render(
    <ResultViewV2
      result={result}
      queryPreview={null}
      queryHasName={false}
      onReset={vi.fn()}
      onUseSuggestedName={vi.fn()}
      onAddName={vi.fn()}
      {...props}
    />,
  );
}

/** 문서 순서 — a 가 b 보다 앞에 있는가. */
function isBefore(a: Element, b: Element): boolean {
  return Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
}

describe("로고만 넣은 검색의 상표명 입력 안내 — 뜨는 조건", () => {
  it("로고만 → B형이 보인다", () => {
    view(logoResult());
    const notice = screen.getByTestId("logo-only-notice");
    expect(notice).toHaveAttribute("data-kind", "plain");
    expect(within(notice).getByTestId("logo-only-line")).toHaveTextContent(LOGO_ONLY_TEXT.plain);
    expect(within(notice).getByRole("button")).toHaveTextContent(LOGO_ONLY_TEXT.plainButton);
  });

  it("로고 + 업종 → 보인다(업종 유무와 상관없다)", () => {
    const result = logoResult();
    view({ ...result, overall: { ...result.overall, pattern: "noname:x2_whole+x4" } });
    expect(screen.getByTestId("logo-only-notice")).toBeVisible();
  });

  it("이름만 → 안 보인다", () => {
    view(SEARCH_V2_TEXT_FIXTURE, { queryHasName: true, queryName: "블루커피" });
    expect(screen.queryByTestId("logo-only-notice")).not.toBeInTheDocument();
  });

  it("이름 + 로고, 이름 + 로고 + 업종 → 안 보인다", () => {
    const { unmount } = view(logoResult(), { queryHasName: true, queryName: "블루커피" });
    expect(screen.queryByTestId("logo-only-notice")).not.toBeInTheDocument();
    unmount();
    const result = logoResult();
    view(
      { ...result, overall: { ...result.overall, pattern: "x2_whole+x4" } },
      { queryHasName: true, queryName: "블루커피" },
    );
    expect(screen.queryByTestId("logo-only-notice")).not.toBeInTheDocument();
  });

  it("규칙 함수 — 로고만 넣은 검색이 아니면 null, 읽은 글자가 비면 B형", () => {
    expect(logoOnlyNoticeKind(false, "블루커피")).toBeNull();
    expect(logoOnlyNoticeKind(true, "블루커피")).toBe("read");
    expect(logoOnlyNoticeKind(true, null)).toBe("plain");
    expect(logoOnlyNoticeKind(true, "   ")).toBe("plain");
  });
});

describe("로고만 넣은 검색의 상표명 입력 안내 — A형과 중복 정리", () => {
  it("읽은 글자가 있으면 A형 문장·버튼이고, 버튼은 읽은 글자 전체를 넘긴다", async () => {
    const user = userEvent.setup();
    const onAddName = vi.fn();
    view(logoResult({ suggested: "STARBUCKS" }), { onAddName });
    const notice = screen.getByTestId("logo-only-notice");
    expect(notice).toHaveAttribute("data-kind", "read");
    expect(within(notice).getByTestId("logo-only-line").textContent).toBe(
      "로고에서 'STARBUCKS'를 읽었어요. 지금은 로고 모양만 비교했어요. " +
        "이름까지 넣으면 이름이 닮은 상표도 찾을 수 있어요.",
    );
    await user.click(within(notice).getByRole("button", { name: LOGO_ONLY_TEXT.readButton }));
    expect(onAddName).toHaveBeenCalledWith("STARBUCKS");
  });

  it("B형 버튼은 글자 없이 부른다", async () => {
    const user = userEvent.setup();
    const onAddName = vi.fn();
    view(logoResult(), { onAddName });
    await user.click(screen.getByRole("button", { name: LOGO_ONLY_TEXT.plainButton }));
    expect(onAddName).toHaveBeenCalledWith(null);
  });

  it("안내가 뜨면 기존 줄(읽었어요 줄·'상표명으로 넣기'·NAME_SUGGESTED 문장)은 0개, NO_NAME 은 그대로", () => {
    view(logoResult({ suggested: "블루커피" }));
    expect(screen.queryByRole("button", { name: /상표명으로 넣기/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/이미지에서 '블루커피'/)).not.toBeInTheDocument();
    expect(screen.queryByText(nameSuggested("블루커피"))).not.toBeInTheDocument();
    expect(screen.getAllByText(/블루커피/)).toHaveLength(1); // 읽은 글자는 안내 한 곳에만
    expect(screen.getByText(NO_NAME)).toBeVisible();
  });

  it("40자를 넘는 글자는 화면에서만 줄이고 전체는 title 에 — 버튼은 전체를 넘긴다", async () => {
    const user = userEvent.setup();
    const onAddName = vi.fn();
    const long = "가나다라마바사아자차".repeat(5); // 50자
    view(logoResult({ suggested: long }), { onAddName });
    const read = screen.getByTestId("logo-only-read");
    expect(read.textContent).toBe(`${long.slice(0, 40)}…`);
    expect(read).toHaveAttribute("title", long);
    await user.click(screen.getByRole("button", { name: LOGO_ONLY_TEXT.readButton }));
    expect(onAddName).toHaveBeenCalledWith(long);
  });

  it("읽은 글자의 줄바꿈은 한 줄로, 조사는 받침에 맞춘다", () => {
    expect(logoReadLine("블루\n커피")).toContain("'블루 커피'를 읽었어요.");
    expect(logoReadLine("서울")).toContain("'서울'을 읽었어요.");
    expect(logoReadLine("CAFE24")).toContain("'CAFE24'를 읽었어요.");
  });

  it("읽은 글자의 꺾쇠는 글자 그대로 보인다(요소가 되지 않는다)", () => {
    view(logoResult({ suggested: "<b>굵게</b>" }));
    const read = screen.getByTestId("logo-only-read");
    expect(read.textContent).toBe("<b>굵게</b>");
    expect(read.querySelector("b")).toBeNull();
  });
});

describe("맨 위 안내 영역의 순서 — 유명 상표 배너 → 설명적 이름 안내 → 사진 안내 → 상표명 입력 안내", () => {
  const famous = SearchV2ResponseSchema.parse(famousFixture).famous!;
  const logoFamous = {
    ...famous,
    matches: famous.matches.map((match) => ({ ...match, basis: "로고" as const })),
  };

  it("유명 상표 배너가 있으면 상표명 입력 안내는 그 아래", () => {
    view(logoResult({ suggested: "STARBUCKS", famous: logoFamous }));
    const banner = screen.getByTestId("famous-banner");
    const notice = screen.getByTestId("logo-only-notice");
    expect(isBefore(banner, notice)).toBe(true);
    expect(isBefore(notice, screen.getByTestId("overall-grade"))).toBe(true);
  });

  it("사진 안내는 배너 아래·상표명 입력 안내 위, 한 곳에만(주의 목록에는 없다)", () => {
    view(logoResult({ famous: logoFamous, caveats: [NO_NAME, PHOTO_CAVEAT] }));
    const photo = screen.getByTestId("photo-notice");
    expect(photo).toHaveTextContent(PHOTO_CAVEAT);
    expect(screen.getAllByText(PHOTO_CAVEAT)).toHaveLength(1);
    expect(isBefore(screen.getByTestId("famous-banner"), photo)).toBe(true);
    expect(isBefore(photo, screen.getByTestId("logo-only-notice"))).toBe(true);
    expect(screen.getByText(NO_NAME)).toBeVisible();
  });

  it("이름이 있는 사진 질의 — 설명적 이름 안내 아래에 사진 안내, 상표명 입력 안내는 없다", () => {
    const descriptive = SearchV2ResponseSchema.parse(descriptiveFixture);
    view(
      {
        ...descriptive,
        overall: {
          ...descriptive.overall,
          visual_status: "STRONG_MATCH",
          caveats: [...descriptive.overall.caveats, PHOTO_CAVEAT],
        },
      },
      { queryHasName: true, queryName: "맛있는 커피 전문점" },
    );
    const photo = screen.getByTestId("photo-notice");
    expect(isBefore(screen.getByTestId("descriptive-notice"), photo)).toBe(true);
    expect(screen.getAllByText(PHOTO_CAVEAT)).toHaveLength(1);
    expect(screen.queryByTestId("logo-only-notice")).not.toBeInTheDocument();
  });

  it("사진 안내가 없는 응답에는 그 칸이 없다", () => {
    view(logoResult());
    expect(screen.queryByTestId("photo-notice")).not.toBeInTheDocument();
  });

  it("주의 문구 나누기 — 글자가 같을 때만 옮기고, NAME_SUGGESTED 는 안내가 뜰 때만 뺀다", () => {
    const caveats = [NO_NAME, nameSuggested("블루커피"), PHOTO_CAVEAT];
    expect(splitCaveats(caveats, true)).toEqual({ photo: PHOTO_CAVEAT, rest: [NO_NAME] });
    expect(splitCaveats(caveats, false)).toEqual({
      photo: PHOTO_CAVEAT,
      rest: [NO_NAME, nameSuggested("블루커피")],
    });
    expect(splitCaveats([`${PHOTO_CAVEAT}.`], true)).toEqual({
      photo: null,
      rest: [`${PHOTO_CAVEAT}.`],
    });
    expect(isNameSuggestedCaveat(NO_NAME)).toBe(false);
  });
});

describe("검색 내용 한 줄", () => {
  const summary = () => screen.getByTestId("query-summary");

  it("이름만 → 이름 · 로고 없음 · 업종 선택 안 함, 전체 등급 위에", () => {
    view(SEARCH_V2_TEXT_FIXTURE, {
      queryHasName: true,
      queryName: "블루커피",
      query: { name: "블루커피", logo: null, goods: [] },
    });
    expect(within(summary()).getByTestId("query-summary-name")).toHaveTextContent("'블루커피'");
    expect(within(summary()).getByTestId("query-summary-logo")).toHaveTextContent(
      QUERY_SUMMARY_TEXT.noLogo,
    );
    expect(within(summary()).getByTestId("query-summary-goods")).toHaveTextContent(
      QUERY_SUMMARY_TEXT.noGoods,
    );
    expect(isBefore(summary(), screen.getByTestId("overall-grade"))).toBe(true);
  });

  it("로고만 → 이름 없음 · 작은 그림 · 업종 선택 안 함", () => {
    view(logoResult(), { query: { name: "", logo: "blob:logo", goods: [] } });
    expect(within(summary()).getByTestId("query-summary-name")).toHaveTextContent(
      QUERY_SUMMARY_TEXT.noName,
    );
    expect(within(summary()).getByRole("img", { name: QUERY_SUMMARY_TEXT.logoAlt })).toHaveAttribute(
      "src",
      "blob:logo",
    );
  });

  it("이름 + 로고 + 업종 6개 → 셋까지 적고 '외 3개'", () => {
    const goods = ["커피", "커피전문점업", "제과점업", "빵", "케이크", "차"];
    view(logoResult(), {
      queryHasName: true,
      queryName: "블루커피",
      query: { name: "블루커피", logo: "blob:logo", goods },
    });
    expect(within(summary()).getByTestId("query-summary-goods").textContent).toBe(
      "커피, 커피전문점업, 제과점업 외 3개",
    );
    expect(goodsSummary(goods.slice(0, 3))).toBe("커피, 커피전문점업, 제과점업");
    expect(goodsSummary(goods.slice(0, 4))).toBe("커피, 커피전문점업, 제과점업 외 1개");
    expect(goodsSummary([])).toBe(QUERY_SUMMARY_TEXT.noGoods);
  });

  it("100자 이름 → 40자로 줄이고 전체는 title", () => {
    const long = "가".repeat(100);
    view(SEARCH_V2_TEXT_FIXTURE, {
      queryHasName: true,
      queryName: long,
      query: { name: long, logo: null, goods: [] },
    });
    const name = within(summary()).getByTestId("query-summary-name");
    expect(name.textContent).toBe(`'${"가".repeat(40)}…'`);
    expect(name).toHaveAttribute("title", long);
    expect(shorten("가".repeat(40))).toBe("가".repeat(40)); // 딱 40자는 줄이지 않는다
  });

  it("'<b>굵게</b>' 는 글자 그대로 보인다", () => {
    view(SEARCH_V2_TEXT_FIXTURE, {
      queryHasName: true,
      queryName: "<b>굵게</b>",
      query: { name: "<b>굵게</b>", logo: null, goods: ["<i>업종</i>"] },
    });
    expect(within(summary()).getByTestId("query-summary-name").textContent).toBe("'<b>굵게</b>'");
    expect(within(summary()).getByTestId("query-summary-goods").textContent).toBe("<i>업종</i>");
    expect(summary().querySelector("b, i")).toBeNull();
  });

  it("입력 상태가 없으면 줄을 그리지 않는다", () => {
    view(SEARCH_V2_TEXT_FIXTURE, { queryHasName: true, queryName: "블루커피" });
    expect(screen.queryByTestId("query-summary")).not.toBeInTheDocument();
    view(logoResult(), { query: null });
    expect(screen.queryByTestId("query-summary")).not.toBeInTheDocument();
  });
});

describe("참고용 안내", () => {
  it("전체 등급 칸 안에 한 줄이 있고, 맨 아래 기존 문장은 그대로", () => {
    view(SEARCH_V2_TEXT_FIXTURE, { queryHasName: true, queryName: "블루커피" });
    const note = screen.getByTestId("reference-note");
    expect(note).toHaveTextContent(REFERENCE_NOTE);
    expect(note.closest("section")).toContainElement(screen.getByTestId("overall-grade"));
    expect(screen.getByText(/결과는 참고 정보이며 법적 판단이 아니에요/)).toBeVisible();
  });
});

describe("이름 확인 실패 안내", () => {
  it("특허청 조회 서비스의 응답을 받지 못한 경우(502·504·연결 실패)는 할 수 있는 일을 알려 준다", () => {
    const upstream = new ApiError(502, "KIPRIS 상표명 확인 서비스 응답을 확인하지 못했어요.");
    expect(nameCheckFailureMessage(upstream)).toBe(NAME_CHECK_FAILURE);
    expect(nameCheckFailureMessage(new ApiError(504, "시간 초과"))).toBe(NAME_CHECK_FAILURE);
    expect(nameCheckFailureMessage(new ApiError(0, "서버에 연결할 수 없어요."))).toBe(
      NAME_CHECK_FAILURE,
    );
    expect(NAME_CHECK_FAILURE).toBe(
      "특허청 조회 서비스에서 응답을 받지 못했어요. 잠시 뒤 다시 눌러 주세요. 검색은 그대로 쓸 수 있어요.",
    );
  });

  it("그 밖(요청 한도·입력 오류)은 서버 문장 그대로, 모르는 오류는 기본 문장", () => {
    const limit = new ApiError(429, "상표명 확인 호출 한도에 도달했어요. 한도 초기화 후 다시 시도하세요.");
    expect(nameCheckFailureMessage(limit)).toBe(limit.message);
    expect(nameCheckFailureMessage(new Error("boom"))).toBe(NAME_CHECK_UNKNOWN);
  });
});

describe("조사 — lib/josa.ts", () => {
  it("유형 셋 — 문자로·도형으로·결합으로", () => {
    expect(retypeLabel("문자")).toBe("문자로 고치기");
    expect(retypeLabel("도형")).toBe("도형으로 고치기");
    expect(retypeLabel("결합")).toBe("결합으로 고치기");
  });

  it("받침 ㄹ 뒤는 '로'", () => {
    expect(josaEuroRo("서울")).toBe("로");
    expect(josaEuroRo("스타벅스")).toBe("로");
    expect(josaEuroRo("김밥")).toBe("으로");
  });

  it("영문·숫자로 끝나는 말은 받침 없는 것으로 본다", () => {
    for (const name of ["STARBUCKS", "GS25", "cafe 7"]) {
      expect(josaEulReul(name)).toBe("를");
      expect(josaEunNeun(name)).toBe("는");
      expect(josaIGa(name)).toBe("가");
      expect(josaWaGwa(name)).toBe("와");
      expect(josaEuroRo(name)).toBe("로");
    }
  });

  it("한글 — 받침에 맞춘다", () => {
    expect(josaEulReul("김밥")).toBe("을");
    expect(josaEulReul("커피")).toBe("를");
    expect(josaEunNeun("서울")).toBe("은");
    expect(josaIGa("서울")).toBe("이");
    expect(josaWaGwa("서울")).toBe("과");
  });
});
