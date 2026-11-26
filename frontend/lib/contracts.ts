import { z } from "zod";

const NullableText = z.string().nullable().optional();

export const StatusCodeSchema = z.enum([
  "STRONG_MATCH",
  "POSSIBLE_MATCH",
  "WEAK_MATCH",
  "NO_CLOSE_MATCH",
]);

export const DatasetInfoSchema = z
  .object({
    총_상표수: z.number().int().nonnegative(),
    출원일자_범위: z.string(),
    데이터_기준: z.string(),
    생성일자: z.string(),
  })
  .passthrough();

// ---- 통합 검색 v2: docs/MarkLens_API계약_v2.md §2 ----
const UnitScore = z.number().finite().min(0).max(1);
const NullableUnitScore = UnitScore.nullable();
const NonnegativeInt = z.number().int().nonnegative();

export const SearchV2GradeSchema = z.enum(["안전", "주의", "검토 권장", "위험"]);
export const SearchV2QueryTypeSchema = z
  .object({
    type: z.enum(["문자", "도형", "결합-문자요부", "결합-도형요부"]),
    source: z.enum(["ocr", "fallback", "user"]),
    detail: z
      .object({ text_ratio: UnitScore, fig_ratio: UnitScore })
      .passthrough()
      .nullable(),
    suggested_name: z.string().nullable(),
  })
  .passthrough();

// 유명 상표 확인(v1.4.7, 선택 필드 — 없으면 유명 상표 확인이 꺼진 서버). level·basis·status·floor 는
// 문자열로 받아 화면이 아는 값만 그린다. 형식이 다르면 그 필드만 버린다(.catch) — 응답 전체를 거절해
// 기존 결과 화면이 깨지지 않게.
export const SearchV2FamousLogoSchema = z
  .object({ id: z.string(), image_url: z.string().nullable() })
  .passthrough();

export const SearchV2FamousMatchSchema = z
  .object({
    brand: z.string(),
    level: z.string(), // "강함" | "약함" | "설명적 사용"
    basis: z.string(), // "이름" | "로고" | "이미지 속 글자"
    notation: z.string().nullable(),
    matched_text: z.string().nullable(),
    protection: z.string(),
    goods_overlap: z.boolean().nullable(),
    floor: z.string().nullable(), // "위험" | "검토 권장" | null
    logos: z.array(SearchV2FamousLogoSchema),
  })
  .passthrough();

export const SearchV2FamousSchema = z
  .object({
    status: z.string(), // "checked" | "unavailable"
    brand_count: NonnegativeInt,
    matches: z.array(SearchV2FamousMatchSchema),
  })
  .passthrough();

// 질의 이름의 낱말별 식별력(선택 필드 — 이름이 있는 질의만, 계약 v2 §2-7). 설명적 이름 안내가 쓴다.
// generic·category 는 문자열로 받아 화면이 아는 값만 그린다. 형식이 다르면 그 필드만 버린다(.catch).
export const SearchV2NameWordSchema = z
  .object({
    word: z.string(),
    distinctive: z.boolean(),
    category: z.string().nullable(), // 식별력이 없을 때만 — "상품 이름" 등 화면용 분류
    reason: z.string().optional(), // 엔진의 사유 원문(화면은 쓰지 않는다)
  })
  .passthrough();

export const SearchV2NameWordsSchema = z
  .object({
    generic: z.string(), // "all" | "some" | "none"
    words: z.array(SearchV2NameWordSchema),
    more: NonnegativeInt,
    more_generic: NonnegativeInt,
  })
  .passthrough();

export const SearchV2CandidateSchema = z
  .object({
    id: z.string().regex(/^[0-9]{13}$/),
    title: z.string().nullable(),
    image_url: z.string().nullable(),
    type: z.enum(["문자", "도형", "결합"]).nullable(),
    applicant: z.string().nullable(),
    nice_classes: z.array(z.number().int().min(1).max(45)),
    axes: z
      .object({
        x1: NullableUnitScore,
        x2_text: NullableUnitScore,
        x2_img: NullableUnitScore,
        x3: NullableUnitScore,
        x4: NullableUnitScore,
      })
      .passthrough(),
    risk: z
      .object({
        prob: UnitScore,
        grade: SearchV2GradeSchema,
        // Logit contributions and missing-pattern offsets can be negative.
        contributions: z
          .object({
            X1: z.number().finite(),
            X2: z.number().finite(),
            X3: z.number().finite(),
            X4: z.number().finite(),
            요부: z.number().finite(),
          })
          .passthrough(),
        missing_adjustment: z.number().finite(),
        figure_caveat: z.boolean(),
        rule_triggers: z.array(z.string()),
        // 계수 집합 — "noname:…" 은 이름 없는 판단(계약 v2 §2-2; 화면은 위험도 %를 숨긴다)
        pattern: z.string(),
      })
      .passthrough(),
    salient: z
      .object({
        query_tokens: z.array(z.string()),
        candidate_tokens: z.array(z.string()),
        removed: z.array(
          z
            .object({
              token: z.string(),
              reason: z.string(),
              side: z.enum(["query", "candidate", "both"]),
            })
            .passthrough(),
        ),
      })
      .passthrough(),
    goods: z
      .object({ codes: z.array(z.string()), jaccard: NullableUnitScore })
      .passthrough(),
    // 유명 상표 등록부의 표장일 때만(v1.4.7)
    famous_brand: z.string().optional().catch(undefined),
  })
  .passthrough();

export const SearchV2ResponseSchema = z
  .object({
    api_version: z.literal("2026-10-24"),
    research_beta: z.literal(true),
    legal_conclusion: z.literal(false),
    overall: z
      .object({
        grade: SearchV2GradeSchema.nullable(),
        prob: NullableUnitScore,
        // 전체 등급을 정한 판단의 계수 집합(후보 0건이면 null, 계약 v2 §2-1)
        pattern: z.string().nullable(),
        caveats: z.array(z.string()),
        query_type: SearchV2QueryTypeSchema,
        visual_status: StatusCodeSchema.nullable(),
        // 유명 상표 바닥이 전체 등급을 정했으면 true(v1.4.7)
        famous_floor: z.boolean().optional().catch(undefined),
      })
      .passthrough(),
    candidates: z.array(SearchV2CandidateSchema),
    meta: z
      .object({
        model_version: z.string(),
        grade_precision: UnitScore,
        thresholds: z
          .object({
            grade: z
              .object({ 주의: UnitScore, "검토 권장": UnitScore, 위험: UnitScore })
              .passthrough(),
            // 이름 없는 계수 집합(risk.pattern 키)별 하한 — null 은 위험도로는 닿지 않는 등급
            nameless: z.record(
              z.string(),
              z
                .object({
                  주의: NullableUnitScore,
                  "검토 권장": NullableUnitScore,
                  위험: NullableUnitScore,
                })
                .passthrough(),
            ),
            standalone: z
              .object({
                x1: NullableUnitScore,
                x2_text: NullableUnitScore,
                x2_img: NullableUnitScore,
                x3: NullableUnitScore,
                x4: NullableUnitScore,
              })
              .passthrough(),
            figure: UnitScore,
          })
          .passthrough(),
        pool: z
          .object({
            image: NonnegativeInt,
            phonetic: NonnegativeInt,
            spelling: NonnegativeInt,
            semantic: NonnegativeInt,
            goods: NonnegativeInt,
            total: NonnegativeInt,
          })
          .passthrough(),
        elapsed_ms: NonnegativeInt,
      })
      .passthrough(),
    dataset_info: DatasetInfoSchema,
    index_size: NonnegativeInt,
    top_k_requested: z.number().int().min(1).max(20),
    top_k_returned: NonnegativeInt.max(20),
    famous: SearchV2FamousSchema.optional().catch(undefined),
    name_words: SearchV2NameWordsSchema.optional().catch(undefined),
  })
  .passthrough();

export type SearchV2Response = z.infer<typeof SearchV2ResponseSchema>;
export type SearchV2Candidate = z.infer<typeof SearchV2CandidateSchema>;
export type SearchV2Famous = z.infer<typeof SearchV2FamousSchema>;
export type SearchV2FamousMatch = z.infer<typeof SearchV2FamousMatchSchema>;
export type SearchV2NameWords = z.infer<typeof SearchV2NameWordsSchema>;
export type SearchV2NameWord = z.infer<typeof SearchV2NameWordSchema>;
export type SearchV2Grade = z.infer<typeof SearchV2GradeSchema>;
export type SearchV2QueryType = z.infer<typeof SearchV2QueryTypeSchema>;

const NameCheckCandidateInputSchema = z.union([
  z.string(),
  z.record(z.string(), z.unknown()),
]);

const StatusCountsSchema = z
  .record(z.string(), z.number().int().nonnegative())
  .optional();

const AdditiveNameCheckSchema = z
  .object({
    available: z.boolean(),
    normalized_name: z.string().optional(),
    similar_count: z.number().int().nonnegative().optional(),
    exact_count: z.number().int().nonnegative().optional(),
    exact_registered_count: z.number().int().nonnegative().optional(),
    exact_title_count: z.number().int().nonnegative().optional(),
    candidates: z.array(NameCheckCandidateInputSchema).optional(),
    examples: z.array(NameCheckCandidateInputSchema).optional(),
    status_counts: StatusCountsSchema,
    status_distribution: StatusCountsSchema,
    candidates_returned: z.number().int().nonnegative().optional(),
    candidates_truncated: z.boolean().optional(),
    message: z.string(),
    complete: z.boolean().optional(),
    scanned_count: z.number().int().nonnegative().optional(),
    total_found: z.number().int().nonnegative().optional(),
    checked_at: z.string().nullable().optional(),
    source: z.string().optional(),
  })
  .passthrough();

const LegacyNameCheckSchema = z
  .object({
    query: z.string(),
    total_found: z.number().int().nonnegative(),
    scanned_count: z.number().int().nonnegative().optional(),
    registered_count: z.number().int().nonnegative(),
    exact_registered_count: z.number().int().nonnegative(),
    exact_title_count: z.number().int().nonnegative().optional(),
    complete: z.boolean().optional(),
    checked_at: z.string().nullable().optional(),
    source: z.string().optional(),
    candidates: z.array(NameCheckCandidateInputSchema).optional(),
    examples: z.array(NameCheckCandidateInputSchema).optional(),
    status_counts: StatusCountsSchema,
    status_distribution: StatusCountsSchema,
    candidates_returned: z.number().int().nonnegative().optional(),
    candidates_truncated: z.boolean().optional(),
    cached: z.boolean(),
    message: z.string(),
  })
  .passthrough();

export interface NameCheckCandidate {
  id: string;
  name: string;
  applicationNumber: string | null;
  registrationNumber: string | null;
  applicationStatus: string | null;
  applicantName: string | null;
  rightHolderName: string | null;
  applicationDate: string | null;
  registrationDate: string | null;
  markType: string | null;
  niceClasses: string[];
  similarityCodes: string[];
  viennaCodes: string[];
  localImageUrl: string | null;
  exactTitleMatch: boolean | null;
  isRegistered: boolean | null;
}

export interface NameCheckResult {
  available: boolean | null;
  normalizedName: string;
  similarCount: number;
  /** @deprecated Use exactRegisteredCount. */
  exactCount: number;
  exactRegisteredCount: number;
  exactTitleCount: number;
  candidates: NameCheckCandidate[];
  candidatesReturned: number;
  candidatesTruncated: boolean;
  statusCounts: Record<string, number>;
  message: string;
  complete: boolean | null;
  scannedCount: number | null;
  totalFound: number;
  checkedAt: string | null;
  source: string;
}

function firstText(
  value: Record<string, unknown>,
  keys: readonly string[],
): string | null {
  for (const key of keys) {
    const candidate = value[key];
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  return null;
}

function textList(
  value: Record<string, unknown>,
  keys: readonly string[],
): string[] {
  for (const key of keys) {
    const candidate = value[key];
    if (Array.isArray(candidate)) {
      return candidate
        .filter((item): item is string => typeof item === "string")
        .map((item) => item.trim())
        .filter(Boolean);
    }
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate
        .split(/[|,]/)
        .map((item) => item.trim())
        .filter(Boolean);
    }
  }
  return [];
}

function normalizeCandidate(
  input: z.infer<typeof NameCheckCandidateInputSchema>,
  index: number,
): NameCheckCandidate {
  if (typeof input === "string") {
    return {
      id: `name-${input}-${index}`,
      name: input.trim() || "이름 미제공 상표",
      applicationNumber: null,
      registrationNumber: null,
      applicationStatus: null,
      applicantName: null,
      rightHolderName: null,
      applicationDate: null,
      registrationDate: null,
      markType: null,
      niceClasses: [],
      similarityCodes: [],
      viennaCodes: [],
      localImageUrl: null,
      exactTitleMatch: null,
      isRegistered: null,
    };
  }

  const applicationNumber = firstText(input, [
    "application_number",
    "applicationNumber",
    "ApplicationNumber",
    "출원번호",
  ]);
  const registrationNumber = firstText(input, [
    "registration_number",
    "registrationNumber",
    "RegistrationNumber",
    "등록번호",
  ]);
  const name =
    firstText(input, [
      "name",
      "title",
      "Title",
      "trademark_name",
      "상표명",
      "상표한글명",
      "상표영문명",
    ]) ?? applicationNumber ?? "이름 미제공 상표";
  const exactValue =
    input.exact_title_match ?? input.exact ?? input.is_exact;
  const registeredValue = input.is_registered;

  return {
    id: applicationNumber ?? registrationNumber ?? `name-${name}-${index}`,
    name,
    applicationNumber,
    registrationNumber,
    applicationStatus: firstText(input, [
      "status",
      "application_status",
      "applicationStatus",
      "ApplicationStatus",
      "상태",
    ]),
    applicantName: firstText(input, [
      "applicant",
      "applicant_name",
      "applicantName",
      "ApplicantName",
      "출원인",
    ]),
    rightHolderName: firstText(input, [
      "right_holder",
      "right_holder_name",
      "rightHolderName",
      "RegistrationRightholderName",
      "최종권리자",
    ]),
    applicationDate: firstText(input, [
      "application_date",
      "applicationDate",
      "ApplicationDate",
      "출원일자",
    ]),
    registrationDate: firstText(input, [
      "registration_date",
      "registrationDate",
      "RegistrationDate",
      "등록일자",
    ]),
    markType: firstText(input, [
      "mark_type",
      "markType",
      "TrademarkDivisionCode",
      "상표구분",
    ]),
    niceClasses: textList(input, [
      "nice_classes",
      "niceClasses",
      "GoodClassificationCode",
      "류",
    ]),
    similarityCodes: textList(input, [
      "similarity_codes",
      "similarityCodes",
      "SimilarCode",
      "유사군",
    ]),
    viennaCodes: textList(input, [
      "vienna_codes",
      "viennaCodes",
      "ViennaCode",
      "비엔나코드",
    ]),
    localImageUrl: firstText(input, [
      "local_image_url",
      "image_url",
      "이미지URL",
      "ImageURL",
      "ImagePath",
    ]),
    exactTitleMatch: typeof exactValue === "boolean" ? exactValue : null,
    isRegistered:
      typeof registeredValue === "boolean" ? registeredValue : null,
  };
}

function normalizeCandidates(
  candidates: z.infer<typeof NameCheckCandidateInputSchema>[] | undefined,
): NameCheckCandidate[] {
  return (candidates ?? []).map(normalizeCandidate);
}

export function parseNameCheckResponse(
  input: unknown,
  requestedName: string,
): NameCheckResult {
  const additive = AdditiveNameCheckSchema.safeParse(input);
  if (additive.success) {
    const value = additive.data;
    const complete = value.complete ?? null;
    return {
      available: complete === true ? value.available : null,
      normalizedName: value.normalized_name?.trim() || requestedName.trim(),
      similarCount: value.similar_count ?? 0,
      exactCount:
        value.exact_registered_count ?? value.exact_count ?? 0,
      exactRegisteredCount:
        value.exact_registered_count ?? value.exact_count ?? 0,
      exactTitleCount:
        value.exact_title_count ?? value.exact_count ?? 0,
      candidates: normalizeCandidates(value.candidates ?? value.examples),
      candidatesReturned:
        value.candidates_returned ??
        (value.candidates ?? value.examples ?? []).length,
      candidatesTruncated: value.candidates_truncated ?? false,
      statusCounts: value.status_counts ?? value.status_distribution ?? {},
      message: value.message,
      complete,
      scannedCount: value.scanned_count ?? null,
      totalFound: value.total_found ?? value.scanned_count ?? 0,
      checkedAt: value.checked_at ?? null,
      source: value.source ?? "KIPRIS",
    };
  }

  const legacy = LegacyNameCheckSchema.parse(input);
  const complete = legacy.complete ?? null;
  return {
    available:
      complete === true ? legacy.exact_registered_count === 0 : null,
    normalizedName: legacy.query.trim() || requestedName.trim(),
    similarCount: legacy.registered_count,
    exactCount: legacy.exact_registered_count,
    exactRegisteredCount: legacy.exact_registered_count,
    exactTitleCount:
      legacy.exact_title_count ?? legacy.exact_registered_count,
    candidates: normalizeCandidates(legacy.candidates ?? legacy.examples),
    candidatesReturned:
      legacy.candidates_returned ??
      (legacy.candidates ?? legacy.examples ?? []).length,
    candidatesTruncated: legacy.candidates_truncated ?? false,
    statusCounts: legacy.status_counts ?? legacy.status_distribution ?? {},
    message: legacy.message,
    complete,
    scannedCount: legacy.scanned_count ?? null,
    totalFound: legacy.total_found,
    checkedAt: legacy.checked_at ?? null,
    source:
      legacy.source ??
      (legacy.cached ? "KIPRIS cache (legacy)" : "KIPRIS (legacy)"),
  };
}

export type StatusCode = z.infer<typeof StatusCodeSchema>;

// ---- X1 호칭(발음) 유사도 검색 (/api/phonetic-search) ----
// 백엔드 /phonetic-search 응답. 한글 키는 KIPRIS 원본 데이터 구조를 따르고 passthrough 로 추가 필드를 허용한다.
export const PhoneticMatchSchema = z
  .object({
    rank: z.number().int().positive(),
    similarity: z.number().finite(),
    출원번호: z.string(),
    상표한글명: z.string(),
    이미지URL: NullableText,
    출원인: NullableText,
    류: z.array(z.number()).optional().default([]),
  })
  .passthrough();

export const PhoneticSearchResponseSchema = z
  .object({
    query: z
      .object({
        name: z.string(),
        has_pronunciation: z.boolean(),
        candidates: z.array(z.string()).optional().default([]),
      })
      .passthrough(),
    matches: z.array(PhoneticMatchSchema),
    searched_count: z.number().int().nonnegative(),
    excluded_no_pronunciation: z.number().int().nonnegative(),
    dataset_info: DatasetInfoSchema.optional(),
    params: z
      .object({
        top_k: z.number().int().positive(),
        min_similarity: z.number().min(0).max(1),
      })
      .passthrough(),
    axis: z.string().optional(),
    note: z.string().optional(),
  })
  .passthrough();

export type PhoneticMatch = z.infer<typeof PhoneticMatchSchema>;
export type PhoneticSearchResponse = z.infer<typeof PhoneticSearchResponseSchema>;

// ---- X3 관념(의미) 유사도 검색 (/api/semantic-search) — phonetic-search 와 같은 구조 ----
// 백엔드 /semantic-search 응답. 점수 필드는 score(재보정 코사인)이고 나머지 키는 phonetic 과 같다.
export const SemanticMatchSchema = z
  .object({
    rank: z.number().int().positive(),
    score: z.number().finite(),
    출원번호: z.string(),
    상표한글명: z.string(),
    이미지URL: NullableText,
    출원인: NullableText,
    류: z.array(z.number()).optional().default([]),
  })
  .passthrough();

export const SemanticSearchResponseSchema = z
  .object({
    query: z
      .object({
        name: z.string(),
        has_meaning: z.boolean(),
        text: z.string().optional().default(""),
      })
      .passthrough(),
    matches: z.array(SemanticMatchSchema),
    searched_count: z.number().int().nonnegative(),
    excluded_no_meaning: z.number().int().nonnegative(),
    dataset_info: DatasetInfoSchema.optional(),
    params: z
      .object({
        top_k: z.number().int().positive(),
        min_score: z.number().min(0).max(1),
      })
      .passthrough(),
    threshold: z.number().min(0).max(1).optional(),
    axis: z.string().optional(),
    note: z.string().optional(),
    model: z.string().optional(),
  })
  .passthrough();

export type SemanticMatch = z.infer<typeof SemanticMatchSchema>;
export type SemanticSearchResponse = z.infer<typeof SemanticSearchResponseSchema>;

// ---- 상품↔유사군 변환표 검색 (/api/goods/search, /api/goods/classes) — 프론트-6 지정상품 입력 UI용 ----
// 백엔드 /goods/* 응답. 필드는 shared/types/goods.ts 의 GoodsMapEntry + matched_alias(원 명칭으로 잡힌 경우).
export const GoodsMatchSchema = z
  .object({
    name: z.string().min(1),
    nice_class: z.number().int().min(1).max(45),
    similarity_codes: z.array(z.string()),
    matched_alias: z.string().nullable().optional().default(null),
  })
  .passthrough();

// 업종 세트(shared/goods_map/business_presets.json): 검색어가 업종명·별칭에 부분 일치하면 함께 온다.
export const PresetGoodSchema = z
  .object({
    name: z.string().min(1),
    nice_class: z.number().int().min(1).max(45),
    similarity_codes: z.array(z.string()),
  })
  .passthrough();

export const BusinessPresetSchema = z
  .object({
    id: z.string().min(1),
    업종명: z.string().min(1),
    emoji: z.string().optional().default(""),
    hint: z.string().optional().default(""),
    지정상품: z.array(PresetGoodSchema),
  })
  .passthrough();

export const GoodsSearchResponseSchema = z
  .object({
    query: z.string(),
    matches: z.array(GoodsMatchSchema),
    total: z.number().int().nonnegative(),
    offset: z.number().int().nonnegative().optional().default(0),
    presets: z.array(BusinessPresetSchema).optional().default([]),
    source: z.string().optional(),
  })
  .passthrough();

export const GoodsClassSchema = z
  .object({
    nice_class: z.number().int().min(1).max(45),
    title: z.string(),
    count: z.number().int().nonnegative(),
  })
  .passthrough();

export const GoodsClassesResponseSchema = z
  .object({
    classes: z.array(GoodsClassSchema),
    total_entries: z.number().int().nonnegative().optional(),
    source: z.string().optional(),
  })
  .passthrough();

export type GoodsMatch = z.infer<typeof GoodsMatchSchema>;
export type PresetGood = z.infer<typeof PresetGoodSchema>;
export type BusinessPreset = z.infer<typeof BusinessPresetSchema>;
export type GoodsSearchResponse = z.infer<typeof GoodsSearchResponseSchema>;
export type GoodsClass = z.infer<typeof GoodsClassSchema>;
export type GoodsClassesResponse = z.infer<typeof GoodsClassesResponseSchema>;
