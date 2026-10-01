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

export type AddPresetResult = {
  next: SelectedGood[];
  added: number;
  duplicates: number;
  overLimit: number;
};

/** 업종 세트의 지정상품을 한꺼번에 추가한다(중복·상한 처리는 addSelectedGood 재사용). */
export function addPresetGoods(
  goods: readonly SelectedGood[],
  presetGoods: readonly SelectedGood[],
  max: number = MAX_SELECTED_GOODS,
): AddPresetResult {
  let next: SelectedGood[] = [...goods];
  let added = 0;
  let duplicates = 0;
  let overLimit = 0;
  for (const good of presetGoods) {
    const result = addSelectedGood(next, good, max);
    if (result.added) {
      next = result.next;
      added += 1;
    } else if (result.reason === "duplicate") {
      duplicates += 1;
    } else {
      overLimit += 1;
    }
  }
  return { next, added, duplicates, overLimit };
}

/**
 * "자주 찾는 업종" 칩 12개(순서 고정). id 는 business_presets.json 의 세트 id 이고 query 는 칩을 눌렀을 때
 * 검색창에 넣는 말 — 세트의 별칭에 부분 일치해 세트 카드가 열리고 개별 검색 결과도 함께 나온다.
 */
export const FREQUENT_PRESETS: readonly {
  id: string;
  label: string;
  emoji: string;
  query: string;
}[] = [
  { id: "cafe", label: "카페", emoji: "☕", query: "카페" },
  { id: "chicken", label: "치킨집", emoji: "🍗", query: "치킨" },
  { id: "korean_restaurant", label: "식당(한식)", emoji: "🍚", query: "한식" },
  { id: "bunsik", label: "분식집", emoji: "🍢", query: "분식" },
  { id: "bakery", label: "빵집", emoji: "🥐", query: "빵집" },
  { id: "pub", label: "술집", emoji: "🍺", query: "술집" },
  { id: "hair_salon", label: "미용실", emoji: "💇", query: "미용실" },
  { id: "nail", label: "네일샵", emoji: "💅", query: "네일" },
  { id: "fitness", label: "헬스장·필라테스", emoji: "🏋️", query: "헬스" },
  { id: "academy", label: "학원", emoji: "📚", query: "학원" },
  { id: "clothing", label: "옷가게·쇼핑몰", emoji: "👕", query: "의류" },
  { id: "cosmetics", label: "화장품", emoji: "🧴", query: "화장품" },
];

/** 결과 화면 요약: "커피, 커피전문점업 (유사군 3개)". 비어 있으면 빈 문자열. */
export function goodsSummaryText(goods: readonly SelectedGood[]): string {
  if (goods.length === 0) return "";
  const names = goods.map((good) => good.name).join(", ");
  return `${names} (유사군 ${goodsCodeUnion(goods).length}개)`;
}
