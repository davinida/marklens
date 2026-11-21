"""검색 응답이 함께 싣는 데이터셋 안내(`dataset_info`) — 통합 검색 v2·발음·관념 검색 공용.

한글 필드명은 KIPRIS 원본 데이터 구조와 일관되도록 그대로 유지합니다.
"""

from pydantic import BaseModel


class DatasetInfo(BaseModel):
    """KIPRIS 데이터셋 안내 정보."""

    총_상표수: int
    출원일자_범위: str
    데이터_기준: str
    생성일자: str
