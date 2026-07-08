/**
 * MarkLens 백엔드 API 클라이언트.
 *
 * 백엔드 스키마(backend/src/schemas/search.py)의 필드명을 그대로 따른다.
 * 한글 필드명은 KIPRIS 원본 데이터 구조와의 일관성을 위한 팀 규약이다.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export interface TrademarkInfo {
  출원번호: string;
  등록번호?: string | null;
  출원일자?: string | null;
  등록일자?: string | null;
  상표한글명?: string | null;
  상표영문명?: string | null;
  상표구분?: string | null;
  출원인?: string | null;
  최종권리자?: string | null;
  비엔나코드: string[];
  류: number[];
  유사군: string[];
}

export interface SearchMatch {
  rank: number;
  similarity: number;
  이미지파일?: string | null;
  이미지URL?: string | null;
  trademark?: TrademarkInfo | null;
}

export type GradeCode = "CAUTION" | "REVIEW" | "LOW" | "SAFE";

export interface GradeInfo {
  grade_code: GradeCode;
  grade_name: string;
  message: string;
  top1_similarity: number;
  separability_a: number;
  separability_b: number;
  warnings: string[];
}

export interface DatasetInfo {
  총_상표수: number;
  출원일자_범위: string;
  데이터_기준: string;
  생성일자: string;
}

export interface SearchResponse {
  grade: GradeInfo;
  matches: SearchMatch[];
  dataset_info: DatasetInfo;
  index_size: number;
  top_k_requested: number;
  top_k_returned: number;
}

export interface HealthResponse {
  status: string;
  engine_ready: boolean;
  index_size: number;
  trademark_count: number;
}

/** 백엔드가 4xx/5xx와 함께 내려주는 detail 메시지를 보존하는 에러. */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const STATUS_FALLBACK: Record<number, string> = {
  400: "이미지를 처리할 수 없어요. 다른 파일로 시도해 주세요.",
  413: "파일이 너무 커요. 10MB 이하로 올려주세요.",
  415: "지원하지 않는 형식이에요. PNG·JPG·WEBP만 올릴 수 있어요.",
  422: "요청 값이 올바르지 않아요.",
  503: "검색 엔진이 아직 준비 중이에요. 잠시 후 다시 시도해 주세요.",
};

/** 로고 이미지 1장을 업로드해 유사 상표를 검색한다. */
export async function searchTrademark(
  file: File,
  topK: number,
): Promise<SearchResponse> {
  const form = new FormData();
  form.append("file", file);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/search?top_k=${topK}`, {
      method: "POST",
      body: form,
    });
  } catch {
    throw new ApiError(
      0,
      "서버에 연결할 수 없어요. 백엔드가 켜져 있는지 확인해 주세요.",
    );
  }

  if (!res.ok) {
    let detail = "";
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // detail 없는 에러 본문은 상태코드 기반 문구로 대체
    }
    throw new ApiError(
      res.status,
      detail || STATUS_FALLBACK[res.status] || "알 수 없는 오류가 발생했어요.",
    );
  }
  return (await res.json()) as SearchResponse;
}

/** 결과의 이미지 상대경로(/images/..)를 절대 URL로 바꾼다. */
export function imageUrl(relative?: string | null): string | null {
  return relative ? `${API_BASE}${relative}` : null;
}
