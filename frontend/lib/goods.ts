import type { GoodsMatch } from "@/lib/contracts";

/**
 * 프론트-6 지정상품 선택 상태 헬퍼. 선택 항목은 변환표 항목의 name·류·유사군만 담고(alias 적중 여부는
 * 화면 표시용이라 버림), 유사군 합집합(goodsCodeUnion)은 X4 자카드·/search 연동(범위 ③, 아직 미연동)의
 * 입력이 된다.
 */
export type SelectedGood = Pick<GoodsMatch, "name" | "nice_class" | "similarity_codes">;

/** 한 번에 고를 수 있는 지정상품 수. 실제 출원도 상품을 수십 개씩 적지만 화면·요청 크기를 위해 제한. */
export const MAX_SELECTED_GOODS = 20;

/** 같은 상품명이 여러 류에 있을 수 있으므로 류 번호까지 합쳐 중복을 판정한다. */
export function selectedGoodKey(good: Pick<SelectedGood, "name" | "nice_class">): string {
  return `${good.nice_class}:${good.name}`;
}

/** 선택한 상품들의 유사군 코드 합집합(정렬, 중복 없음). */
export function goodsCodeUnion(goods: readonly SelectedGood[]): string[] {
  const codes = new Set<string>();
  for (const good of goods) {
    for (const code of good.similarity_codes) codes.add(code);
  }
  return [...codes].sort();
}

export type AddGoodResult =
  | { added: true; next: SelectedGood[] }
  | { added: false; reason: "duplicate" | "limit"; next: SelectedGood[] };

/** 중복(name+류)과 상한을 검사해 새 목록을 돌려준다. 입력 배열은 바꾸지 않는다. */
export function addSelectedGood(
  goods: readonly SelectedGood[],
  candidate: SelectedGood,
  max: number = MAX_SELECTED_GOODS,
): AddGoodResult {
  const key = selectedGoodKey(candidate);
  if (goods.some((good) => selectedGoodKey(good) === key)) {
    return { added: false, reason: "duplicate", next: [...goods] };
  }
  if (goods.length >= max) {
    return { added: false, reason: "limit", next: [...goods] };
  }
  return {
    added: true,
    next: [
      ...goods,
      {
        name: candidate.name,
        nice_class: candidate.nice_class,
        similarity_codes: [...candidate.similarity_codes],
      },
    ],
  };
}

export function removeSelectedGood(
  goods: readonly SelectedGood[],
  target: Pick<SelectedGood, "name" | "nice_class">,
): SelectedGood[] {
  const key = selectedGoodKey(target);
  return goods.filter((good) => selectedGoodKey(good) !== key);
}

/** 결과 화면 요약: "커피, 커피전문점업 (유사군 3개)". 비어 있으면 빈 문자열. */
export function goodsSummaryText(goods: readonly SelectedGood[]): string {
  if (goods.length === 0) return "";
  const names = goods.map((good) => good.name).join(", ");
  return `${names} (유사군 ${goodsCodeUnion(goods).length}개)`;
}
