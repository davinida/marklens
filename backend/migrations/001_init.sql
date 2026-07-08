-- MarkLens 초기 스키마 (백엔드-1)
-- 실행: backend/scripts/migrate_json_to_db.py 가 자동 적용 (멱등 — 재실행 안전)
--
-- 설계 근거 (TODO.pdf 백엔드-1):
--  * 출원번호가 PK (조인 키. 저장 전 반드시 appno.normalize_application_number 적용)
--  * 비엔나코드/류/유사군은 한 상표에 여러 개 → 배열 타입 (한 덩어리 문자열 금지
--    — X4 자카드 집합 연산과 GIN 인덱스 검색이 안 됨)
--  * 자주 조회할 컬럼(name_ko, applicant, image_key, similarity_codes)에 인덱스

CREATE TABLE IF NOT EXISTS trademark (
    application_no    TEXT PRIMARY KEY,              -- 정규화된 출원번호 (숫자 13자리)
    registration_no   TEXT,
    application_date  DATE,
    registration_date DATE,
    name_ko           TEXT,
    name_en           TEXT,
    mark_type         TEXT,                          -- 도형상표 / 도형복합
    applicant         TEXT,
    right_holder      TEXT,
    image_key         TEXT NOT NULL,                 -- 이미지 파일명 (FAISS 인덱스 메타와의 조인 키)
    vienna_codes      TEXT[]     NOT NULL DEFAULT '{}',
    nice_classes      SMALLINT[] NOT NULL DEFAULT '{}',
    similarity_codes  TEXT[]     NOT NULL DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- image_key 는 검색 경로(FAISS 결과 → 메타 조회)의 핵심 — 유니크 인덱스
CREATE UNIQUE INDEX IF NOT EXISTS idx_tm_image_key ON trademark (image_key);
CREATE INDEX IF NOT EXISTS idx_tm_name_ko   ON trademark (name_ko);
CREATE INDEX IF NOT EXISTS idx_tm_applicant ON trademark (applicant);
-- 배열 포함 검색(예: 특정 유사군을 가진 상표)용 GIN
CREATE INDEX IF NOT EXISTS idx_tm_simcodes  ON trademark USING GIN (similarity_codes);
CREATE INDEX IF NOT EXISTS idx_tm_vienna    ON trademark USING GIN (vienna_codes);

-- dataset_info(데이터 범위 안내 문구 등) 같은 단건 메타 저장소
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value JSONB NOT NULL
);
