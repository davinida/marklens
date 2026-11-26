// 업종은 다르지만 표장이 닮은 후보(API 계약 v2 §2-8·§4-8) — 문구와, 응답의 cross_goods·
// cross_goods_more 에서 무엇을 보일지 정하는 규칙을 한 곳에 모은다. 문구는 정해진 글자 그대로(다듬지
// 말 것). 판단은 엔진의 것이다(후보의 cross_goods.flagged) — 여기서는 새로 판단하지 않는다.

import type { SearchV2Candidate, SearchV2Response } from "@/lib/contracts";

export const CROSS_GOODS_TEXT = {
  /** 후보 카드의 표시 */
  badge: "업종 다름",
  /** 후보 카드의 설명 한 줄 — 보통 상표 */
  plain:
    "표장은 닮았지만 업종이 달라요. 보통은 함께 등록될 수 있어요. 다만 나중에 이 업종으로 넓히면 문제가 될 수 있어요.",
  /** 후보 카드의 설명 한 줄 — 유명 상표 표시가 붙은 후보 */
  famous: "업종은 다르지만 널리 알려진 상표라 문제가 될 수 있어요.",
  /** 전체 등급 옆의 한 줄 */
  overall: "가장 닮은 상표가 다른 업종에 있어요. 업종이 다르면 함께 등록될 수도 있어요.",
} as const;

/** 접힌 칸에 한 번에 보이는 후보 수 */
export const CROSS_GOODS_MORE_LIMIT = 5;

/** 이 후보가 "업종은 다르지만 표장이 닮은 후보"인가 — 엔진이 정한 값 그대로(필드가 없으면 아니다). */
export function isCrossGoods(candidate: SearchV2Candidate): boolean {
  return candidate.cross_goods?.flagged === true;
}

/** 후보 카드의 설명 한 줄 — 표시되는 후보가 아니면 null. 유명 상표 표시가 붙은 후보는 다른 문구. */
export function crossGoodsLine(candidate: SearchV2Candidate): string | null {
  if (!isCrossGoods(candidate)) return null;
  return candidate.famous_brand ? CROSS_GOODS_TEXT.famous : CROSS_GOODS_TEXT.plain;
}

/**
 * 전체 등급 옆 한 줄을 보일지 — 가장 위 후보가 표시되는 후보이고, 유명 상표 바닥이 전체 등급을 정한
 * 것이 아닐 때만(그때는 "널리 알려진 상표와 …" 까닭 한 줄이 그 자리에 있다).
 */
export function showsCrossGoodsOverallLine(result: SearchV2Response): boolean {
  const first = result.candidates[0];
  return Boolean(first) && isCrossGoods(first) && result.overall.famous_floor !== true;
}

/**
 * 목록 아래 접힌 칸 — 처음 보이는 범위 밖에 표시되는 후보가 있을 때만. 응답의 cross_goods_more 에서
 * 표시되는 후보만 최대 CROSS_GOODS_MORE_LIMIT 개를 쓴다. 보일 것이 없으면 null(칸을 만들지 않는다).
 */
export function crossGoodsMore(
  result: SearchV2Response,
): { count: number; candidates: SearchV2Candidate[] } | null {
  const more = result.cross_goods_more;
  if (!more) return null;
  const candidates = more.candidates.filter(isCrossGoods).slice(0, CROSS_GOODS_MORE_LIMIT);
  if (!candidates.length) return null;
  return { count: Math.max(more.count, candidates.length), candidates };
}

/** 접힌 칸의 제목(버튼) — "업종은 다르지만 표장이 닮은 상표 {N}건". */
export function crossGoodsMoreTitle(count: number): string {
  return `업종은 다르지만 표장이 닮은 상표 ${count}건`;
}

/** 수가 보이는 것보다 많을 때의 한 줄 — 같으면 null. */
export function crossGoodsMoreNote(count: number, shown: number): string | null {
  return count > shown ? `${count}건 가운데 표장이 가장 닮은 ${shown}건을 보여요.` : null;
}
