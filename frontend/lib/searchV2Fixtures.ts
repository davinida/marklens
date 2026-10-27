import type { SearchV2Response } from "@/lib/contracts";

/**
 * API 계약 v2 §3 의 실측 예시 JSON 그대로(2026-10-25). 백엔드 스텁·프론트 Vitest 픽스처 공용 —
 * 숫자를 바꾸지 말 것(§3 말미 검산식이 이 값으로 맞춰져 있다). 계약이 바뀌면 문서와 함께 갱신한다.
 */

// §3-1. 문자상표 — 이름 "블루커피" + 카페 세트, 이미지 없음
export const SEARCH_V2_TEXT_FIXTURE: SearchV2Response = {
  api_version: "2026-10-24",
  research_beta: true,
  legal_conclusion: false,
  overall: {
    grade: "위험",
    prob: 0.604,
    caveats: [
      "이미지가 없어 외관(이미지) 축은 비교하지 않았습니다",
      "비교 대상 중 지정상품 정보가 있는 상표는 100/1,100건입니다",
    ],
    query_type: { type: "문자", source: "fallback", detail: null, suggested_name: null },
    visual_status: null,
  },
  candidates: [
    {
      id: "4020230001001",
      title: "BLUE CAFE 블루카페",
      image_url: "/api/images/4020230001001.png",
      type: "결합",
      applicant: "예시 출원인 1",
      nice_classes: [43],
      axes: { x1: 0.891, x2_text: 0.556, x2_img: null, x3: 0.548, x4: 0.25 },
      risk: {
        prob: 0.604,
        grade: "위험",
        contributions: { X1: 3.162, X2: 0.475, X3: 0.0, X4: 0.24, 요부: 0.0 },
        missing_adjustment: 0.018,
        figure_caveat: false,
        rule_triggers: [],
      },
      salient: {
        query_tokens: ["블루"],
        candidate_tokens: ["블루카페"],
        removed: [
          { token: "커피", reason: "1호 보통명칭·3호 기술적 표장:원재료(류 30,35,43)", side: "query" },
          { token: "blue", reason: "일반어(zipf 5.1)·다수 등록(A=53, N=54)", side: "candidate" },
          { token: "cafe", reason: "3호 기술적 표장:용도(류 35,43)", side: "candidate" },
        ],
      },
      goods: { codes: ["S120602"], jaccard: 0.25 },
    },
    {
      id: "4020220000777",
      title: "블루보틀 BLUE BOTTLE",
      image_url: "/api/images/4020220000777.png",
      type: "결합",
      applicant: "예시 출원인 2",
      nice_classes: [30, 43],
      axes: { x1: 0.673, x2_text: 0.5, x2_img: null, x3: 0.52, x4: 0.75 },
      risk: {
        prob: 0.52,
        grade: "검토 권장",
        contributions: { X1: 2.388, X2: 0.427, X3: 0.0, X4: 0.719, 요부: 0.0 },
        missing_adjustment: 0.018,
        figure_caveat: false,
        rule_triggers: [],
      },
      salient: {
        query_tokens: ["블루"],
        candidate_tokens: ["블루보틀", "bottle"],
        removed: [
          { token: "커피", reason: "1호 보통명칭·3호 기술적 표장:원재료(류 30,35,43)", side: "query" },
          { token: "blue", reason: "일반어(zipf 5.1)·다수 등록(A=53, N=54)", side: "candidate" },
        ],
      },
      goods: { codes: ["G0301", "G0502", "S120602"], jaccard: 0.75 },
    },
    {
      id: "4020210000333",
      title: "블루밍 BLOOMING",
      image_url: null,
      type: "결합",
      applicant: "예시 출원인 3",
      nice_classes: [3],
      axes: { x1: 0.778, x2_text: 0.625, x2_img: null, x3: 0.539, x4: 0.0 },
      risk: {
        prob: 0.46,
        grade: "검토 권장",
        contributions: { X1: 2.761, X2: 0.534, X3: 0.0, X4: 0.0, 요부: 0.0 },
        missing_adjustment: 0.018,
        figure_caveat: false,
        rule_triggers: [],
      },
      salient: {
        query_tokens: ["블루"],
        candidate_tokens: ["블루밍", "blooming"],
        removed: [
          { token: "커피", reason: "1호 보통명칭·3호 기술적 표장:원재료(류 30,35,43)", side: "query" },
        ],
      },
      goods: { codes: ["G1201"], jaccard: 0.0 },
    },
    {
      id: "4020200002222",
      title: "레드커피",
      image_url: "/api/images/4020200002222.png",
      type: "결합",
      applicant: "예시 출원인 4",
      nice_classes: [30, 43],
      axes: { x1: 0.473, x2_text: 0.0, x2_img: null, x3: 0.0, x4: 0.5 },
      risk: {
        prob: 0.215,
        grade: "검토 권장",
        contributions: { X1: 1.679, X2: 0.0, X3: 0.0, X4: 0.479, 요부: 0.0 },
        missing_adjustment: 0.018,
        figure_caveat: false,
        rule_triggers: [],
      },
      salient: {
        query_tokens: ["블루"],
        candidate_tokens: ["레드"],
        removed: [
          { token: "커피", reason: "1호 보통명칭·3호 기술적 표장:원재료(류 30,35,43)", side: "both" },
        ],
      },
      goods: { codes: ["G0502", "S120602"], jaccard: 0.5 },
    },
  ],
  meta: {
    model_version: "risk_model_v1.3",
    grade_precision: 0.7039,
    thresholds: {
      grade: { 주의: 0.0902, "검토 권장": 0.1805, 위험: 0.5902 },
      standalone: { x1: 0.98, x2_text: 0.75, x2_img: null, x3: 0.7707, x4: null },
      figure: 0.9,
    },
    pool: { image: 0, phonetic: 20, spelling: 20, semantic: 5, goods: 20, total: 41 },
    elapsed_ms: 180,
  },
  dataset_info: {
    총_상표수: 1100,
    출원일자_범위: "2021-01-05 ~ 2026-08-20",
    데이터_기준: "KIPRIS Plus 등록상표, generation 20260827T035002Z-25f84a6eeb26",
    생성일자: "2026-08-27",
  },
  index_size: 1100,
  top_k_requested: 4,
  top_k_returned: 4,
};

// §3-2. 도형상표 — 이미지만, 상표명·지정상품 없음
export const SEARCH_V2_FIGURE_FIXTURE: SearchV2Response = {
  api_version: "2026-10-24",
  research_beta: true,
  legal_conclusion: false,
  overall: {
    grade: "검토 권장",
    prob: 0.06,
    caveats: [
      "도형 유사는 검증 데이터가 적어 참고용",
      "상표명이 없어 호칭·철자·관념 축은 비교하지 않았습니다",
      "지정상품이 없어 상품 견련성은 비교하지 않았습니다",
    ],
    query_type: {
      type: "도형",
      source: "ocr",
      detail: { text_ratio: 0.01, fig_ratio: 0.62 },
      suggested_name: null,
    },
    visual_status: "STRONG_MATCH",
  },
  candidates: [
    {
      id: "4020190004444",
      title: null,
      image_url: "/api/images/4020190004444.png",
      type: "도형",
      applicant: "예시 출원인 5",
      nice_classes: [25],
      axes: { x1: null, x2_text: null, x2_img: 0.93, x3: null, x4: null },
      risk: {
        prob: 0.06,
        grade: "검토 권장",
        contributions: { X1: 0.0, X2: 1.059, X3: 0.0, X4: 0.0, 요부: 0.0 },
        missing_adjustment: -0.339,
        figure_caveat: true,
        rule_triggers: ["figure_x2_img"],
      },
      salient: { query_tokens: [], candidate_tokens: [], removed: [] },
      goods: { codes: [], jaccard: null },
    },
    {
      id: "4020210005555",
      title: "뫼비우스 MOBIUS",
      image_url: "/api/images/4020210005555.png",
      type: "결합",
      applicant: "예시 출원인 6",
      nice_classes: [9, 42],
      axes: { x1: null, x2_text: null, x2_img: 0.81, x3: null, x4: null },
      risk: {
        prob: 0.053,
        grade: "안전",
        contributions: { X1: 0.0, X2: 0.922, X3: 0.0, X4: 0.0, 요부: 0.0 },
        missing_adjustment: -0.339,
        figure_caveat: true,
        rule_triggers: [],
      },
      salient: { query_tokens: [], candidate_tokens: ["뫼비우스", "mobius"], removed: [] },
      goods: { codes: ["G390802"], jaccard: null },
    },
    {
      id: "4020220006666",
      title: "INFINITY",
      image_url: null,
      type: "결합",
      applicant: "예시 출원인 7",
      nice_classes: [35],
      axes: { x1: null, x2_text: null, x2_img: 0.62, x3: null, x4: null },
      risk: {
        prob: 0.043,
        grade: "안전",
        contributions: { X1: 0.0, X2: 0.706, X3: 0.0, X4: 0.0, 요부: 0.0 },
        missing_adjustment: -0.339,
        figure_caveat: true,
        rule_triggers: [],
      },
      salient: { query_tokens: [], candidate_tokens: ["infinity"], removed: [] },
      goods: { codes: [], jaccard: null },
    },
  ],
  meta: {
    model_version: "risk_model_v1.3",
    grade_precision: 0.7039,
    thresholds: {
      grade: { 주의: 0.0902, "검토 권장": 0.1805, 위험: 0.5902 },
      standalone: { x1: 0.98, x2_text: 0.75, x2_img: null, x3: 0.7707, x4: null },
      figure: 0.9,
    },
    pool: { image: 20, phonetic: 0, spelling: 0, semantic: 0, goods: 0, total: 20 },
    elapsed_ms: 410,
  },
  dataset_info: {
    총_상표수: 1100,
    출원일자_범위: "2021-01-05 ~ 2026-08-20",
    데이터_기준: "KIPRIS Plus 등록상표, generation 20260827T035002Z-25f84a6eeb26",
    생성일자: "2026-08-27",
  },
  index_size: 1100,
  top_k_requested: 3,
  top_k_returned: 3,
};

/** 후보 0건(§5-4) — image 없는 조어 이름 등, 어느 축도 하한을 못 넘긴 경우. */
export const SEARCH_V2_EMPTY_FIXTURE: SearchV2Response = {
  api_version: "2026-10-24",
  research_beta: true,
  legal_conclusion: false,
  overall: {
    grade: null,
    prob: null,
    caveats: [
      "이미지가 없어 외관(이미지) 축은 비교하지 않았습니다",
      "지정상품이 없어 상품 견련성은 비교하지 않았습니다",
      "비교할 후보가 없습니다 — 안전하다는 뜻이 아닙니다",
    ],
    query_type: { type: "문자", source: "fallback", detail: null, suggested_name: null },
    visual_status: null,
  },
  candidates: [],
  meta: {
    model_version: "risk_model_v1.3",
    grade_precision: 0.7039,
    thresholds: {
      grade: { 주의: 0.0902, "검토 권장": 0.1805, 위험: 0.5902 },
      standalone: { x1: 0.98, x2_text: 0.75, x2_img: null, x3: 0.7707, x4: null },
      figure: 0.9,
    },
    pool: { image: 0, phonetic: 0, spelling: 0, semantic: 0, goods: 0, total: 0 },
    elapsed_ms: 42,
  },
  dataset_info: {
    총_상표수: 1100,
    출원일자_범위: "2021-01-05 ~ 2026-08-20",
    데이터_기준: "KIPRIS Plus 등록상표, generation 20260827T035002Z-25f84a6eeb26",
    생성일자: "2026-08-27",
  },
  index_size: 1100,
  top_k_requested: 5,
  top_k_returned: 0,
};
