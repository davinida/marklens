"""사진 표장 판정(src.photo_mark) 테스트 — 방향 벡터 파일과 numpy 만으로(CLIP 적재 없음)."""

from __future__ import annotations

import json

import numpy as np
import pytest
from src import photo_mark as pm
from src.contracts import EMBEDDING_DIM


def _unit(vector: np.ndarray) -> np.ndarray:
    return (vector / np.linalg.norm(vector)).astype(np.float32)


def test_shipped_direction_matches_module_definition():
    """저장소의 방향 파일은 모듈의 문장 묶음·임계값으로 만든 것이어야 한다(문장을 바꾸면 파일을
    다시 만들고 표본 확인을 다시 한다)."""
    data = json.loads(pm.DEFAULT_DIRECTION_PATH.read_text(encoding="utf-8"))
    assert data["version"] == pm.DIRECTION_VERSION
    assert data["prompts"] == {"photo": list(pm.PHOTO_PROMPTS),
                               "graphic": list(pm.GRAPHIC_PROMPTS)}
    assert data["threshold"] == pm.THRESHOLD == 0.0
    direction, threshold = pm.load_direction()
    assert direction.shape == (EMBEDDING_DIM,) and threshold == 0.0
    assert not direction.flags.writeable  # 캐시된 배열을 호출자가 바꾸지 못한다
    assert 0.1 < float(np.linalg.norm(direction)) < 2.0  # 단위 벡터 둘의 차


def test_score_sign_decides_photo():
    direction, _ = pm.load_direction()
    toward = _unit(direction)
    away = _unit(-direction)
    assert pm.photo_score(toward) > 0 > pm.photo_score(away)
    assert pm.is_photo(toward) and not pm.is_photo(away)
    assert pm.pair_has_photo(away, toward) and pm.pair_has_photo(toward, away)
    assert not pm.pair_has_photo(away, away)
    # 임계값은 "초과" — 점수가 임계값과 같으면 사진이 아니다
    orthogonal = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    assert not pm.is_photo(orthogonal)
    assert pm.is_photo(away, threshold=-10.0) and not pm.is_photo(toward, threshold=10.0)
    with pytest.raises(ValueError):
        pm.photo_score(np.zeros(8))


def test_build_direction_is_difference_of_normalized_prompt_centers():
    rng = np.random.default_rng(0)
    table = {prompt: rng.normal(size=EMBEDDING_DIM) * (1 + i)  # 크기가 달라도 정규화 뒤 평균
             for i, prompt in enumerate(pm.PHOTO_PROMPTS + pm.GRAPHIC_PROMPTS)}

    def encode(prompts):
        return np.stack([table[prompt] for prompt in prompts])

    def center(prompts):
        rows = np.stack([table[p] / np.linalg.norm(table[p]) for p in prompts]).mean(axis=0)
        return rows / np.linalg.norm(rows)

    direction = pm.build_direction(encode)
    expected = center(pm.PHOTO_PROMPTS) - center(pm.GRAPHIC_PROMPTS)
    assert direction.dtype == np.float32 and direction.shape == (EMBEDDING_DIM,)
    np.testing.assert_allclose(direction, expected, atol=1e-6)
    # 사진 문장 쪽 임베딩은 양수, 그래픽 문장 쪽은 음수
    assert pm.photo_score(_unit(center(pm.PHOTO_PROMPTS)), direction=direction) > 0
    assert pm.photo_score(_unit(center(pm.GRAPHIC_PROMPTS)), direction=direction) < 0
    with pytest.raises(ValueError):
        pm.build_direction(lambda prompts: np.zeros((1, EMBEDDING_DIM)))


def test_payload_round_trip_and_validation(tmp_path, monkeypatch):
    direction = _unit(np.arange(1, EMBEDDING_DIM + 1, dtype=np.float64))
    payload = pm.direction_payload(direction)
    path = tmp_path / "direction.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded, threshold = pm.load_direction(path)
    np.testing.assert_allclose(loaded, direction, atol=1e-6)
    assert threshold == pm.THRESHOLD
    monkeypatch.setenv(pm.ENV_DIRECTION_PATH, str(path))  # 경로: 인자 > 환경변수 > 기본
    assert pm.resolve_direction_path() == path
    assert pm.resolve_direction_path(tmp_path / "other.json") == tmp_path / "other.json"
    monkeypatch.delenv(pm.ENV_DIRECTION_PATH)
    assert pm.resolve_direction_path() == pm.DEFAULT_DIRECTION_PATH

    def broken(name: str, **changes) -> str:
        target = tmp_path / name
        target.write_text(json.dumps({**payload, **changes}), encoding="utf-8")
        return str(target)

    for name, changes in (("version.json", {"version": "photo_direction_v0"}),
                          ("model.json", {"model": "ViT-L-14"}),
                          ("contract.json", {"embedding_contract": "other"}),
                          ("dim.json", {"direction": [0.1, 0.2]}),
                          ("nan.json", {"direction": [float("nan")] * EMBEDDING_DIM}),
                          ("threshold.json", {"threshold": "0"})):
        with pytest.raises(ValueError):
            pm.load_direction(broken(name, **changes))


def test_module_does_not_import_torch_at_import_time():
    """판정은 numpy 만 쓴다 — 방향 재생성(main)만 torch·open_clip 을 지연 import."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(pm))
    top_level = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level.add(node.module.split(".")[0])
    assert not top_level & {"torch", "open_clip", "faiss"}
