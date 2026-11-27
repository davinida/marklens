// 결과 화면의 보완(API 계약 v2 §4-9) — 로고만 넣은 검색의 상표명 입력 안내, 검색 내용 표시, 참고용
// 안내, 사진 안내의 자리, 이름 확인 실패 안내. 문구와 규칙을 한 곳에 모은다(문구는 정해진 글자
// 그대로). 질의에서 온 글자는 텍스트로만 쓴다.

import { ApiError } from "@/lib/api";
import { josaEulReul } from "@/lib/josa";

/** 화면에서 줄여 보이는 길이(이름·로고에서 읽은 글자) — 전체는 title 로 둔다. */
export const DISPLAY_LIMIT = 40;

/** 한 줄로(줄바꿈·연속 공백을 한 칸으로). */
export function oneLine(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

/** 화면용 — DISPLAY_LIMIT 를 넘으면 줄인다(코드 포인트 기준). */
export function shorten(text: string, limit: number = DISPLAY_LIMIT): string {
  const chars = Array.from(text);
  return chars.length > limit ? `${chars.slice(0, limit).join("")}…` : text;
}

// ---- 1. 로고만 넣은 검색의 상표명 입력 안내 ---------------------------------------------------
export const LOGO_ONLY_TEXT = {
  /** A형 — 로고에서 읽은 글자가 있을 때(앞뒤로 읽은 글자와 조사가 들어간다) */
  readLead: "로고에서 ",
  readTail: " 읽었어요. 지금은 로고 모양만 비교했어요. 이름까지 넣으면 이름이 닮은 상표도 찾을 수 있어요.",
  readButton: "이 이름을 넣고 다시 확인하기",
  /** B형 — 읽은 글자가 없을 때 */
  plain: "로고 모양만 비교한 결과예요. 상표 이름이 있다면 함께 넣어 보세요. 이름이 닮은 상표는 로고만으로는 찾지 못해요.",
  plainButton: "이름 넣고 다시 확인하기",
  /** 영역의 이름(화면에는 보이지 않는다) */
  label: "상표 이름 입력 안내",
} as const;

export type LogoOnlyNoticeKind = "read" | "plain";

/** 안내의 종류 — 로고만 넣은 검색(이름이 없고 이미지가 있는 질의)이 아니면 null. */
export function logoOnlyNoticeKind(
  logoOnly: boolean,
  suggestedName: string | null | undefined,
): LogoOnlyNoticeKind | null {
  if (!logoOnly) return null;
  return suggestedName && oneLine(suggestedName) ? "read" : "plain";
}

/** A형 문장 전체(시험·title 용) — 로고에서 '{읽은 글자}'을(를) 읽었어요. … */
export function logoReadLine(text: string): string {
  const read = oneLine(text);
  return `${LOGO_ONLY_TEXT.readLead}'${shorten(read)}'${josaEulReul(read)}${LOGO_ONLY_TEXT.readTail}`;
}

// ---- 서버가 보낸 주의 문구 가운데 자리를 옮기거나 숨기는 것(계약 v2 §2-5) ----------------------
/** 사진 안내 영역의 이름(화면에는 보이지 않는 제목) */
export const PHOTO_NOTICE_LABEL = "사진 안내";
/** PHOTO_QUERY — 맨 위 안내 영역으로 옮긴다(문장은 서버가 준 그대로). */
export const PHOTO_CAVEAT = "사진으로 보여요 — 로고 파일을 올리면 외관 비교가 더 정확해요";
/** NAME_SUGGESTED 의 머리·꼬리 — 상표명 입력 안내가 같은 내용을 말할 때 주의 목록에서 뺀다. */
const NAME_SUGGESTED_HEAD = "이미지에서 '";
const NAME_SUGGESTED_TAIL = "를 읽었어요 — 상표명으로 넣으면 호칭·철자·관념도 비교해요";

export function isNameSuggestedCaveat(caveat: string): boolean {
  return caveat.startsWith(NAME_SUGGESTED_HEAD) && caveat.endsWith(NAME_SUGGESTED_TAIL);
}

/** 주의 목록을 나눈다 — 사진 안내(있으면 그 문장), 목록에 남길 것. */
export function splitCaveats(
  caveats: string[],
  hideNameSuggested: boolean,
): { photo: string | null; rest: string[] } {
  const photo = caveats.find((caveat) => caveat === PHOTO_CAVEAT) ?? null;
  const rest = caveats.filter(
    (caveat) => caveat !== PHOTO_CAVEAT && !(hideNameSuggested && isNameSuggestedCaveat(caveat)),
  );
  return { photo, rest };
}

// ---- 2. 검색 내용 표시 -----------------------------------------------------------------------
/** 결과 화면이 갖고 있는 입력 상태 — 없으면(새로 고침 등) 검색 내용 줄을 그리지 않는다. */
export interface QuerySummaryInput {
  name: string;
  /** 로고 미리보기 주소(사용자가 고른 영역) — 없으면 null */
  logo: string | null;
  /** 고른 업종(지정상품) 이름 */
  goods: string[];
}

export const QUERY_SUMMARY_TEXT = {
  label: "검색한 내용",
  noName: "이름 없음",
  noLogo: "로고 없음",
  noGoods: "업종 선택 안 함",
  logoAlt: "검색한 로고",
} as const;

/** 업종 이름을 보여 줄 만큼 적는다. */
export const GOODS_SHOWN = 3;

/** 업종 — 셋까지 적고 나머지는 "외 n개". 없으면 "업종 선택 안 함". */
export function goodsSummary(names: string[]): string {
  if (!names.length) return QUERY_SUMMARY_TEXT.noGoods;
  const shown = names.slice(0, GOODS_SHOWN).join(", ");
  const more = names.length - GOODS_SHOWN;
  return more > 0 ? `${shown} 외 ${more}개` : shown;
}

// ---- 4. 참고용 안내 --------------------------------------------------------------------------
export const REFERENCE_NOTE = "참고용 결과예요. 법적 판단이 아니에요.";

// ---- 3. 이름 확인 실패 안내 ------------------------------------------------------------------
export const NAME_CHECK_FAILURE =
  "특허청 조회 서비스에서 응답을 받지 못했어요. 잠시 뒤 다시 눌러 주세요. 검색은 그대로 쓸 수 있어요.";
export const NAME_CHECK_UNKNOWN = "이름을 확인하지 못했어요. 다시 시도해 주세요.";

/**
 * 이름 확인이 실패했을 때 보일 문장. 특허청 조회 서비스(외부)의 응답을 받지 못한 경우(502·504,
 * 연결 실패)는 무엇을 할 수 있는지 알려 주는 문장으로, 그 밖(입력 오류·요청 한도 등)은 서버가 준
 * 문장 그대로. 지금 오는 응답으로는 "이번 달 조회 한도"를 가를 수 없어(하루·한 달 한도가 같은
 * 429) 한도 전용 문장은 쓰지 않는다.
 */
export function nameCheckFailureMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return NAME_CHECK_UNKNOWN;
  if (error.status === 0 || error.status === 502 || error.status === 504) return NAME_CHECK_FAILURE;
  return error.message;
}
