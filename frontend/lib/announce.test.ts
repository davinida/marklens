// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { ANNOUNCE_TEXT, moveFocus, resultAnnouncement } from "@/lib/announce";
import { josaIeyoYeyo } from "@/lib/josa";

// 화면 낭독기용 알림 문장과 포커스 이동(API 계약 v2 §4-10).

describe("resultAnnouncement — 결과가 나왔을 때의 알림", () => {
  it.each([
    ["위험", "검색 결과가 나왔어요. 전체 등급은 위험이에요."],
    ["검토 권장", "검색 결과가 나왔어요. 전체 등급은 검토 권장이에요."],
    ["안전", "검색 결과가 나왔어요. 전체 등급은 안전이에요."],
    // 받침이 없는 등급 이름은 "예요"
    ["주의", "검색 결과가 나왔어요. 전체 등급은 주의예요."],
  ])("%s", (grade, sentence) => {
    expect(resultAnnouncement(grade)).toBe(sentence);
  });

  it("등급이 없으면 비교할 후보가 없다고 알린다", () => {
    expect(resultAnnouncement(null)).toBe("검색 결과가 나왔어요. 비교할 후보가 없어요.");
    expect(resultAnnouncement(undefined)).toBe("검색 결과가 나왔어요. 비교할 후보가 없어요.");
  });

  it("검색 중 문장과 결과 화면의 제목", () => {
    expect(ANNOUNCE_TEXT.searching).toBe("검색하고 있어요");
    expect(ANNOUNCE_TEXT.resultTitle).toBe("검색 결과");
  });

  it("이에요/예요는 받침으로 고른다", () => {
    expect(josaIeyoYeyo("위험")).toBe("이에요");
    expect(josaIeyoYeyo("주의")).toBe("예요");
  });
});

describe("moveFocus — 버튼이 가리키는 칸, 없으면 그 화면의 제목", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  function mount(html: string) {
    document.body.innerHTML = html;
  }

  it("이름 칸 — 포커스를 두고 전체를 고른다", () => {
    mount('<h1 data-phase-heading tabindex="-1">제목</h1><input id="mark-text" value="블루커피" />');
    moveFocus("name");
    const input = document.querySelector<HTMLInputElement>("#mark-text")!;
    expect(document.activeElement).toBe(input);
    expect(input.selectionStart).toBe(0);
    expect(input.selectionEnd).toBe("블루커피".length);
  });

  it("로고 고르기 버튼", () => {
    mount('<h1 data-phase-heading tabindex="-1">제목</h1><button data-logo-picker>로고 이미지 선택</button>');
    moveFocus("logo");
    expect(document.activeElement).toBe(document.querySelector("[data-logo-picker]"));
  });

  it("가리키는 칸이 화면에 없으면 제목으로", () => {
    mount('<h1 data-phase-heading tabindex="-1">제목</h1>');
    moveFocus("name");
    expect(document.activeElement).toBe(document.querySelector("h1"));
    (document.activeElement as HTMLElement).blur();
    moveFocus("logo");
    expect(document.activeElement).toBe(document.querySelector("h1"));
  });

  it("따로 정하지 않으면 제목으로", () => {
    mount('<h1 data-phase-heading tabindex="-1">제목</h1><input id="mark-text" />');
    moveFocus("heading");
    expect(document.activeElement).toBe(document.querySelector("h1"));
  });
});
