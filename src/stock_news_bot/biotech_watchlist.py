"""2026년 임상 일정 워치리스트.

특정 바이오 종목의 2026년 주요 임상/기술이전 파이프라인 일정을 수동으로
큐레이션해 둔 데이터다. 뉴스 본문에서 자동으로 날짜를 추출하는
schedule_engine.extractor와 달리, 여기 있는 데이터는 회사 IR/기사를
근거로 미리 등록해 둔 것이라 뉴스에 날짜가 명시되어 있지 않아도
"이 종목은 이런 일정이 예정되어 있다"는 맥락을 항상 붙일 수 있다.

각 항목의 stage는 사실 기반으로만 채운다(추측 금지) — 이번에 채운
내용은 2026-09-06 기준 언론 보도(메디게이트뉴스, 하이불스, 전자신문,
딜사이트 등)를 근거로 했다. 진행 상황이 바뀌면 이 파일만 업데이트하면
된다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BiotechPipeline:
    company: str          # DART 등록 상장사명과 일치해야 매칭됨 (item.company)
    pipeline_name: str     # 파이프라인/약물 코드명
    event_type: str        # 임상, 기술이전, 승인 등
    expected_period: str   # "2026년 상반기", "10월경" 등 자연어 기간(정확한 날짜 불명 시)
    stage: str             # 현재 진행 단계 설명
    note: str              # 참고 사항(적응증, 파트너사 등)


# 회사명은 반드시 DART 정식 상장사명 기준으로 맞춘다 (match_company 매칭용).
BIOTECH_WATCHLIST: dict[str, list[BiotechPipeline]] = {
    "에이비엘바이오": [
        BiotechPipeline(
            company="에이비엘바이오",
            pipeline_name="ABL001 (토베시미그)",
            event_type="임상",
            expected_period="2026년 중",
            stage="컴퍼스 테라퓨틱스가 담도암 2차 치료제로 미국 2/3상(COMPANION-002) 진행 중",
            note="글로벌 개발·상업화 권리는 컴퍼스 테라퓨틱스 보유",
        ),
        BiotechPipeline(
            company="에이비엘바이오",
            pipeline_name="ABL301",
            event_type="임상",
            expected_period="2026년 중",
            stage="사노피에 기술이전, 파킨슨병 치료제로 임상 개시 예정",
            note="사노피 기술이전 파이프라인",
        ),
    ],
    "보로노이": [
        BiotechPipeline(
            company="보로노이",
            pipeline_name="VRN11",
            event_type="임상",
            expected_period="2026년 상반기(중간데이터), 연중 2상 진입 목표",
            stage="EGFR 변이 비소세포폐암 표적치료제, 글로벌 2상 진입 및 가속승인 목표",
            note="C797S 변이 대상 임상 1상 데이터 다수 공개(ORR 개선 추세)",
        ),
    ],
    "한올바이오파마": [
        BiotechPipeline(
            company="한올바이오파마",
            pipeline_name="IMVT-1402",
            event_type="임상",
            expected_period="2026년 중",
            stage="류마티스 관절염 2b/3상 및 전신 홍반성 루푸스 Pivotal 2상 결과 발표 예정",
            note="자가면역질환 치료제",
        ),
    ],
    "한미약품": [
        BiotechPipeline(
            company="한미약품",
            pipeline_name="듀얼아고니스트(MASH 치료제)",
            event_type="임상",
            expected_period="2026년 중",
            stage="MSD에 기술이전, MASH(대사이상성 지방간염) 임상 2b상 결과 발표 예정",
            note="비만합병증 관련 파이프라인",
        ),
    ],
    "리가켐바이오": [
        BiotechPipeline(
            company="리가켐바이오",
            pipeline_name="LCB84",
            event_type="임상",
            expected_period="2026년 중",
            stage="얀센에 기술이전한 ADC(항체-약물접합체), 임상 1상 완료 및 2상 개시 예정",
            note="얀센 기술이전 파이프라인",
        ),
    ],
    "퓨쳐켐": [
        BiotechPipeline(
            company="퓨쳐켐",
            pipeline_name="FC705",
            event_type="임상",
            expected_period="진행 중",
            stage="전립선암 방사선 치료제 후보물질, 미국 2a상 진행 중",
            note="방사성의약품(RPT) 파이프라인",
        ),
    ],
    "올릭스": [
        BiotechPipeline(
            company="올릭스",
            pipeline_name="OLX702A",
            event_type="임상",
            expected_period="2026년 중(2상 진행 예정)",
            stage="일라이릴리에 기술이전, 호주 1상 진행 중이며 2026년 2상 진행 예정",
            note="일라이릴리 기술이전 파이프라인",
        ),
    ],
    "코오롱티슈진": [
        BiotechPipeline(
            company="코오롱티슈진",
            pipeline_name="TG-C (구 인보사)",
            event_type="임상",
            expected_period="2026년 10월경",
            stage="골관절염 세포유전자치료제, 미국 두 번째 임상 3상 결과 공개 예정(첫 번째 3상은 통계적 유의성 미확보)",
            note="확증 임상(TGC-15302, TGC-12301)",
        ),
    ],
}


def get_pipelines(company: str) -> list[BiotechPipeline]:
    """회사명으로 워치리스트 파이프라인 목록을 조회한다. 없으면 빈 리스트."""
    return BIOTECH_WATCHLIST.get(company, [])


# ---------------------------------------------------------------------------
# 미등록 종목 보조판별(키워드 자동판별) — 위 BIOTECH_WATCHLIST에 없는 종목도
# 임상/허가 테마 키워드가 있으면 AI(analyze_watchlist_outlook)로 보조
# 전망을 생성할 수 있도록 남겨둔다. 정적 등록 종목이 우선이며, 이 함수는
# get_pipelines(company)가 빈 리스트일 때만 scheduler.py에서 사용된다.
# ---------------------------------------------------------------------------
BIOTECH_KEYWORDS = {
    "바이오", "제약", "신약", "신약개발", "신약허가", "CDMO", "ADC",
    "GLP-1", "위고비", "비만치료제", "임상", "임상1상", "임상2상", "임상3상",
    "임상시험", "임상시험계획", "임상성공", "임상실패", "FDA", "FDA승인",
    "FDA허가", "식약처", "품목허가", "허가신청", "IND", "NDA", "BLA",
    "항암제", "세포치료", "유전자치료", "알츠하이머", "백신", "항체",
    "바이오시밀러",
}


def is_biotech_watchlist_item(item) -> bool:
    """종목이 확인됐고(company) + 바이오 임상/허가 테마 키워드가 본문에
    있으면 (미등록 종목이라도) AI 보조 전망 대상으로 본다."""
    company = str(getattr(item, "company", "") or "").strip()
    if not company:
        return False
    text = f"{getattr(item, 'title', '')} {getattr(item, 'summary', '')}".lower()
    return any(kw.lower() in text for kw in BIOTECH_KEYWORDS)
