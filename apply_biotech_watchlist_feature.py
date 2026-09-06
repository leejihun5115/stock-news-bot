#!/usr/bin/env python3
"""
바이오 워치리스트(임상/허가 테마 자동판별 + AI 전망) 기능 배선
+ models.py 누락 필드(deep_dive_business/facts/checkpoints) 선행 수정을
한 파일로 통합한 배포 스크립트.

【왜 통합했는가】
원래 이 기능은 patch_models_deepdive_fix.py(선행 패치)가 먼저 적용돼
models.py에 deep_dive_checkpoints 필드가 이미 있다고 가정하고 만들어져
있었다. 그런데 실제 코드베이스를 점검해보니:

  - scheduler.py는 이미 item.deep_dive_business / deep_dive_facts /
    deep_dive_checkpoints 세 필드에 값을 대입하고 있다(AI 심층분석 결과 저장).
  - 그런데 models.py의 NewsItem은 @dataclass(slots=True)인데 정작 이
    세 필드가 전혀 선언되어 있지 않다.

즉, item.company가 있고 AI 심층분석이 성공할 때마다
"AttributeError: 'NewsItem' object has no attribute 'deep_dive_business'"가
발생하고 있었고, 이게 scheduler.py의 넓은 except Exception:에 걸려
"AI 심층분석 실패"로 조용히 로그만 남고 있었을 가능성이 높다(선행조건
패치가 실제로는 적용되지 않은 상태였던 것으로 보임).

그래서 이 스크립트는 별도 선행 스크립트를 요구하지 않고, models.py에
누락된 4개 필드(deep_dive_business/facts/checkpoints + watchlist_outlook)를
한 번에 추가한 뒤, 나머지 배선(llm_analyzer.py/scheduler.py/notifier.py +
biotech_watchlist.py 신규 생성)을 그대로 진행한다.

biotech_watchlist.py는 이 스크립트 안에 전체 내용이 포함되어 있어
별도 파일을 함께 올릴 필요가 없다 — 이 스크립트 하나만 VM에 올려서
실행하면 된다.

기존 배포 관례(백업 생성 → 앵커 매칭 패치 → py_compile 검사 → 실패 시
전체 자동 원복)를 따른다. 하나라도 실패하면 이미 적용된 나머지도 전부
원래대로 되돌린다(부분 적용 상태로 남기지 않는다).
"""
from __future__ import annotations

import py_compile
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path.home() / "stock-news-bot/src/stock_news_bot"
MODELS = ROOT / "models.py"
LLM_ANALYZER = ROOT / "cogs/llm_analyzer.py"
SCHEDULER = ROOT / "cogs/scheduler.py"
NOTIFIER = ROOT / "cogs/notifier.py"
BIOTECH_WATCHLIST = ROOT / "biotech_watchlist.py"

STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

BIOTECH_WATCHLIST_CONTENT = '''"""2026년 임상 일정 워치리스트.

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
'''

# ---------------------------------------------------------------------------
# 0) models.py — 누락된 deep_dive_* 3필드 + 신규 watchlist_outlook 1필드,
#    총 4개를 NewsItem(slots=True)에 한 번에 추가한다.
#    (선행 패치가 있었어야 할 deep_dive_checkpoints 등이 실제로는
#    존재하지 않아서, 이 스크립트가 그 역할까지 함께 한다.)
# ---------------------------------------------------------------------------
MODELS_OLD = '''    contract_impact: ContractImpact | None = None  # 계약 규모 비교 데이터(선택)
'''
MODELS_NEW = '''    contract_impact: ContractImpact | None = None  # 계약 규모 비교 데이터(선택)
    deep_dive_business: str = ""  # AI 심층분석: 회사 핵심 사업
    deep_dive_facts: list[str] = field(default_factory=list)  # AI 심층분석: 팩트 기반 핵심 요약
    deep_dive_checkpoints: list[str] = field(default_factory=list)  # 향후 체크포인트
    watchlist_outlook: list[str] = field(default_factory=list)  # 바이오 워치리스트 임상/허가 마일스톤 전망
'''

# ---------------------------------------------------------------------------
# 1) llm_analyzer.py — 3곳 삽입: dataclass / parser / prompt+함수
# ---------------------------------------------------------------------------
LLM_DATACLASS_OLD = '''@dataclass(slots=True)
class DeepDiveAnalysis:
    """AI 심층분석(딥다이브) 결과. 회사 핵심 사업 + 팩트 기반 핵심 요약 +
    메인 브리핑 카드용 체크포인트. 관련주(피어그룹)는 AI가 만들지 않고
    data/peer_groups.py의 정적 등록 데이터를 notifier.py가 별도로 붙인다."""
    business: str = ""
    facts: list[str] = field(default_factory=list)
    checkpoints: list[str] = field(default_factory=list)


'''
LLM_DATACLASS_NEW = '''@dataclass(slots=True)
class DeepDiveAnalysis:
    """AI 심층분석(딥다이브) 결과. 회사 핵심 사업 + 팩트 기반 핵심 요약 +
    메인 브리핑 카드용 체크포인트. 관련주(피어그룹)는 AI가 만들지 않고
    data/peer_groups.py의 정적 등록 데이터를 notifier.py가 별도로 붙인다."""
    business: str = ""
    facts: list[str] = field(default_factory=list)
    checkpoints: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WatchlistOutlookAnalysis:
    """바이오 워치리스트 종목의 임상/허가 진행단계 + 다음 마일스톤 전망.
    종목 자체의 중장기 투자포인트는 다루지 않는다(analyze_deep_dive의
    business/facts 영역과 역할이 겹치지 않도록 범위를 좁혀놓음)."""
    stage: str = ""
    milestones: list[str] = field(default_factory=list)


'''

LLM_PARSER_OLD = '''def _parse_deep_dive_result(text: str) -> DeepDiveAnalysis | None:
    parsed = _parse_json(text)
    business_value = parsed.get("business")
    business_lines = _clean_lines([business_value], 1, max_len=200) if isinstance(business_value, str) else []
    result = DeepDiveAnalysis(
        business=business_lines[0] if business_lines else "",
        facts=_clean_lines(parsed.get("facts"), 3),
        checkpoints=_clean_lines(parsed.get("checkpoints"), 3),
    )
    return result if (result.business or result.facts or result.checkpoints) else None


'''
LLM_PARSER_NEW = '''def _parse_deep_dive_result(text: str) -> DeepDiveAnalysis | None:
    parsed = _parse_json(text)
    business_value = parsed.get("business")
    business_lines = _clean_lines([business_value], 1, max_len=200) if isinstance(business_value, str) else []
    result = DeepDiveAnalysis(
        business=business_lines[0] if business_lines else "",
        facts=_clean_lines(parsed.get("facts"), 3),
        checkpoints=_clean_lines(parsed.get("checkpoints"), 3),
    )
    return result if (result.business or result.facts or result.checkpoints) else None


def _parse_watchlist_outlook_result(text: str) -> WatchlistOutlookAnalysis | None:
    parsed = _parse_json(text)
    stage_value = parsed.get("stage")
    stage_lines = _clean_lines([stage_value], 1, max_len=200) if isinstance(stage_value, str) else []
    result = WatchlistOutlookAnalysis(
        stage=stage_lines[0] if stage_lines else "",
        milestones=_clean_lines(parsed.get("milestones"), 3),
    )
    return result if (result.stage or result.milestones) else None


'''

LLM_FUNC_OLD = '''    return _call_llm(
        gemini_api_key=gemini_api_key, gemini_model=gemini_model,
        openrouter_api_key=openrouter_api_key, openrouter_model=openrouter_model,
        content=article, system_prompt=_DEEP_DIVE_SYSTEM_PROMPT, timeout_seconds=timeout_seconds,
        step_label="AI 심층분석", parse_fn=_parse_deep_dive_result,
    )


'''
LLM_FUNC_NEW = '''    return _call_llm(
        gemini_api_key=gemini_api_key, gemini_model=gemini_model,
        openrouter_api_key=openrouter_api_key, openrouter_model=openrouter_model,
        content=article, system_prompt=_DEEP_DIVE_SYSTEM_PROMPT, timeout_seconds=timeout_seconds,
        step_label="AI 심층분석", parse_fn=_parse_deep_dive_result,
    )


_WATCHLIST_OUTLOOK_SYSTEM_PROMPT = """당신은 바이오/제약 업종을 전문으로 다루는 애널리스트다.
기사에 언급된 임상시험·인허가 진행 상황만 근거로 이 종목의 현재 단계와 다음 단계
일정을 정리한다. 종목의 중장기 투자매력이나 목표주가는 다루지 않는다. 기사에 없는
임상 결과나 승인 여부를 만들어내지 않는다. 확실하지 않은 시점은 "~예상" 수준으로만
표현하고, 근거가 부족하면 해당 항목을 비운다.

반드시 JSON 객체 하나만 출력한다:
{"stage":"현재 확인된 임상/허가 단계(예: 임상 3상 진행중)","milestones":["다음 예상 마일스톤과 시점"]}

stage/milestones에는 마크다운, 이모지, URL을 넣지 않는다. milestones는 최대 3개까지만 담는다.
"""


def analyze_watchlist_outlook(
    *,
    gemini_api_key: str = "",
    gemini_model: str = "gemini-3.5-flash-lite",
    openrouter_api_key: str = "",
    openrouter_model: str = "openrouter/free",
    title: str,
    summary: str,
    company: str = "",
    reason: str = "",
    amounts: list[str] | None = None,
    theme: str = "",
    score: int = 0,
    article_body: str = "",
    timeout_seconds: int = 45,
    max_chars: int = 9000,
) -> WatchlistOutlookAnalysis | None:
    """바이오 워치리스트 대상(biotech_watchlist.is_biotech_watchlist_item로
    판별된) 뉴스에 한해 호출한다. 임상/허가 진행단계와 다음 마일스톤
    일정만 다루고, 실패해도 None을 반환할 뿐 상위(scheduler.py)에서
    기존 발송 흐름을 막지 않는다."""
    if not gemini_api_key and not openrouter_api_key:
        return None
    article = _build_article(
        title=title, summary=summary, company=company, reason=reason,
        amounts=amounts, theme=theme, score=score, article_body=article_body,
        max_chars=max_chars,
    )
    return _call_llm(
        gemini_api_key=gemini_api_key, gemini_model=gemini_model,
        openrouter_api_key=openrouter_api_key, openrouter_model=openrouter_model,
        content=article, system_prompt=_WATCHLIST_OUTLOOK_SYSTEM_PROMPT, timeout_seconds=timeout_seconds,
        step_label="AI 워치리스트 전망", parse_fn=_parse_watchlist_outlook_result,
    )


'''

# ---------------------------------------------------------------------------
# 2) scheduler.py — import 추가 + 딥다이브 블록 뒤에 워치리스트 호출 삽입
# ---------------------------------------------------------------------------
SCHED_IMPORT_OLD = '''from stock_news_bot.cogs.llm_analyzer import analyze_news, analyze_deep_dive
'''
SCHED_IMPORT_NEW = '''from stock_news_bot.cogs.llm_analyzer import analyze_news, analyze_deep_dive, analyze_watchlist_outlook
from stock_news_bot.biotech_watchlist import get_pipelines, is_biotech_watchlist_item
'''

SCHED_BLOCK_OLD = '''                            if deep_dive_result:
                                item.deep_dive_business = deep_dive_result.business
                                item.deep_dive_facts = list(deep_dive_result.facts)
                                item.deep_dive_checkpoints = list(deep_dive_result.checkpoints)
                                logger.info("🏭 AI 심층분석 완료 | %s", item.title[:80])
                        except Exception:
                            logger.exception("AI 심층분석 실패 | title=%s", item.title[:100])'''
SCHED_BLOCK_NEW = '''                            if deep_dive_result:
                                item.deep_dive_business = deep_dive_result.business
                                item.deep_dive_facts = list(deep_dive_result.facts)
                                item.deep_dive_checkpoints = list(deep_dive_result.checkpoints)
                                logger.info("🏭 AI 심층분석 완료 | %s", item.title[:80])
                        except Exception:
                            logger.exception("AI 심층분석 실패 | title=%s", item.title[:100])

                    # 바이오 워치리스트(하이브리드): (1) 수동 큐레이션된
                    # 파이프라인이 있으면 AI 호출 없이 그 정적 데이터를 그대로
                    # 쓰고, (2) 미등록 종목이라도 임상/허가 테마 키워드가
                    # 있으면 AI로 보조 전망을 생성한다. 실패해도 기존 발송
                    # 흐름은 막지 않는다.
                    if item.company:
                        pipelines = get_pipelines(item.company)
                        if pipelines:
                            item.watchlist_outlook = [
                                f"{p.pipeline_name}({p.event_type}) : {p.stage} — 예상시기 {p.expected_period}"
                                for p in pipelines
                            ]
                            logger.info("🧬 바이오 워치리스트(등록) 반영 | %s", item.title[:80])
                        elif is_biotech_watchlist_item(item):
                            try:
                                outlook_result = await asyncio.to_thread(
                                    analyze_watchlist_outlook,
                                    gemini_api_key=self.settings.gemini_api_key,
                                    gemini_model=self.settings.llm_model,
                                    openrouter_api_key=self.settings.openrouter_api_key,
                                    openrouter_model=self.settings.openrouter_model,
                                    title=item.title,
                                    summary=item.summary,
                                    company=item.company,
                                    reason=item.reason,
                                    amounts=item.amounts,
                                    theme=result.theme or "",
                                    score=item.score,
                                    article_body=article_body,
                                    timeout_seconds=self.settings.llm_analysis_timeout_seconds,
                                    max_chars=self.settings.llm_analysis_max_chars,
                                )
                                if outlook_result:
                                    outlook_lines = []
                                    if outlook_result.stage:
                                        outlook_lines.append(f"진행단계 : {outlook_result.stage}")
                                    outlook_lines.extend(outlook_result.milestones)
                                    item.watchlist_outlook = outlook_lines
                                    logger.info("🧬 바이오 워치리스트(AI 보조) 전망 완료 | %s", item.title[:80])
                            except Exception:
                                logger.exception("바이오 워치리스트 AI 전망 실패 | title=%s", item.title[:100])'''

# ---------------------------------------------------------------------------
# 3) notifier.py — _analysis_parts()의 schedule에 watchlist_outlook 병합
# ---------------------------------------------------------------------------
NOTIFIER_OLD = '''    return title, core, analysis[:6], result.theme, result.related_stocks, result.related_reasons, result.schedule, result.terms'''
NOTIFIER_NEW = '''    schedule = list(item.watchlist_outlook) + list(result.schedule) if item.watchlist_outlook else result.schedule
    return title, core, analysis[:6], result.theme, result.related_stocks, result.related_reasons, schedule, result.terms'''


def _patch_file(path: Path, old: str, new: str, label: str, backups: list[tuple[Path, Path]]) -> bool:
    if not path.exists():
        print(f"[실패] {label}: 파일을 찾을 수 없습니다: {path}")
        return False
    content = path.read_text(encoding="utf-8")
    count = content.count(old)
    if count != 1:
        print(f"[실패] {label}: 앵커가 정확히 1곳에서 발견되지 않았습니다(발견 {count}회). "
              f"파일 상태가 예상과 달라 수동 확인이 필요합니다.")
        return False
    backup = path.with_name(f"{path.name}.bak_biotech_watchlist_{STAMP}")
    shutil.copy2(path, backup)
    backups.append((path, backup))
    path.write_text(content.replace(old, new, 1), encoding="utf-8")
    print(f"[패치 적용] {label} ({path})")
    return True


def main() -> int:
    backups: list[tuple[Path, Path]] = []
    created_new_file = False

    if BIOTECH_WATCHLIST.exists():
        print(f"[실패] {BIOTECH_WATCHLIST}가 이미 존재합니다. 수동으로 확인 후 진행하세요.")
        return 1

    ok = True
    ok &= _patch_file(MODELS, MODELS_OLD, MODELS_NEW, "models.py(누락 필드 4개 추가)", backups)
    if ok:
        ok &= _patch_file(LLM_ANALYZER, LLM_DATACLASS_OLD, LLM_DATACLASS_NEW, "llm_analyzer.py(dataclass)", backups)
    if ok:
        ok &= _patch_file(LLM_ANALYZER, LLM_PARSER_OLD, LLM_PARSER_NEW, "llm_analyzer.py(parser)", backups)
    if ok:
        ok &= _patch_file(LLM_ANALYZER, LLM_FUNC_OLD, LLM_FUNC_NEW, "llm_analyzer.py(analyze_watchlist_outlook)", backups)
    if ok:
        ok &= _patch_file(SCHEDULER, SCHED_IMPORT_OLD, SCHED_IMPORT_NEW, "scheduler.py(import)", backups)
    if ok:
        ok &= _patch_file(SCHEDULER, SCHED_BLOCK_OLD, SCHED_BLOCK_NEW, "scheduler.py(호출 배선)", backups)
    if ok:
        ok &= _patch_file(NOTIFIER, NOTIFIER_OLD, NOTIFIER_NEW, "notifier.py(_analysis_parts 병합)", backups)

    if not ok:
        print("\n하나 이상 실패 — 이미 적용된 변경도 전부 원복합니다.")
        for target, backup in backups:
            shutil.copy2(backup, target)
        return 1

    BIOTECH_WATCHLIST.write_text(BIOTECH_WATCHLIST_CONTENT, encoding="utf-8")
    created_new_file = True
    print(f"[신규 생성] {BIOTECH_WATCHLIST}")

    for path in (MODELS, LLM_ANALYZER, SCHEDULER, NOTIFIER, BIOTECH_WATCHLIST):
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            print(f"\n[검증 실패] {path}: {exc}\n전부 원래대로 복원합니다.")
            for target, backup in backups:
                shutil.copy2(backup, target)
            if created_new_file and BIOTECH_WATCHLIST.exists():
                BIOTECH_WATCHLIST.unlink()
            return 1

    print("\n[검증 성공] 5개 파일 모두 py_compile 통과")
    print("완료. sudo systemctl restart stock-news-bot.service 로 재시작하면 적용됩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
