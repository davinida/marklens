"""/name-check 질의 캐시(TTLCache) 동작 검증.

배경: 수제 dict 캐시는 상한이 없어 서로 다른 질의가 쌓이면 무한 성장했고,
지연 방출(조회 시에만 삭제)이라 안 읽는 항목은 영원히 남았다.
TTLCache 교체 후 보장해야 하는 것: (1) 항목 수 상한 (2) TTL 만료.

주의: 이 테스트는 app 전체를 띄우지 않는다 (namecheck 모듈은 torch/faiss 와
무관하게 단독 import 가능).
"""

from cachetools import TTLCache

from backend.src.api import namecheck


def test_cache_is_bounded(monkeypatch):
    """maxsize 를 넘겨 넣어도 캐시 크기가 상한을 넘지 않는다."""
    small = TTLCache(maxsize=3, ttl=3600)
    monkeypatch.setattr(namecheck, "_cache", small)

    for i in range(10):
        namecheck._cache_put(f"질의{i}", {"n": i})

    assert len(small) <= 3
    # 가장 최근 항목은 남아 있어야 한다
    assert namecheck._cache_get("질의9") == {"n": 9}


def test_cache_ttl_expiry_with_fake_clock(monkeypatch):
    """TTL 이 지나면 같은 키 조회가 None 을 반환한다 (가짜 시계로 검증)."""
    now = [1000.0]
    fake_clock = lambda: now[0]  # noqa: E731

    expiring = TTLCache(maxsize=16, ttl=60, timer=fake_clock)
    monkeypatch.setattr(namecheck, "_cache", expiring)

    namecheck._cache_put("스타벅스", {"exact_registered_count": 4})
    assert namecheck._cache_get("스타벅스") == {"exact_registered_count": 4}

    now[0] += 61  # TTL(60s) 경과
    assert namecheck._cache_get("스타벅스") is None


def test_cache_hit_within_ttl(monkeypatch):
    """TTL 안에서는 캐시가 유지된다."""
    now = [0.0]
    expiring = TTLCache(maxsize=16, ttl=60, timer=lambda: now[0])
    monkeypatch.setattr(namecheck, "_cache", expiring)

    namecheck._cache_put("커피빈", {"exact_registered_count": 0})
    now[0] += 59
    assert namecheck._cache_get("커피빈") == {"exact_registered_count": 0}
