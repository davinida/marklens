import { forwardRef, useEffect, useImperativeHandle } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import LoadingView from "@/components/LoadingView";
import ResultViewV2 from "@/components/ResultViewV2";
import SearchForm from "@/components/SearchForm";
import { SearchV2ResponseSchema, type SearchV2Response } from "@/lib/contracts";
import { PHOTO_CAVEAT } from "@/lib/resultExtras";
import descriptiveFixture from "@/test/fixtures/search-v2-descriptive.json";
import famousFixture from "@/test/fixtures/search-v2-famous.json";
import imageFixture from "@/test/fixtures/search-v2-image.json";
import textFixture from "@/test/fixtures/search-v2-text.json";

// 접근성 — 제목 구조와 이름(API 계약 v2 §4-10). 눈에 보이는 모습은 그대로 두고 마크업의 뜻만 본다:
// 화면마다 h1 하나, 단계를 건너뛰지 않는 제목, 이름 붙은 영역, 길이로 뜻을 전하는 막대의 글자.

vi.mock("@/components/TurnstileWidget", () => ({
  default: forwardRef<{ reset: () => void }, { onTokenChange: (token: string | null) => void }>(
    function MockTurnstile({ onTokenChange }, ref) {
      useImperativeHandle(ref, () => ({ reset: () => onTokenChange("test-token") }));
      useEffect(() => onTokenChange("test-token"), [onTokenChange]);
      return <div>자동 요청 확인 완료</div>;
    },
  ),
}));

const TEXT = SearchV2ResponseSchema.parse(textFixture);
const IMAGE = SearchV2ResponseSchema.parse(imageFixture);
const FAMOUS = SearchV2ResponseSchema.parse(famousFixture);
const DESCRIPTIVE = SearchV2ResponseSchema.parse(descriptiveFixture);

function view(result: SearchV2Response, queryHasName = true) {
  return render(
    <ResultViewV2
      result={result}
      queryPreview={null}
      queryHasName={queryHasName}
      queryName={queryHasName ? "블루커피" : null}
      onReset={vi.fn()}
      onAddName={vi.fn()}
    />,
  );
}

/** 제목을 문서 순서로 — [단계, 글자] */
function outline(): [number, string][] {
  return screen
    .getAllByRole("heading")
    .map((node) => [Number(node.tagName.slice(1)), node.textContent ?? ""]);
}

function expectNoSkippedLevel(list: [number, string][]) {
  let previous = 0;
  for (const [level, text] of list) {
    expect(level, `"${text}" 앞의 단계가 h${previous}`).toBeLessThanOrEqual(previous + 1);
    previous = level;
  }
}

describe("결과 화면 — 제목 구조", () => {
  it.each([
    ["이름 + 업종", TEXT, true],
    ["로고만", IMAGE, false],
    ["유명 상표 배너", FAMOUS, true],
    ["설명적 이름 안내", DESCRIPTIVE, true],
  ])("%s: h1 은 하나(화면에 보이지 않는 '검색 결과')이고 단계를 건너뛰지 않는다", (_label, result, named) => {
    view(result, named);
    const list = outline();
    expect(list.filter(([level]) => level === 1)).toEqual([[1, "검색 결과"]]);
    expect(list[0]).toEqual([1, "검색 결과"]);
    expectNoSkippedLevel(list);
  });

  it("결과 제목은 포커스를 받을 수 있고(화면이 바뀌면 여기로 옮긴다) 윤곽은 그리지 않는다", () => {
    view(TEXT);
    const title = screen.getByRole("heading", { level: 1 });
    expect(title).toHaveAttribute("data-phase-heading");
    expect(title).toHaveAttribute("tabindex", "-1");
    expect(title).toHaveClass("sr-only", "outline-none");
    expect(document.querySelectorAll("[data-phase-heading]")).toHaveLength(1);
  });

  it("전체 등급·주의·후보 목록은 h2, 후보 카드는 h3", () => {
    view(TEXT);
    const overall = screen.getByRole("region", { name: "전체 등급" });
    expect(overall).toContainElement(screen.getByTestId("overall-grade"));
    expect(within(overall).getByRole("heading", { level: 2, name: "전체 등급" })).toHaveClass("sr-only");
    expect(within(overall).getByRole("heading", { level: 2, name: "주의할 점" })).toHaveClass("sr-only");

    const list = screen.getByRole("region", { name: "유사 상표 후보" });
    const cards = [...list.querySelector(":scope > ul")!.children];
    expect(cards.length).toBe(TEXT.candidates.length);
    cards.forEach((card, index) => {
      expect(card.tagName).toBe("LI");
      const heading = within(card as HTMLElement).getByRole("heading", { level: 3 });
      expect(heading).toHaveTextContent(TEXT.candidates[index].title ?? "이름 미등록 상표");
      expect(heading).toHaveClass("sr-only");
    });
  });

  it("주의 문구가 없으면 '주의할 점' 제목도 없다", () => {
    view({ ...TEXT, overall: { ...TEXT.overall, caveats: [] } });
    expect(screen.queryByRole("heading", { name: "주의할 점" })).not.toBeInTheDocument();
  });

  it("로고만 넣은 결과 — 상표명 입력 안내와 사진 안내도 제목(h2)으로 이름 붙은 영역", () => {
    view({ ...IMAGE, overall: { ...IMAGE.overall, caveats: [...IMAGE.overall.caveats, PHOTO_CAVEAT] } }, false);
    const notice = screen.getByRole("region", { name: "상표 이름 입력 안내" });
    expect(notice).toBe(screen.getByTestId("logo-only-notice"));
    expect(within(notice).getByRole("heading", { level: 2 })).toHaveClass("sr-only");
    const photo = screen.getByRole("region", { name: "사진 안내" });
    expect(photo).toContainElement(screen.getByTestId("photo-notice"));
    expectNoSkippedLevel(outline());
  });
});

describe("결과 화면 — 펼치는 버튼과 길이로 뜻을 전하는 요소", () => {
  it("후보 카드의 버튼은 펼침 상태와 대상을 알리고, 펼친 뒤의 제목은 h4", async () => {
    const user = userEvent.setup();
    view(TEXT);
    const card = screen.getByRole("region", { name: "유사 상표 후보" }).querySelector(":scope > ul > li")!;
    const toggle = within(card as HTMLElement).getAllByRole("button")[0];
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const panel = document.getElementById(toggle.getAttribute("aria-controls")!);
    expect(panel).not.toBeNull();
    expect(within(panel!).getByRole("heading", { level: 4, name: "등급 근거 축" })).toBeVisible();
    expectNoSkippedLevel(outline());
  });

  it("근거 막대 — 길이(몫)가 글자로도 읽힌다", async () => {
    const user = userEvent.setup();
    view(TEXT);
    const card = screen.getByRole("region", { name: "유사 상표 후보" }).querySelector(":scope > ul > li")!;
    await user.click(within(card as HTMLElement).getAllByRole("button")[0]);
    const bars = within(card as HTMLElement).getByRole("list", { name: "등급 근거 축(기여도 순)" });
    const labels = within(bars)
      .getAllByRole("img")
      .map((bar) => bar.getAttribute("aria-label") ?? "");
    expect(labels.length).toBeGreaterThan(0);
    for (const label of labels) expect(label).toMatch(/^근거 가운데 \d+%$/);
    const shares = labels.map((label) => Number(label.match(/\d+/)![0]));
    expect(Math.abs(shares.reduce((sum, share) => sum + share, 0) - 100)).toBeLessThanOrEqual(labels.length);
  });

  it("등급 눈금·등급 배지·'업종 다름'은 글자로도 읽힌다", () => {
    view(TEXT);
    expect(screen.getAllByRole("img", { name: /^등급 눈금: / }).length).toBeGreaterThan(0);
    expect(screen.getByTestId("overall-grade")).toHaveTextContent(TEXT.overall.grade!);
    for (const badge of screen.queryAllByTestId("candidate-cross-goods")) {
      expect(badge).toHaveTextContent("업종 다름");
    }
  });
});

describe("입력 화면·검색 중 화면", () => {
  it("로고 파일 입력에 이름이 있고, 파일 고르기는 눈에 보이는 버튼(키보드로 포커스가 감)이 연다", () => {
    render(<SearchForm onSubmit={vi.fn()} />);
    const input = document.querySelector('input[type="file"]')!;
    expect(input).toHaveAttribute("aria-label", "로고 이미지 파일 선택");
    const picker = screen.getByRole("button", { name: /로고 이미지 선택/ });
    expect(picker).toHaveAttribute("data-logo-picker");
    expect(picker).not.toHaveAttribute("tabindex", "-1");
    // 입력 화면의 h1 은 눈에 보이는 제목 하나
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expectNoSkippedLevel(outline());
  });

  it("검색 중 화면 — 문장은 해요체이고 여기서 따로 알리지 않는다(알림은 page 의 한 줄이 한 번)", () => {
    render(<LoadingView queryPreview={null} onCancel={vi.fn()} />);
    const line = screen.getByText("로고를 분석하고 있어요.");
    expect(line).toHaveClass("sr-only");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText(/진행 중입니다/)).not.toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });
});
