"""사진 표장 판정 — 표장 이미지가 실물·장면을 찍은 사진(간판·제품·입체물·포장·직물 등)인지
그래픽(평면 로고·문자·스캔)인지 CLIP 이미지 임베딩 하나로 가른다. 학습 특징
(ml/scripts/pairs_features.py 의 `사진A`·`사진B`)과 서비스가 같이 쓰는 공용 판정이다(통합 모델
설계 §7-4 — 사진이 낀 쌍은 이미지 축을 "관측 없음"으로 둔다. 서비스 연결은 다음 단계).

방법: 서비스가 이미 계산하는 OpenCLIP ViT-B/32 이미지 임베딩 e(L2 정규화, `src.embedding`)와 방향
벡터 d 의 내적 score = e·d. d = normalize(mean(사진 문장 임베딩)) − normalize(mean(그래픽 문장
임베딩)) — 사진 쪽 문장 묶음과 그래픽 쪽 문장 묶음 가운데 어느 쪽에 더 가까운가. score 가
THRESHOLD(0) 보다 크면 사진. d 는 `shared/model/photo_direction_v1.json` 에 고정해 두어 판정에는
텍스트 인코더가 필요 없다(재생성: `ml/venv/bin/python -m src.photo_mark`, ml/ 에서).

왜 임베딩인가: 추출 때 쓰던 화소 통계 추정(trials_extract_images._photo_like — 64px 축소본의 색 수·
중간 톤 비율)은 눈으로 확인한 30쌍 중 20쌍만 맞았다(JPEG 잡음이 낀 단색 배경·계조가 있는 로고를
사진으로, 흑백 사진·흰 배경 제품 사진을 그래픽으로). 이 판정은 문장을 고친 뒤 새로 뽑은 30쌍에서
27쌍(이미지 55/60)이 맞았다(2026-11-19, 설계 §7-4). 경계: 균일한 배경에 인쇄된 글자를 바짝 자른
라벨·평면 포장 도안·금박 카드처럼 사진과 그래픽 사이에 있는 이미지는 점수가 0 근처다.

torch 를 import 하지 않는다(방향 재생성 main 만 지연 import) — numpy 만으로 판정한다.
"""

from __future__ import annotations

import functools
import json
import os
from pathlib import Path

import numpy as np

from src.contracts import EMBEDDING_CONTRACT_VERSION, EMBEDDING_DIM, MODEL_NAME, PRETRAINED

__all__ = [
    "PHOTO_PROMPTS", "GRAPHIC_PROMPTS", "THRESHOLD", "DIRECTION_VERSION", "DEFAULT_DIRECTION_PATH",
    "ENV_DIRECTION_PATH", "build_direction", "direction_payload", "load_direction", "photo_score",
    "is_photo", "pair_has_photo",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIRECTION_PATH = REPO_ROOT / "shared" / "model" / "photo_direction_v1.json"
ENV_DIRECTION_PATH = "MARKLENS_PHOTO_DIRECTION"
DIRECTION_VERSION = "photo_direction_v1"
THRESHOLD = 0.0  # score > 0: 사진 쪽 문장 묶음에 더 가깝다
# 문장 묶음은 판정의 정의다 — 바꾸면 방향 파일을 다시 만들고 표본 확인을 다시 한다.
PHOTO_PROMPTS = (
    "a photograph of a storefront signboard",
    "a photo of a product",
    "a photograph of a real object",
    "a photo taken with a camera",
    "a photo of a shop sign on a building",
    "a photo of product packaging",
    "a photo of a stuffed toy",
    "a photo of clothing with a printed logo",
)
GRAPHIC_PROMPTS = (
    "a flat logo design on a white background",
    "a vector logo",
    "plain black text on a white background",
    "a trademark logo graphic",
    "a scanned black and white wordmark",
    "a simple emblem illustration",
    "typography on a plain background",
    "a clip art icon",
)


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        raise ValueError("photo_mark: 영벡터는 정규화할 수 없습니다")
    return vector / norm


def build_direction(encode_text) -> np.ndarray:
    """방향 벡터 d. encode_text(문장 목록) → (n, EMBEDDING_DIM) 배열(행마다 텍스트 임베딩;
    정규화는 여기서 한다)."""
    def center(prompts) -> np.ndarray:
        rows = np.asarray(encode_text(list(prompts)), dtype=np.float64)
        if rows.ndim != 2 or rows.shape[0] != len(prompts):
            raise ValueError("photo_mark: encode_text 는 (문장 수, 차원) 배열을 돌려줘야 합니다")
        return _unit(np.stack([_unit(row) for row in rows]).mean(axis=0))

    return (center(PHOTO_PROMPTS) - center(GRAPHIC_PROMPTS)).astype(np.float32)


def direction_payload(direction: np.ndarray) -> dict:
    """방향 벡터 파일 내용(JSON) — 모델·임베딩 계약과 문장 묶음을 함께 적는다."""
    return {
        "version": DIRECTION_VERSION,
        "model": MODEL_NAME, "pretrained": PRETRAINED,
        "embedding_contract": EMBEDDING_CONTRACT_VERSION,
        "threshold": THRESHOLD,
        "rule": "score = 이미지 임베딩 · direction; score > threshold 이면 사진",
        "prompts": {"photo": list(PHOTO_PROMPTS), "graphic": list(GRAPHIC_PROMPTS)},
        "direction": [round(float(value), 7) for value in np.asarray(direction).ravel()],
    }


def resolve_direction_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path:
        return Path(path)
    env = os.environ.get(ENV_DIRECTION_PATH, "").strip()
    return Path(env) if env else DEFAULT_DIRECTION_PATH


@functools.lru_cache(maxsize=4)
def _load_cached(path_text: str) -> tuple[np.ndarray, float]:
    data = json.loads(Path(path_text).read_text(encoding="utf-8"))
    if data.get("version") != DIRECTION_VERSION:
        raise ValueError(f"photo_mark: version 은 {DIRECTION_VERSION} 이어야 합니다")
    for key, expected in (("model", MODEL_NAME), ("pretrained", PRETRAINED),
                          ("embedding_contract", EMBEDDING_CONTRACT_VERSION)):
        if data.get(key) != expected:
            raise ValueError(f"photo_mark: {key} 가 임베딩 계약({expected})과 다릅니다")
    direction = np.asarray(data.get("direction"), dtype=np.float32)
    if direction.shape != (EMBEDDING_DIM,) or not np.all(np.isfinite(direction)):
        raise ValueError(f"photo_mark: direction 은 {EMBEDDING_DIM}차원 숫자 벡터여야 합니다")
    threshold = data.get("threshold")
    if not isinstance(threshold, (int, float)):
        raise ValueError("photo_mark: threshold 는 숫자여야 합니다")
    direction.setflags(write=False)
    return direction, float(threshold)


def load_direction(path: str | os.PathLike[str] | None = None) -> tuple[np.ndarray, float]:
    """(방향 벡터, 임계값). 경로: 인자 > MARKLENS_PHOTO_DIRECTION > shared/model/…(캐시)."""
    return _load_cached(str(resolve_direction_path(path)))


def photo_score(embedding, *, direction: np.ndarray | None = None) -> float:
    """이미지 임베딩(L2 정규화, EMBEDDING_DIM)의 사진 점수 — 양수면 사진 쪽."""
    vector = np.asarray(embedding, dtype=np.float32).ravel()
    if vector.shape != (EMBEDDING_DIM,):
        raise ValueError(f"photo_mark: 임베딩은 {EMBEDDING_DIM}차원이어야 합니다")
    if direction is None:
        direction = load_direction()[0]
    return float(vector @ direction)


def is_photo(embedding, *, direction: np.ndarray | None = None,
             threshold: float | None = None) -> bool:
    """사진 표장인가(score > threshold)."""
    if direction is None or threshold is None:
        loaded, loaded_threshold = load_direction()
        direction = loaded if direction is None else direction
        threshold = loaded_threshold if threshold is None else threshold
    return photo_score(embedding, direction=direction) > float(threshold)


def pair_has_photo(embedding_a, embedding_b) -> bool:
    """쌍에 사진이 끼었는가 — 한쪽이라도 사진이면 이미지 축을 관측 없음으로 둔다."""
    return is_photo(embedding_a) or is_photo(embedding_b)


def main(argv: list[str] | None = None) -> int:
    """방향 파일 재생성(실제 CLIP 텍스트 인코더, 가중치 캐시 필요)."""
    import argparse

    parser = argparse.ArgumentParser(description="사진 판정 방향 벡터 재생성")
    parser.add_argument("--out", type=Path, default=DEFAULT_DIRECTION_PATH)
    args = parser.parse_args(argv)

    import open_clip
    import torch

    from src import embedding

    model, _ = embedding._load_model()  # noqa: SLF001 - 서비스와 같은 모델 인스턴스
    tokenizer = open_clip.get_tokenizer(MODEL_NAME)

    def encode_text(prompts: list[str]) -> np.ndarray:
        with torch.no_grad():
            return model.encode_text(tokenizer(prompts)).cpu().numpy()

    payload = direction_payload(build_direction(encode_text))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{args.out} — {len(payload['direction'])}차원, 문장 {len(PHOTO_PROMPTS)}+"
          f"{len(GRAPHIC_PROMPTS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
