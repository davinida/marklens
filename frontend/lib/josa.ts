// 종성(받침) 유무로 조사를 고른다. 한글 음절로 끝나지 않으면(라틴 문자·숫자 등) 받침 없는 것으로
// 본다 — 결과 화면(ResultViewV2)의 조사 규칙과 같다.

export function hasBatchim(text: string): boolean {
  const code = text.trim().slice(-1).charCodeAt(0);
  if (Number.isNaN(code) || code < 0xac00 || code > 0xd7a3) return false;
  return (code - 0xac00) % 28 !== 0;
}

export function josaEunNeun(text: string): "은" | "는" {
  return hasBatchim(text) ? "은" : "는";
}

export function josaWaGwa(text: string): "과" | "와" {
  return hasBatchim(text) ? "과" : "와";
}

/** "으로/로" — 받침이 없거나 ㄹ 받침이면 "로"(문자로·결합으로·도형으로). */
export function josaEuroRo(text: string): "으로" | "로" {
  if (!hasBatchim(text)) return "로";
  const code = text.trim().slice(-1).charCodeAt(0);
  return (code - 0xac00) % 28 === 8 ? "로" : "으로"; // 8 = ㄹ 받침
}

export function josaIGa(text: string): "이" | "가" {
  return hasBatchim(text) ? "이" : "가";
}
