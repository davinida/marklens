/**
 * 프론트-2 상품↔유사군 변환표 스키마.
 * 생성: shared/goods_map/parse_goods_map.py → shared/goods_map/goods_map.json
 * 소비: 프론트-6(지정상품 입력 UI), 프론트-8(X4 자카드 유사도)
 */
export interface GoodsMapEntry {
  /** 고시상품명칭 (예: "화장품") */
  name: string;
  /** NICE 국제상품분류 류 번호 (1~45) */
  nice_class: number;
  /**
   * 유사군 코드 배열. 한 상품에 여러 개가 붙을 수 있으므로 항상 배열로 유지한다
   * (예: 화장품 = ["G1201", "S120907", "S128302"]).
   */
  similarity_codes: string[];
}

export type GoodsMap = GoodsMapEntry[];
