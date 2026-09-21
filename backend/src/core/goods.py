"""상품↔유사군 변환표 서비스 — 기동 시 적재, GET /goods/search·/goods/classes 의 데이터 소스.

phonetic_search.py 와 같은 모듈 전역 state 패턴. 차이점: 변환표 파일이 없어도 서버는 기동하고
(state.ready=False, state.error 에 이유) 두 엔드포인트만 503 을 낸다 — /name-check 가 KIPRIS 키
없이 503 을 내는 것과 같은 방식. 적재·검색 자체는 ml/src/axes/goods_map.py(lru_cache, 경로당 1회).

실측(2026-09-21, 이 Mac, 91,591건 + aliases 230,598개): 적재 0.4~0.6초(.gz), 객체 메모리 약 80MB
(파싱 중 RSS 피크 약 270MB), 검색 3~5ms(1~2글자 광범위 질의 최대 약 50ms). KIPRIS·torch 와 무관하다.
"""

import logging
import sys
import time
from dataclasses import dataclass

from . import config, paths

# ml/src 를 import 경로에 둔다 (engine.py·phonetic_search.py 와 같은 패턴). 표준 라이브러리만 쓴다.
if str(paths.ML_ROOT) not in sys.path:
    sys.path.insert(0, str(paths.ML_ROOT))

from src.axes.goods_map import (  # noqa: E402
    NICE_CLASS_TITLES,
    SOURCE_LABEL,
    GoodsMap,
    Match,
    load_goods_map,
)

logger = logging.getLogger(__name__)

SOURCE = SOURCE_LABEL  # 응답 source 필드: "고시상품명칭 13판(2026)"


@dataclass
class GoodsState:
    goods_map: GoodsMap | None = None
    ready: bool = False
    error: str = ""  # 준비 실패 이유 — 503 detail 과 로그에 쓴다
    path: str = ""
    entry_count: int = 0
    alias_count: int = 0
    load_ms: float = 0.0


# 모듈 전역 상태. main.py lifespan 이 load_all() 로 채운다.
state = GoodsState()


def reset() -> None:
    """테스트·재적재용: 상태를 비운다."""
    state.goods_map = None
    state.ready = False
    state.error = ""
    state.path = ""
    state.entry_count = 0
    state.alias_count = 0
    state.load_ms = 0.0


def load_all(path: str | None = None) -> GoodsState:
    """변환표를 적재한다. 실패해도 예외를 밖으로 내지 않는다 — 서버는 뜨고 /goods/* 만 503."""
    started = time.perf_counter()
    target = path or config.GOODS_MAP_PATH or None
    try:
        goods_map = load_goods_map(target)
    except FileNotFoundError as exc:
        reset()
        state.error = (
            "상품↔유사군 변환표 파일이 없습니다. shared/goods_map/README.md 절차로 "
            "goods_map.json(.gz) 을 만들거나 MARKLENS_GOODS_MAP_PATH 를 지정하세요."
        )
        logger.warning("상품 변환표 미적재 — /goods/* 는 503: %s", exc)
        return state
    except Exception:
        reset()
        state.error = "상품↔유사군 변환표를 읽는 중 오류가 났습니다(서버 로그 참조)."
        logger.exception("상품 변환표 적재 실패 — /goods/* 는 503")
        return state

    state.goods_map = goods_map
    state.ready = True
    state.error = ""
    state.path = str(goods_map.path)
    state.entry_count = len(goods_map)
    state.alias_count = goods_map.alias_count
    state.load_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "상품 변환표 준비: %d건 (aliases %d개, %s, %.0fms)",
        state.entry_count,
        state.alias_count,
        state.path,
        state.load_ms,
    )
    return state


def _require() -> GoodsMap:
    if not state.ready or state.goods_map is None:
        raise RuntimeError(state.error or "상품↔유사군 변환표가 준비되지 않았습니다.")
    return state.goods_map


def search(query: str, limit: int, nice_class: int | None) -> tuple[list[Match], int, float]:
    """(상위 limit 개, 전체 일치 건수, 소요 ms). 정규화·순위는 로더에 맡긴다."""
    goods_map = _require()
    started = time.perf_counter()
    matches, total = goods_map.search_with_total(query, limit, nice_class)
    return matches, total, (time.perf_counter() - started) * 1000


def classes() -> list[dict]:
    """45개 류 전부: {nice_class, title, count}."""
    goods_map = _require()
    return [
        {
            "nice_class": row["nice_class"],
            "title": NICE_CLASS_TITLES[row["nice_class"]],
            "count": row["count"],
        }
        for row in goods_map.classes()
    ]
