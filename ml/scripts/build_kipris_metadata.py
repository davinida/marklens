#!/usr/bin/env python3
"""
KIPRIS 원시 txt 6개를 출원번호 기준으로 통합하여 메타데이터 JSON을 생성합니다.

사용법:
    python scripts/build_kipris_metadata.py \
        [--raw-dir data/raw_kipris] [--output data/kipris_metadata.json]

이 단계에서는 "이미지파일" 칼럼에 "{출원번호}.png"를 적어둘 뿐 실제 추출은 하지 않습니다.
실제 추출은 extract_kipris_images.py가 수행하며, 이미지 부재 항목은
이후 reconcile 단계에서 제외됩니다.

데이터 통합 방식:
- 중심 열쇠: 출원번호 (PDF 파일명, gongbo txt 4개와 일치)
- 등록번호 ↔ 출원번호 매핑은 TB_KT10에서 직접 가져옴 (RG_BS.txt 미사용)
- LAST_RG_HOLDER는 등록번호 기준이므로 위 매핑으로 연결
"""

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

# === 구분자 ===
SEP_GONGBO = "^B"      # gongbo/ 4개 파일 (literal "^"+"B" 두 글자)
SEP_REGISTRATION = "¶"  # registration/ (U+00B6)


# === 도형 필터링 ===
DOHYEONG_KEYWORDS = {"도형상표", "도형복합"}


def clean(value: str) -> Optional[str]:
    """공백 한 칸 또는 빈 문자열이면 None을 반환합니다."""
    if value is None:
        return None
    v = value.strip()
    return v if v else None


def normalize_date(yyyymmdd: Optional[str]) -> Optional[str]:
    """YYYYMMDD 형식을 YYYY-MM-DD로 정규화합니다. 비정상 입력은 None 반환."""
    v = clean(yyyymmdd)
    if v is None or len(v) != 8 or not v.isdigit():
        return None
    return f"{v[0:4]}-{v[4:6]}-{v[6:8]}"


def parse_table(path: Path, sep: str) -> tuple[list[str], list[list[str]]]:
    """
    구분자로 분리된 텍스트 파일을 (헤더, 데이터행) 튜플로 파싱합니다.

    각 행은 헤더 칼럼 수에 맞춰 슬라이스됩니다 (줄 끝 구분자로 인한
    여분 빈 칼럼은 잘립니다).
    """
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f]
    if not lines:
        return [], []

    header = lines[0].split(sep)
    ncols = len(header)
    rows = []
    for line in lines[1:]:
        cols = line.split(sep)
        # 헤더 길이에 맞춤 (모자라면 빈 문자열로 패딩, 남으면 잘라냄)
        if len(cols) < ncols:
            cols = cols + [""] * (ncols - len(cols))
        else:
            cols = cols[:ncols]
        rows.append(cols)
    return header, rows


def col_index(header: list[str], name: str) -> int:
    """헤더에서 칼럼명의 위치를 찾습니다. strip 비교."""
    for i, c in enumerate(header):
        if c.strip() == name:
            return i
    raise ValueError(f"Column '{name}' not found in header: {header}")


def main():
    parser = argparse.ArgumentParser(description="KIPRIS txt → 통합 메타데이터 JSON")
    parser.add_argument(
        "--raw-dir", type=Path, default=Path("data/raw_kipris"),
        help="raw_kipris/ 경로 (기본: data/raw_kipris)",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/kipris_metadata.json"),
        help="출력 JSON 경로 (기본: data/kipris_metadata.json)",
    )
    args = parser.parse_args()

    gongbo_dir = args.raw_dir / "gongbo"
    reg_dir = args.raw_dir / "registration"

    # ===== TB_KT10: 메인 테이블 =====
    h10, r10 = parse_table(gongbo_dir / "TB_KT10.txt", SEP_GONGBO)
    i_app = col_index(h10, "출원번호")
    i_app_date = col_index(h10, "출원일자")
    i_reg = col_index(h10, "등록번호")
    i_reg_date = col_index(h10, "등록일자")
    i_name_kr = col_index(h10, "상표한글명")
    i_name_en = col_index(h10, "상표영문명")
    i_gubun = col_index(h10, "상표구분코드명")

    print(f"[TB_KT10] {len(r10)} rows")

    # 출원번호 → 메인 정보, 출원번호 → 등록번호 매핑
    main_table: dict[str, dict] = {}
    app_to_reg: dict[str, Optional[str]] = {}

    gubun_dist = defaultdict(int)

    for row in r10:
        app_no = clean(row[i_app])
        if not app_no:
            continue
        gubun = clean(row[i_gubun]) or ""
        gubun_dist[gubun] += 1

        reg_no = clean(row[i_reg])
        main_table[app_no] = {
            "출원번호": app_no,
            "등록번호": reg_no,
            "출원일자": normalize_date(row[i_app_date]),
            "등록일자": normalize_date(row[i_reg_date]),
            "상표한글명": clean(row[i_name_kr]),
            "상표영문명": clean(row[i_name_en]),
            "상표구분": gubun,
        }
        app_to_reg[app_no] = reg_no

    print(f"[TB_KT10] 상표구분코드명 분포: {dict(gubun_dist)}")

    # ===== APPLICANT: 출원번호 → 출원인명 =====
    hAP, rAP = parse_table(gongbo_dir / "APPLICANT.txt", SEP_GONGBO)
    i_ap_app = col_index(hAP, "출원번호")
    i_ap_seq = col_index(hAP, "일련번호")
    i_ap_name = col_index(hAP, "출원인명")

    # 일련번호가 가장 작은(=대표) 출원인을 채택
    applicant_pick: dict[str, tuple[int, str]] = {}
    for row in rAP:
        app_no = clean(row[i_ap_app])
        name = clean(row[i_ap_name])
        if not app_no or not name:
            continue
        seq_raw = clean(row[i_ap_seq]) or "999999"
        try:
            seq = int(seq_raw)
        except ValueError:
            seq = 999999
        cur = applicant_pick.get(app_no)
        if cur is None or seq < cur[0]:
            applicant_pick[app_no] = (seq, name)

    applicant_table: dict[str, str] = {k: v[1] for k, v in applicant_pick.items()}
    print(f"[APPLICANT] 출원번호당 대표 출원인 매핑: {len(applicant_table)}")

    # ===== LAST_RG_HOLDER: 등록번호 → 최종권리권자성명 =====
    hRH, rRH = parse_table(reg_dir / "LAST_RG_HOLDER.txt", SEP_REGISTRATION)
    i_rh_reg = col_index(hRH, "등록번호")
    i_rh_name = col_index(hRH, "최종권리권자성명")

    # 같은 등록번호에 여러 권리자가 있을 수 있음. 첫 번째 항목 채택.
    holder_table: dict[str, str] = {}
    for row in rRH:
        reg_no = clean(row[i_rh_reg])
        name = clean(row[i_rh_name])
        if not reg_no or not name:
            continue
        holder_table.setdefault(reg_no, name)
    print(f"[LAST_RG_HOLDER] 등록번호당 대표 권리자 매핑: {len(holder_table)}")

    # ===== TB_KT11: 출원번호 → 비엔나분류설명 리스트 =====
    h11, r11 = parse_table(gongbo_dir / "TB_KT11.txt", SEP_GONGBO)
    i_v_app = col_index(h11, "출원번호")
    i_v_desc = col_index(h11, "비엔나분류설명")

    vienna_table: dict[str, list[str]] = defaultdict(list)
    for row in r11:
        app_no = clean(row[i_v_app])
        desc = clean(row[i_v_desc])
        if not app_no or not desc:
            continue
        if desc not in vienna_table[app_no]:  # 중복 제거, 입력 순 유지
            vienna_table[app_no].append(desc)
    print(f"[TB_KT11] 비엔나 매핑된 출원번호: {len(vienna_table)}")

    # ===== TB_KT15: 출원번호 → 류 집합, 유사군 집합 =====
    h15, r15 = parse_table(gongbo_dir / "TB_KT15.txt", SEP_GONGBO)
    i_g_app = col_index(h15, "출원번호")
    i_g_class = col_index(h15, "류")
    i_g_sim = col_index(h15, "유사군")

    class_table: dict[str, list[int]] = defaultdict(list)
    similar_table: dict[str, list[str]] = defaultdict(list)
    for row in r15:
        app_no = clean(row[i_g_app])
        if not app_no:
            continue
        c_raw = clean(row[i_g_class])
        if c_raw:
            try:
                c_int = int(c_raw)
                if c_int not in class_table[app_no]:
                    class_table[app_no].append(c_int)
            except ValueError:
                pass
        s_raw = clean(row[i_g_sim])
        if s_raw:
            # 유사군 칼럼에 콤마/공백 구분자로 여러 코드가 들어올 수 있음
            for token in s_raw.replace(",", " ").split():
                token = token.strip()
                if token and token not in similar_table[app_no]:
                    similar_table[app_no].append(token)
    print(f"[TB_KT15] 류 매핑: {len(class_table)}, 유사군 매핑: {len(similar_table)}")

    # ===== 도형 필터링 + 통합 =====
    trademarks = []
    excluded_non_dohyeong = 0
    for app_no, base in main_table.items():
        gubun = base.get("상표구분") or ""
        if gubun not in DOHYEONG_KEYWORDS:
            excluded_non_dohyeong += 1
            continue

        reg_no = base["등록번호"]
        entry = {
            "출원번호": app_no,
            "등록번호": reg_no,
            "이미지파일": f"{app_no}.png",
            "출원일자": base["출원일자"],
            "등록일자": base["등록일자"],
            "상표한글명": base["상표한글명"],
            "상표영문명": base["상표영문명"],
            "상표구분": gubun,
            "출원인": applicant_table.get(app_no),
            "최종권리자": holder_table.get(reg_no) if reg_no else None,
            "비엔나코드": vienna_table.get(app_no, []),
            "류": class_table.get(app_no, []),
            "유사군": similar_table.get(app_no, []),
        }
        trademarks.append(entry)

    # ===== 데이터셋 안내 정보 =====
    years = [
        int(t["출원일자"][:4])
        for t in trademarks
        if t["출원일자"] and t["출원일자"][:4].isdigit()
    ]
    if years:
        year_range = f"{min(years)} ~ {max(years)}"
    else:
        year_range = "미상"

    dataset = {
        "dataset_info": {
            "총_상표수": len(trademarks),
            "출원일자_범위": year_range,
            "데이터_기준": "KIPRIS 등록상표 공보",
            "생성일자": date.today().isoformat(),
        },
        "trademarks": trademarks,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

    # ===== 검증/요약 출력 =====
    print()
    print("=" * 60)
    print(" 통합 결과 요약")
    print("=" * 60)
    print(f"  도형 필터 통과: {len(trademarks)} / {len(main_table)}")
    print(f"  도형 외 제외 건수: {excluded_non_dohyeong}")
    print("  상표구분 분포 (통과분):")
    final_gubun = defaultdict(int)
    for t in trademarks:
        final_gubun[t["상표구분"]] += 1
    for k, v in sorted(final_gubun.items()):
        print(f"    {k}: {v}")
    print()
    print(f"  채워진 필드 카운트 (전체 {len(trademarks)} 중):")
    fields = ["등록번호", "등록일자", "상표한글명", "상표영문명",
              "출원인", "최종권리자"]
    for f_name in fields:
        n = sum(1 for t in trademarks if t.get(f_name))
        print(f"    {f_name:>10s}: {n}")
    for f_name in ["비엔나코드", "류", "유사군"]:
        n = sum(1 for t in trademarks if t.get(f_name))
        print(f"    {f_name:>10s}: {n} (비어있지 않은 건)")
    print()
    print(f"  출원일자 범위: {year_range}")
    print(f"  생성일자: {date.today().isoformat()}")
    print()
    print(f"  출력 파일: {args.output}")
    print(f"  파일 크기: {args.output.stat().st_size} bytes")


if __name__ == "__main__":
    main()
