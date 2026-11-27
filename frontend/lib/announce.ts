// 화면 낭독기용 알림과 포커스 이동 규칙(API 계약 v2 §4-10). 화면에는 보이지 않는 한 줄(role="status")을
// page.tsx 가 본문 맨 위에 두고, 사용자가 검색을 실행했을 때만 이 문장을 넣는다 — 처음 페이지를 열었을
// 때는 비어 있다. 오류 문장은 오류 화면의 role="alert" 가 바로 알린다(여기서는 비운다).

import { josaIeyoYeyo } from "@/lib/josa";

export const ANNOUNCE_TEXT = {
  /** 검색 중 */
  searching: "검색하고 있어요",
  /** 결과가 나왔을 때의 머리 — 뒤에 전체 등급 문장이 붙는다 */
  resultLead: "검색 결과가 나왔어요.",
  /** 전체 등급이 없을 때(비교할 후보가 없음) */
  noCandidates: "비교할 후보가 없어요.",
  /** 결과 화면의 제목(화면에는 보이지 않는 h1 — 결과가 나오면 포커스를 여기로 옮긴다) */
  resultTitle: "검색 결과",
} as const;

/** 결과가 나왔을 때 — "검색 결과가 나왔어요. 전체 등급은 {등급}이에요." (받침이 없으면 "예요") */
export function resultAnnouncement(grade: string | null | undefined): string {
  if (!grade) return `${ANNOUNCE_TEXT.resultLead} ${ANNOUNCE_TEXT.noCandidates}`;
  return `${ANNOUNCE_TEXT.resultLead} 전체 등급은 ${grade}${josaIeyoYeyo(grade)}.`;
}

/** 입력 화면으로 돌아갈 때 포커스를 둘 곳 — 버튼이 가리키는 칸. 없으면 입력 화면의 제목. */
export type FocusTarget = "name" | "logo" | "heading";

/** 포커스를 옮긴다 — 가리키는 칸이 화면에 없으면 그 화면의 제목([data-phase-heading])으로. */
export function moveFocus(target: FocusTarget): void {
  if (target === "name") {
    const input = document.querySelector<HTMLInputElement>("#mark-text");
    if (input) {
      input.focus();
      input.select();
      return;
    }
  }
  if (target === "logo") {
    const picker = document.querySelector<HTMLElement>("[data-logo-picker]");
    if (picker) {
      picker.focus();
      return;
    }
  }
  document.querySelector<HTMLElement>("[data-phase-heading]")?.focus();
}
