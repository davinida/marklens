"""결합 규칙 v0.3 가속(2026-11-22)의 결과 불변 — 고치기 전 계산을 그대로 옮긴 기준 구현과 같은지.

가속은 판정(유사도 ≥ 0.9 를 넘었나)만 바꾸지 않는 범위에서 한다: 정수 거리 상한(`_max_distance`),
띠 편집거리(`_within_distance`), (토큰, 토큰열) LRU, 맞아도 더할 토큰이 없는 비교 건너뛰기.
"""

from __future__ import annotations

import itertools
import random
from concurrent.futures import ThreadPoolExecutor

from src.axes import distinctiveness as dx
from src.axes.goods_map import GoodsEntry, GoodsMap
from src.axes.x1_phonetic import pronunciation_candidates
from src.axes.x2_ortho import decompose_jamo

GOODS = GoodsMap([GoodsEntry("커피", 30, ("G0301",)), GoodsEntry("신발", 25, ("G2701",))])
WEAK = ("line", "royal", "bee", "cool", "touch", "quick", "pass", "slim", "gate", "혹", "달린",
        "신발", "커피", "블루", "카페")
VOCAB = WEAK + ("zorbix", "qwzy", "slimline", "quickpath", "royalebee", "혹달린신발", "쿨터치",
                "퀵패스", "블루커피", "블루카페", "슬림라인", "coolttouch", "zorbixgate", "삼성")


def _model() -> dx.Distinctiveness:
    names, classes = dx.goods_index(GOODS)
    stats = {"zorbix": (0, 0), "qwzy": (5, 10), **{token: (20, 40) for token in WEAK}}
    return dx.Distinctiveness(stats, famous={"삼성"}, goods_names=names, code_classes=classes,
                              descriptive={})


def _reference_match(single: str, run: list[str]) -> bool:
    """고치기 전 `_combined_match` 그대로(캐시·거리 상한 없음)."""
    joined = "".join(run)
    if single == joined:
        return True
    if dx._string_similarity(single, joined) >= dx.COMBINED_SIMILARITY:
        return True
    single_readings = pronunciation_candidates(single) or [single]
    lists = [pronunciation_candidates(token) or [token] for token in run]
    run_readings = []
    for parts in itertools.product(*lists):
        run_readings.append("".join(parts))
        if len(run_readings) >= dx.COMBINED_READINGS_CAP:
            break
    if set(single_readings) & set(run_readings):
        return True
    return any(dx._string_similarity(left, right) >= dx.COMBINED_SIMILARITY
               for left in single_readings for right in run_readings)


def _reference_single_match(model: dx.Distinctiveness, name_a: str, name_b: str,
                            goods=None) -> frozenset[str]:
    """고치기 전 `Distinctiveness.combined_single_match` 그대로(건너뛰기 없음)."""
    withheld: set[str] = set()
    for split in (True, False):
        judged = {name: model.judge_name(name, goods, split=split) for name in (name_a, name_b)}
        for spaced, other in ((name_a, name_b), (name_b, name_a)):
            tokens = [j.token for j in judged[spaced]]
            weak = {j.token for j in judged[spaced] if j.score < model.theta}
            if len(tokens) < 2 or not weak:
                continue
            for start in range(len(tokens) - 1):
                for stop in range(start + 2, len(tokens) + 1):
                    run = tokens[start:stop]
                    run_weak = [token for token in run if token in weak]
                    if not run_weak:
                        continue
                    for single in judged[other]:
                        if _reference_match(single.token, run):
                            withheld.update(run_weak)
                            if single.score < model.theta:
                                withheld.add(single.token)
    return frozenset(withheld)


def _random_text(rng: random.Random, length: int) -> str:
    jamo = decompose_jamo("가나다라마바사아자차카타파하")
    alphabet = "abcdeilnorst01" if rng.random() < 0.5 else jamo
    return "".join(rng.choice(alphabet) for _ in range(length))


def _pairs() -> list[tuple[str, str]]:
    rng = random.Random(0)
    known = [("슬림라인", "Slim Line"), ("SLIMLINE", "Slim Line"),
             ("QUICKPATH", "퀵패스 QUICK PASS"), ("ROYALEBEE", "ROYAL BEE"),
             ("쿨터치", "COOL TOUCH"), ("혹달린신발", "신광준의 혹 달린 신발"),
             ("퀵패스 QUICKPATH", "Zorbix QUICK PASS"),
             ("로얄비 ROYALEBEE", "Zorbix ROYAL BEE")]
    made = [(" ".join(rng.choice(VOCAB) for _ in range(rng.randint(1, 7))),
             " ".join(rng.choice(VOCAB) for _ in range(rng.randint(1, 7)))) for _ in range(300)]
    return known + made


def test_max_distance_is_the_similarity_formula_as_an_integer_bound():
    for longest in range(1, 301):
        bound = dx._max_distance(longest)
        for distance in range(longest + 1):
            assert (1.0 - distance / longest >= dx.COMBINED_SIMILARITY) == (distance <= bound)


def test_banded_distance_decides_like_the_full_edit_distance():
    rng = random.Random(1)
    for _ in range(3000):
        left = _random_text(rng, rng.randint(0, 22))
        right = left if rng.random() < 0.2 else _random_text(rng, rng.randint(0, 22))
        if rng.random() < 0.3 and right:  # 거리 1–2 의 경계 근처
            index = rng.randrange(len(right))
            right = right[:index] + rng.choice("xy") + right[index + 1:]
        full = dx._edit_distance(left, right)
        for limit in range(-1, max(len(left), len(right)) + 2):
            assert dx._within_distance(left, right, limit) == (full <= limit), (left, right, limit)


def test_similar_decides_like_string_similarity():
    rng = random.Random(2)
    syllables = "슬림라인퀵패스혹달린신발블루커피카페로얄비쿨터치"
    for _ in range(3000):
        size = rng.randint(0, 12)
        left = "".join(rng.choice(syllables + "abcxyz") for _ in range(size))
        right = left
        for _ in range(rng.randint(0, 2)):
            if right:
                index = rng.randrange(len(right))
                right = right[:index] + rng.choice(syllables + "q") + right[index + 1:]
        expected = dx._string_similarity(left, right) >= dx.COMBINED_SIMILARITY
        assert dx._similar(left, right) == expected, (left, right)


def test_combined_match_equals_reference_on_runs():
    rng = random.Random(3)
    for _ in range(400):
        run = [rng.choice(VOCAB) for _ in range(rng.randint(2, 5))]
        single = rng.choice(VOCAB + ("".join(run),))
        assert dx._combined_match(single, run) == _reference_match(single, run), (single, run)


def test_combined_single_match_equals_reference_loop():
    model = _model()
    for name_a, name_b in _pairs():
        for goods in (None, {"G0301"}):
            expected = _reference_single_match(model, name_a, name_b, goods)
            assert model.combined_single_match(name_a, name_b, goods) == expected, (name_a, name_b)


def test_combined_caches_are_bounded_and_safe_across_threads():
    model = _model()
    pairs = _pairs()
    for cached in (dx._combined_match_cached, dx._joined_readings_cached, dx._readings, dx._jamo):
        assert cached.cache_info().maxsize == dx.COMBINED_CACHE_SIZE
        cached.cache_clear()
    sequential = [model.combined_single_match(a, b) for a, b in pairs]
    dx._combined_match_cached.cache_clear()
    with ThreadPoolExecutor(max_workers=8) as pool:
        threaded = list(pool.map(lambda pair: model.combined_single_match(*pair), pairs * 3))
    assert threaded == sequential * 3


def _reference_syllable_sim(x: str, y: str) -> float:
    """고치기 전 `x1_phonetic._syllable_sim_cached` 본문 그대로."""
    from src.axes import x1_phonetic as x1

    a = x1._syllables_only(x)[:x1.MAX_SYLLABLES]
    b = x1._syllables_only(y)[:x1.MAX_SYLLABLES]
    if not a or not b:
        return 0.0
    m, k = len(a), len(b)
    weights = x1._position_weights(max(m, k))
    indel = x1.COST_INDEL
    prev = [0.0] * (k + 1)
    for j in range(1, k + 1):
        prev[j] = prev[j - 1] + indel * weights[0]
    for i in range(1, m + 1):
        cur = [prev[0] + indel * weights[0]] + [0.0] * k
        ai = a[i - 1]
        for j in range(1, k + 1):
            sub = prev[j - 1] + x1._sub_cost(ai, b[j - 1]) * weights[min(i - 1, j - 1)]
            delete = prev[j] + indel * weights[min(i - 1, j)]
            insert = cur[j - 1] + indel * weights[min(i, j - 1)]
            cur[j] = min(sub, delete, insert)
        prev = cur
    max_distance = indel * sum(weights)
    return max(0.0, min(1.0, 1.0 - prev[k] / max_distance))


def test_x1_syllable_dp_is_bit_identical_to_the_original():
    from src.axes import x1_phonetic as x1

    rng = random.Random(4)
    syllables = ("스타벅스커피블루퀵패스슬림라인혹달린신발굽네치킨"
                 "빽다방파리바게뜨맛있는만두원조장수손")
    fast = x1._syllable_sim_cached.__wrapped__
    for _ in range(20000):
        left = "".join(rng.choice(syllables + " a1") for _ in range(rng.randint(0, 24)))
        right = left
        for _ in range(rng.randint(0, 4)):
            index = rng.randrange(len(right) + 1)
            right = right[:index] + rng.choice(syllables) + right[index:]
        if rng.random() < 0.3:
            right = "".join(rng.choice(syllables) for _ in range(rng.randint(0, 24)))
        assert repr(fast(left, right)) == repr(_reference_syllable_sim(left, right)), (left, right)
