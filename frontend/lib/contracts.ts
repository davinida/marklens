import { z } from "zod";

const NullableText = z.string().nullable().optional();

export const TrademarkInfoSchema = z
  .object({
    출원번호: z.string(),
    등록번호: NullableText,
    출원일자: NullableText,
    등록일자: NullableText,
    상표한글명: NullableText,
    상표영문명: NullableText,
    상표구분: NullableText,
    출원인: NullableText,
    최종권리자: NullableText,
    비엔나코드: z.array(z.string()).optional().default([]),
    류: z.array(z.number()).optional().default([]),
    유사군: z.array(z.string()).optional().default([]),
  })
  .passthrough();

export const SearchMatchSchema = z
  .object({
    rank: z.number().int().positive(),
    similarity: z.number().finite(),
    이미지파일: NullableText,
    이미지URL: NullableText,
    trademark: TrademarkInfoSchema.nullable().optional(),
  })
  .passthrough();

export const GradeCodeSchema = z.enum(["CAUTION", "REVIEW", "LOW", "SAFE"]);
export const StatusCodeSchema = z.enum([
  "STRONG_MATCH",
  "POSSIBLE_MATCH",
  "WEAK_MATCH",
  "NO_CLOSE_MATCH",
]);

export const GradeInfoSchema = z
  .object({
    grade_code: GradeCodeSchema,
    grade_name: z.string(),
    status_code: StatusCodeSchema.optional(),
    status_name: z.string().min(1).optional(),
    uncertain: z.boolean().optional(),
    uncertainty_reasons: z.array(z.string()).optional(),
    scored_candidate_count: z.number().int().positive().optional(),
    threshold_version: z.string().min(1).optional(),
    scope: z.literal("visual_similarity_only").optional(),
    calibrated: z.literal(false).optional(),
    legal_conclusion: z.literal(false).optional(),
    message: z.string(),
    top1_similarity: z.number().finite(),
    separability_a: z.number().finite(),
    separability_b: z.number().finite(),
    warnings: z.array(z.string()).optional().default([]),
  })
  .passthrough()
  .superRefine((value, context) => {
    if (!value.status_code) return;
    for (const field of [
      "status_name",
      "uncertain",
      "uncertainty_reasons",
      "scored_candidate_count",
      "threshold_version",
      "scope",
      "calibrated",
      "legal_conclusion",
    ] as const) {
      if (value[field] === undefined) {
        context.addIssue({
          code: "custom",
          path: [field],
          message: `canonical grade field ${field} is required`,
        });
      }
    }
  });

export const DatasetInfoSchema = z
  .object({
    총_상표수: z.number().int().nonnegative(),
    출원일자_범위: z.string(),
    데이터_기준: z.string(),
    생성일자: z.string(),
  })
  .passthrough();

export const SearchResponseSchema = z
  .object({
    grade: GradeInfoSchema,
    matches: z.array(SearchMatchSchema),
    dataset_info: DatasetInfoSchema,
    index_size: z.number().int().nonnegative(),
    top_k_requested: z.number().int().positive(),
    top_k_returned: z.number().int().nonnegative(),
    scoring_k: z.number().int().positive().optional(),
    api_version: z.string().optional(),
    research_beta: z.boolean().optional(),
  })
  .passthrough();

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

export type SearchResponse = z.infer<typeof SearchResponseSchema>;
export type SearchMatch = z.infer<typeof SearchMatchSchema>;
export type GradeCode = z.infer<typeof GradeCodeSchema>;
export type StatusCode = z.infer<typeof StatusCodeSchema>;
