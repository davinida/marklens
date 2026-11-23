// 상표명 입력 정리 — 백엔드 clean_input_name(ml/src/axes/pair_axes.py)과 같은 규칙(견고성 점검 R-P1-6·B14·U3).
// 보이지 않는 서식 문자(유니코드 Cf — 폭 없는 공백·BOM·부드러운 붙임표·양방향 제어 문자 등)를 지우고 → NFC → 앞뒤
// 공백(파이썬 str.strip 이 지우는 공백)을 뗀다. 호환 문자·대소문자는 바꾸지 않는다.
//
// 두 문자 집합은 백엔드 파이썬(3.11 — 유니코드 14.0)의 것을 그대로 적었다. 브라우저·Node 의 \p{Cf} 는 유니코드 판에
// 따라 달라(Node 24 는 17.0 — U+13439–U+1343F 7자가 더 Cf) 같은 결과를 보장하지 못하고, JS trim() 은 파이썬 strip()
// 과 달리 U+001C–U+001F·U+0085 를 남긴다. 공용 사례 shared/text/clean_input_name_cases.json 으로 Vitest
// (markName.test.ts)·pytest(ml/tests/test_robustness_results.py)가 두 구현이 같은지 본다 — 백엔드 파이썬을 올려
// 유니코드 판이 바뀌면 그 파일을 다시 만들고 아래 두 집합도 같이 고친다.
const STRIP_SPACE = /[\u0009-\u000D\u001C-\u0020\u0085\u00A0\u1680\u2000-\u200A\u2028-\u2029\u202F\u205F\u3000]/u;
const FORMAT_CHARACTER = /[\u00AD\u0600-\u0605\u061C\u06DD\u070F\u0890-\u0891\u08E2\u180E\u200B-\u200F\u202A-\u202E\u2060-\u2064\u2066-\u206F\uFEFF\uFFF9-\uFFFB\u{110BD}\u{110CD}\u{13430}-\u{13438}\u{1BCA0}-\u{1BCA3}\u{1D173}-\u{1D17A}\u{E0001}\u{E0020}-\u{E007F}]/u;
const FORMAT_CHARACTERS = new RegExp(FORMAT_CHARACTER.source, "gu");
const EDGE_SPACES = new RegExp(`^${STRIP_SPACE.source}+|${STRIP_SPACE.source}+$`, "gu");

/** 상표명 입력 정리 — 서식 문자 제거 → NFC → 앞뒤 공백. 결과가 비면 이름이 없는 것으로 본다. */
export function cleanInputName(value: string | null | undefined): string {
  return (value ?? "").replace(FORMAT_CHARACTERS, "").normalize("NFC").replace(EDGE_SPACES, "");
}

/** 시험용 — 한 글자(코드 포인트 하나)가 지우는 서식 문자인지. */
export function isFormatCharacter(char: string): boolean {
  return FORMAT_CHARACTER.test(char);
}

/** 시험용 — 한 글자(코드 포인트 하나)가 앞뒤에서 떼는 공백인지. */
export function isStripSpace(char: string): boolean {
  return STRIP_SPACE.test(char);
}
