// 설명적 이름 안내(API 계약 v2 §2-7·§4-7) — 문구와, 응답의 name_words·후보에서 무엇을 보일지 정하는
// 규칙을 한 곳에 모은다. 문구는 정해진 글자 그대로(다듬지 말 것) — 이름·낱말 바로 뒤의 조사만 받침에 맞춘다.
// 판정은 엔진의 것이다(낱말별 식별력) — 여기서는 새로 판정하지 않는다.

import type { SearchV2Candidate, SearchV2NameWord, SearchV2NameWords } from "@/lib/contracts";
import { josaEunNeun } from "@/lib/josa";

// ---- 분류별 문구(응답의 category 값 → 문구) ----------------------------------------------------
export const CATEGORY_GOODS = "상품 이름";
export const CATEGORY_COMMON = "흔히 쓰는 말";
export const CATEGORY_TEXT: Record<string, string> = {
  [CATEGORY_GOODS]: "파는 상품이나 서비스의 이름 그 자체예요",
  "성질·품질": "맛·품질·재료·쓰임새 같은 성질을 설명하는 말이에요",
  [CATEGORY_COMMON]: "여러 상표에 흔히 쓰이는 말이에요",
  "지역 이름": "널리 알려진 지역 이름이에요",
  "흔한 성·이름": "흔한 성이나 흔히 쓰는 이름이에요",
  "짧고 흔한 글자": "너무 짧거나 흔한 글자·숫자예요",
};
/** "그 밖"과 모르는 분류 */
export const CATEGORY_OTHER_TEXT = "식별력이 약한 말이에요";
/**
 * 큰 안내를 띄우는 분류 — "흔히 쓰는 말"(통계로 약해진 낱말)과 "그 밖"은 들지 않는다. 모든 낱말이
 * 식별력 없는 말이어도 이 분류의 낱말이 하나도 없으면(흔히 쓰는 말뿐이면) 작은 안내로 보인다.
 */
export const BIG_NOTICE_CATEGORIES: ReadonlySet<string> = new Set([
  CATEGORY_GOODS,
  "성질·품질",
  "지역 이름",
  "흔한 성·이름",
  "짧고 흔한 글자",
]);

export function categoryText(category: string | null | undefined): string {
  return (category && CATEGORY_TEXT[category]) || CATEGORY_OTHER_TEXT;
}

// ---- 안내 문구 --------------------------------------------------------------------------------
export const NOTICE_TEXT = {
  /** (가) 큰 안내 */
  bigTitle: "이 이름은 상표로 등록받기 어려울 수 있어요",
  bigLabel: "이름 안내 · 설명하는 말로만 된 이름",
  follow:
    "이런 말은 다른 가게도 자기 상품을 설명하려면 써야 해서, 한 사람만 쓰도록 등록받기 어려워요. 등록이 안 되면 다른 가게가 같은 이름을 써도 막을 수 없어요.",
  tipsTitle: "이렇게 해 보세요",
  tipCoin: "직접 지은 말을 이름의 중심에 넣어 보세요.",
  tipKeep: "설명하는 말은 같이 써도 괜찮아요. 다만 그 말 자체는 혼자 쓸 수 없어요.",
  retry: "다른 이름으로 다시 확인하기",
  footnote:
    "최종 판단은 특허청 심사에서 정해져요. 오래 써서 많은 사람이 알아보는 이름은 예외가 될 수 있어요.",
  /** (나) 작은 안내 — 일부 낱말만 */
  someToggle: "왜요?",
  someFollow: "이런 말은 누구나 써야 해서 혼자 쓸 수 없어요.",
  /** (다) 작은 안내 — 모든 낱말인데 흔히 쓰는 말뿐이거나, 유명 상표 배너(약한 일치·로고로만 강한 일치)가 있을 때 */
  allToggle: "자세히",
  /** 작은 안내의 제목(화면에는 보이지 않는다 — 제목 구조용) */
  smallHeading: "이름에 든 누구나 쓰는 말",
  /** (라) 전체 등급 옆의 한 줄 */
  wholeName: "설명하는 말로만 된 이름이라, 아래는 이름 전체를 견준 결과예요.",
} as const;

/** (가) 큰 안내의 본문 첫 줄 — '{이름}'은(는) 모두 상품을 설명하거나 누구나 쓰는 말이에요. */
export function bigLine(name: string): string {
  return `'${name}'${josaEunNeun(name)} 모두 상품을 설명하거나 누구나 쓰는 말이에요.`;
}

/** (다) 작은 안내의 한 줄 — '{이름}'은(는) 모두 누구나 쓰는 말이에요. */
export function allSmallLine(name: string): string {
  return `'${name}'${josaEunNeun(name)} 모두 누구나 쓰는 말이에요.`;
}

/** (나) '{낱말들}'은(는) 누구나 쓰는 말이라 빼고 비교했어요. — 싣지 않은 낱말이 있으면 "외 N개". */
export function someGenericLine(words: string[], more: number): string {
  const tail = "누구나 쓰는 말이라 빼고 비교했어요.";
  if (!words.length) return `이름의 낱말 ${more}개는 ${tail}`;
  const listed = `'${words.join("·")}'`;
  if (more > 0) return `${listed} 외 ${more}개는 ${tail}`;
  return `${listed}${josaEunNeun(words[words.length - 1])} ${tail}`;
}

/** 예: '○○ {상품 이름 낱말}'처럼요. */
export function tipExample(word: string): string {
  return `예: '○○ ${word}'처럼요.`;
}

/** 낱말 목록 끝의 "외 N개" 줄(싣지 않은 낱말). */
export function moreWordsLine(count: number): string {
  return `외 ${count}개`;
}

// ---- 무엇을 보일지 ----------------------------------------------------------------------------
export type DescriptiveNoticeKind = "big" | "all-small" | "some-small";

/**
 * 맨 위 유명 상표 배너가 설명적 이름 안내에 주는 영향(배너에서 정한다 — FamousBanner 의 famousBannerState).
 *  - "none": 강함·약함 배너가 없다(없거나 "설명적 사용" 안내 — 그 안내는 설명적 이름 안내 아래에 온다).
 *  - "banner": 강함·약함 배너가 위에 있다(약한 일치, 또는 로고로만 강한 일치) — 큰 안내 대신 작은 안내.
 *  - "name-strong": 그 배너가 이름 쪽의 강한 일치(이름·이미지 속 글자)로 떴다 — 설명적 이름 안내를
 *    그리지 않는다(큰 안내·작은 안내, 전체 등급 옆 한 줄 모두). 이름이 널리 알려진 상표와 같거나 거의
 *    같다고 알리는 자리에서 그 이름을 "누구나 쓰는 말"이라고 함께 말하지 않는다.
 */
export type FamousBannerState = "none" | "banner" | "name-strong";

/**
 * (나) "빼고 비교했어요"가 보이는 후보 모두에서 사실인가 — 이름을 견준 후보(상표명이 있는 후보)마다
 * 실린 식별력 없는 낱말이 모두 뺀 낱말(removed 의 side 가 query·both)에 들어 있고, 싣지 않은 식별력
 * 없는 낱말 수(more_generic)만큼 질의 쪽에서 뺀 낱말이 더 있다. 이름을 견준 후보가 하나도 없으면
 * 견준 것이 없으므로 사실이 아니다. 엔진은 결합 규칙이 요부로 되돌린 쌍이나, 후보의 업종 때문에 그
 * 쌍에서는 질의에 요부가 없는 쌍에서 그 낱말을 빼지 않는다(계약 v2 §2-7).
 */
export function removedAsSaid(
  nameWords: SearchV2NameWords,
  candidates: SearchV2Candidate[],
): boolean {
  const weak = genericWords(nameWords).map((word) => word.word);
  const named = candidates.filter((candidate) => candidate.title);
  if (!named.length) return false;
  return named.every((candidate) => {
    const removed = new Set(
      candidate.salient.removed
        .filter((item) => item.side !== "candidate")
        .map((item) => item.token),
    );
    if (!weak.every((word) => removed.has(word))) return false;
    return removed.size - weak.length >= nameWords.more_generic;
  });
}

/**
 * 안내의 종류.
 *  - 유명 상표 배너가 이름 쪽의 강한 일치로 떴으면("name-strong"): null — 어떤 안내도 그리지 않는다.
 *  - 모든 낱말이 식별력 없는 말(generic "all"): 큰 안내("big") — 다만 유명 상표 배너(강함·약함)가
 *    있거나, "흔히 쓰는 말"이 아닌 분류(BIG_NOTICE_CATEGORIES)의 낱말이 하나도 없으면 작은 안내
 *    ("all-small", "자세히").
 *  - 일부만(generic "some"): 작은 안내("some-small", "왜요?") — "빼고 비교했어요"가 보이는 후보
 *    모두에서 사실일 때만(removedAsSaid), 아니면 null.
 *  - 그 밖(없음·모르는 값·필드 없음): null.
 */
export function descriptiveNoticeKind(
  nameWords: SearchV2NameWords | undefined,
  famousBanner: FamousBannerState,
  candidates: SearchV2Candidate[],
): DescriptiveNoticeKind | null {
  if (!nameWords || famousBanner === "name-strong") return null;
  if (nameWords.generic === "all") {
    const decisive = genericWords(nameWords).some(
      (word) => word.category !== null && BIG_NOTICE_CATEGORIES.has(word.category),
    );
    return famousBanner === "banner" || !decisive ? "all-small" : "big";
  }
  if (nameWords.generic === "some") {
    return removedAsSaid(nameWords, candidates) ? "some-small" : null;
  }
  return null;
}

/** 응답에 실린 낱말 가운데 식별력 없는 낱말(이름 순서). */
export function genericWords(nameWords: SearchV2NameWords): SearchV2NameWord[] {
  return nameWords.words.filter((word) => !word.distinctive);
}

/** 안내에 보일 이름 — 사용자가 넣은 이름 그대로, 없으면 낱말을 띄어 이은 것. */
export function displayName(
  queryName: string | null | undefined,
  nameWords: SearchV2NameWords,
): string {
  const typed = queryName?.trim();
  return typed || nameWords.words.map((word) => word.word).join(" ");
}

/**
 * (라) "이름 전체를 견준 결과" 한 줄을 보일지 — 모든 낱말이 설명하는 말이고, 보이는 후보 가운데
 * 질의의 낱말이 빠진 것이 하나도 없을 때만. 엔진은 요부가 없는 이름의 낱말을 빼지 않지만, 후보 쪽의
 * 약한 낱말이 질의에도 있으면 그 후보와 견줄 때는 양쪽에서 함께 뺀다(removed 의 side 가
 * query·both) — 그런 후보가 보이면 이 줄은 사실이 아니어서 그리지 않는다. 유명 상표 배너가 이름 쪽의
 * 강한 일치로 떴으면("name-strong") 안내와 함께 이 줄도 그리지 않는다("설명하는 말로만 된 이름"이라는
 * 말을 그 자리에서 하지 않는다).
 */
export function showsWholeNameLine(
  nameWords: SearchV2NameWords | undefined,
  candidates: SearchV2Candidate[],
  famousBanner: FamousBannerState,
): boolean {
  if (!nameWords || nameWords.generic !== "all" || famousBanner === "name-strong") return false;
  return candidates.every((candidate) =>
    candidate.salient.removed.every((item) => item.side === "candidate"),
  );
}
