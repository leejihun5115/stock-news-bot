# -*- coding: utf-8 -*-
"""
학습형 AI 분석 모듈 (무료 · 온디바이스 온라인 학습).

[목적]
outcome_tracking_성과추적.py가 쌓는 "실제 결과"(등락률, 시황/광고 여부)를 학습
데이터로 계속 누적하면서, 새로 들어오는 뉴스를 과거 누적 사례와 자동으로
비교·분석해 다음을 산출한다.
  1) 이번 뉴스와 가장 유사했던 과거 사례들(그때 실제로 올랐는지/내렸는지)
  2) 그 사례들과 지금이 어떻게 다른지(동일 종목 여부, 유사도)
  3) 누적 학습 통계 기반 '상승 방향 확률' 및 '시황/광고성 확률' 추정치
  4) 위 내용을 텔레그램/관리자 리포트에 바로 붙일 수 있는 한국어 요약문

[설계 원칙 — 왜 이렇게 만들었는가]
- 무료: 유료 클라우드 학습 API를 쓰지 않는다. Python 표준 라이브러리(math, re,
  json)만으로 구현한 온라인(incremental) 나이브베이즈 + TF-IDF 코사인 유사도다.
  requirements.txt에 새 의존성을 추가할 필요가 없다.
- 안전: 이 모듈의 출력은 어디까지나 '참고 분석'이다. 실제 송출 여부를 가르는
  MASTER 엔진/뉴스엔진의 필터링 로직은 절대 건드리지 않는다 — 예측이 틀리거나
  이 모듈이 예외를 던져도 봇의 핵심 동작(수집·판정·송출)은 영향받지 않도록
  호출부(outcome_tracking)에서 항상 try/except로 감싸는 것을 전제로 한다.
- 정직한 학습: 아직 확정되지 않은 값으로는 학습하지 않는다. 시황/광고 라벨은
  기존 규칙판정이 이미 확정한 값을 그대로 신호로 쓰고(즉시 학습), 상승/하락
  라벨은 outcome_tracking이 실제 등락률을 계산 완료한 시점에만 학습한다.
- 점진적 온라인 학습: 매번 전체 이력을 다시 훈련하지 않는다. 결과가 확정되는
  건별로 카운트를 누적 갱신하는 나이브베이즈 방식이라 데이터가 아무리 쌓여도
  학습 자체는 항상 O(1)에 가깝다(유사사례 검색만 최근 N건을 훑는다).
"""

import os
import re
import json
import math
import tempfile
from collections import Counter

from common_공용유틸 import _engine_log, _now_kst, log_error

ML_MODEL_FILE = os.environ.get("NEWS_BOT_ML_MODEL_DB", "ml_learning_model.json")
# 나이브베이즈가 "의미 있는 추정치"를 내놓기 시작하는 최소 학습 표본 수.
# 이보다 적으면 확률을 내지 않고 "학습 데이터 부족"이라고 정직하게 알린다.
ML_MIN_TRAIN_SAMPLES = int(os.environ.get("NEWS_BOT_ML_MIN_TRAIN_SAMPLES", "8"))
# 평균 등락률이 이 값(%)을 넘으면 "상승" 라벨(1), 아니면 "하락/보합" 라벨(0)로 학습한다.
ML_OUTCOME_POSITIVE_THRESHOLD = float(os.environ.get("NEWS_BOT_ML_OUTCOME_POS_THRESHOLD", "0.5"))
ML_LAPLACE_ALPHA = 1.0
# 유사 사례 검색 시 과거 DB를 통째로 훑지 않고 최근 이만큼만 본다(최근 사례가 더 유의미하고, 속도도 보장).
ML_SIMILAR_CASE_LOOKBACK = int(os.environ.get("NEWS_BOT_ML_SIMILAR_LOOKBACK", "600"))
# 장기 운영 시 1회성 희귀 토큰이 무한정 쌓이는 것을 막는 어휘 상한.
ML_VOCAB_PRUNE_LIMIT = int(os.environ.get("NEWS_BOT_ML_VOCAB_PRUNE_LIMIT", "30000"))
ML_PREDICTION_LOG_MAX = 500

# 한글 음절/영문/숫자 2자 이상을 토큰으로 본다(뉴스 제목은 이미 공백 정제됨).
_TOKEN_PAT = re.compile(r"[가-힣A-Za-z0-9]{2,}")

_ml_model = None  # 메모리 캐시. 예측/학습마다 파일을 다시 읽지 않기 위함(변경 시에만 저장).


def _ml_empty_class_stats():
    return {
        "class_doc_count": {"0": 0, "1": 0},
        "token_count": {"0": {}, "1": {}},
        "class_token_total": {"0": 0, "1": 0},
    }


def _ml_default_model():
    return {
        "version": 1,
        "created_at": _now_kst().isoformat(),
        "updated_at": _now_kst().isoformat(),
        "vocab_df": {},              # {token: 등장한 문서 수} — IDF 계산용
        "total_docs_seen": 0,
        "macro_model": _ml_empty_class_stats(),    # 시황/광고 여부 학습
        "outcome_model": _ml_empty_class_stats(),  # 상승/하락 여부 학습
        "prediction_log": [],        # 예측 당시 값 vs 실제 결과 (적중률 검증용)
    }


def _ml_load_model(force=False):
    """모델을 1회 로드해 메모리에 캐시한다. 파일이 없거나 손상되면 빈 모델로
    새로 시작한다(학습 자체가 무너지지 않는 것이 과거 이력을 억지로 복구하는
    것보다 중요하다)."""
    global _ml_model
    if _ml_model is not None and not force:
        return _ml_model
    model = _ml_default_model()
    if os.path.exists(ML_MODEL_FILE):
        try:
            with open(ML_MODEL_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f) or {}
            for k, v in _ml_default_model().items():
                loaded.setdefault(k, v)
            loaded.setdefault("macro_model", _ml_empty_class_stats())
            loaded.setdefault("outcome_model", _ml_empty_class_stats())
            model = loaded
        except Exception as e:
            log_error("[학습AI] 모델 파일 로드 실패 - 새로 시작", e)
    _ml_model = model
    return _ml_model


def _ml_save_model():
    """임시파일에 먼저 쓰고 os.replace로 교체한다(성과추적 DB와 동일한 원자적
    저장 패턴) — 저장 도중 프로세스가 죽어도 모델 파일이 깨지지 않는다."""
    if _ml_model is None:
        return
    try:
        _ml_model["updated_at"] = _now_kst().isoformat()
        directory = os.path.dirname(os.path.abspath(ML_MODEL_FILE)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp_ml_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(_ml_model, f, ensure_ascii=False, separators=(",", ":"))
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp_path, ML_MODEL_FILE)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
    except Exception as e:
        log_error("[학습AI] 모델 파일 저장 실패", e)


def _ml_tokenize(text):
    return _TOKEN_PAT.findall(str(text or ""))


def _ml_prune_vocab_if_needed(model):
    vocab_df = model["vocab_df"]
    if len(vocab_df) <= ML_VOCAB_PRUNE_LIMIT:
        return
    rare = [t for t, df in vocab_df.items() if df <= 1]
    for t in rare:
        vocab_df.pop(t, None)
        for cls_model in (model["macro_model"], model["outcome_model"]):
            for cls in ("0", "1"):
                cnt = cls_model["token_count"].get(cls, {}).pop(t, None)
                if cnt:
                    cls_model["class_token_total"][cls] = max(0, cls_model["class_token_total"][cls] - cnt)
    _engine_log("info", "[학습AI] 어휘 정리 완료 | 제거=%d건 | 잔여=%d건", len(rare), len(vocab_df))


def _ml_register_tokens(model, tokens):
    """전역 vocab 문서빈도(df)를 갱신한다(IDF 계산용). 같은 문서 내 중복 토큰은 1회만 센다."""
    for t in set(tokens):
        model["vocab_df"][t] = model["vocab_df"].get(t, 0) + 1
    model["total_docs_seen"] += 1


def _ml_update_class_stats(cls_stats, tokens, label):
    label = str(int(bool(label)))
    cls_stats["class_doc_count"][label] = cls_stats["class_doc_count"].get(label, 0) + 1
    tc = cls_stats["token_count"].setdefault(label, {})
    counts = Counter(tokens)
    for token, c in counts.items():
        tc[token] = tc.get(token, 0) + c
    cls_stats["class_token_total"][label] = cls_stats["class_token_total"].get(label, 0) + sum(counts.values())


def _ml_predict_class_stats(cls_stats, vocab_size, tokens):
    """나이브베이즈(라플라스 스무딩)로 label=1일 확률(0~1)을 계산한다.
    두 클래스 중 하나라도 표본이 0이거나 전체 표본이 최소치 미만이면
    (None, 전체표본수)를 반환해 "아직 학습 부족"임을 정직하게 알린다."""
    n0 = cls_stats["class_doc_count"].get("0", 0)
    n1 = cls_stats["class_doc_count"].get("1", 0)
    total = n0 + n1
    if total < ML_MIN_TRAIN_SAMPLES or n0 == 0 or n1 == 0:
        return None, total
    log_p0 = math.log(n0 / total)
    log_p1 = math.log(n1 / total)
    tt0 = cls_stats["class_token_total"].get("0", 0)
    tt1 = cls_stats["class_token_total"].get("1", 0)
    tc0 = cls_stats["token_count"].get("0", {})
    tc1 = cls_stats["token_count"].get("1", {})
    alpha = ML_LAPLACE_ALPHA
    v = max(1, vocab_size)
    for token, c in Counter(tokens).items():
        log_p0 += c * math.log((tc0.get(token, 0) + alpha) / (tt0 + alpha * v))
        log_p1 += c * math.log((tc1.get(token, 0) + alpha) / (tt1 + alpha * v))
    m = max(log_p0, log_p1)
    e0, e1 = math.exp(log_p0 - m), math.exp(log_p1 - m)
    prob1 = e1 / (e0 + e1)
    return prob1, total


def _ml_tfidf_vector(model, tokens):
    df = model["vocab_df"]
    n = max(1, model["total_docs_seen"])
    vec = {}
    for token, c in Counter(tokens).items():
        d = df.get(token, 0)
        idf = math.log((n + 1) / (d + 1)) + 1.0
        vec[token] = c * idf
    return vec


def _ml_cosine(vec_a, vec_b):
    if not vec_a or not vec_b:
        return 0.0
    common = set(vec_a) & set(vec_b)
    if not common:
        return 0.0
    dot = sum(vec_a[t] * vec_b[t] for t in common)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _ml_avg_change(record):
    changes = list((record.get("change_pct") or {}).values())
    if not changes:
        return None
    return sum(changes) / len(changes)


def _ml_load_recent_completed_records():
    """outcome_tracking DB에서 최근 레코드만 불러온다(전체 파일을 매번 다 읽지
    않기 위해 끝에서부터 ML_SIMILAR_CASE_LOOKBACK줄만 사용)."""
    from outcome_tracking_성과추적 import OUTCOME_DB_FILE
    if not os.path.exists(OUTCOME_DB_FILE):
        return []
    try:
        with open(OUTCOME_DB_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        log_error("[학습AI] 성과추적 DB 읽기 실패", e)
        return []
    lines = lines[-ML_SIMILAR_CASE_LOOKBACK:]
    records = []
    for line in lines:
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    return records


def _ml_find_similar_cases(model, query_tokens, related_stocks, top_k=3):
    """이번 뉴스와 가장 유사한 '결과가 이미 확정된' 과거 사례를 코사인 유사도로
    찾는다. 시황/광고로 걸러진 사례는 개별 종목 반응과 비교 대상이 아니므로 제외."""
    records = _ml_load_recent_completed_records()
    query_vec = _ml_tfidf_vector(model, query_tokens)
    scored = []
    for r in records:
        if r.get("is_macro_or_ad"):
            continue
        change = _ml_avg_change(r)
        if change is None:
            continue
        cand_tokens = _ml_tokenize(r.get("title", ""))
        sim = _ml_cosine(query_vec, _ml_tfidf_vector(model, cand_tokens))
        if sim <= 0:
            continue
        scored.append((sim, change, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_k]


def _ml_generate_analysis(title, category, related_stocks, reason, evidence):
    """뉴스 1건에 대한 학습 기반 비교분석을 생성한다.
    반환값: (텔레그램에 붙일 요약 문자열, 나중에 적중률 검증에 쓸 예측 스냅샷 dict)"""
    try:
        model = _ml_load_model()
        text = f"{title} {reason} {' '.join(evidence or [])} {category} {' '.join(related_stocks or [])}"
        tokens = _ml_tokenize(text)
        vocab_size = max(1, len(model["vocab_df"]))

        macro_prob, macro_n = _ml_predict_class_stats(model["macro_model"], vocab_size, tokens)
        outcome_prob, outcome_n = _ml_predict_class_stats(model["outcome_model"], vocab_size, tokens)
        # [수정] top_k를 3→8로 넓혀서 평균/범위/승률 같은 통계치를 낼 표본을 더 확보한다.
        # (개별 사례 표시는 여전히 상위 3건만 하되, 요약 통계는 최대 8건으로 계산)
        similar = _ml_find_similar_cases(model, tokens, related_stocks, top_k=8)

        lines = ["🤖 [AI 학습 분석 · 누적 데이터 기반]"]
        lines.append(f"• 누적 학습 표본: 시황/광고 판정 {macro_n}건 · 등락 결과 학습 {outcome_n}건")

        if macro_prob is not None:
            lines.append(f"• AI 추정 시황/광고성 확률: {macro_prob*100:.1f}%")
        if outcome_prob is not None:
            direction = "상승 우세" if outcome_prob >= 0.5 else "약세 우려"
            lines.append(f"• AI 추정 상승 방향 확률: {outcome_prob*100:.1f}% ({direction})")
        else:
            lines.append(f"• AI 등락 방향 예측: 정식 확률모형은 학습 표본 부족(최소 {ML_MIN_TRAIN_SAMPLES}건, "
                          f"현재 {outcome_n}건, 상승/하락 사례 모두 필요) — 아래 유사사례 실측치로 대체 판단")

        # [핵심 수정 — 이전 버그] 정식 확률모형(나이브베이즈) 표본이 부족하면
        # "학습 표본 부족"이라는 문장 하나만 나가고 끝나서, 매매 판단에 쓸 수 있는
        # 숫자가 하나도 없는 메시지가 나가는 경우가 대부분이었다(신규 소재는 항상
        # 8건 미만이므로 사실상 매번 발생). 정식 확률모형과 별개로, 이미 찾아낸
        # "유사 과거사례"들의 실제 등락률을 평균/승률/범위로 즉시 요약해 정식 모형이
        # 없어도 근거 수치가 항상 나가도록 한다.
        if similar:
            changes = [c for _, c, _ in similar]
            avg_change = sum(changes) / len(changes)
            up_count = sum(1 for c in changes if c > 0)
            win_rate = up_count / len(changes) * 100
            max_c, min_c = max(changes), min(changes)

            lines.append(
                f"• 유사사례 {len(changes)}건 실측 요약: 평균 {avg_change:+.2f}% · "
                f"상승비율 {win_rate:.0f}%({up_count}/{len(changes)}) · 범위 {min_c:+.2f}%~{max_c:+.2f}%"
            )

            lines.append("• 가장 유사한 과거 사례:")
            for sim, change, r in similar[:3]:
                arrow = "📈" if change > 0 else ("📉" if change < 0 else "➖")
                same_stock = bool(set(related_stocks or []) & set(r.get("related_stocks") or []))
                diff_note = "동일 종목" if same_stock else "다른 종목·유사 소재"
                lines.append(
                    f"  - (유사도 {sim*100:.0f}%, {diff_note}) \"{str(r.get('title',''))[:40]}\" "
                    f"→ 당시 결과 {arrow} 평균 {change:+.2f}%"
                )

            best_sim, best_change, _ = similar[0]
            if best_sim >= 0.35:
                if win_rate >= 65 and avg_change > 0:
                    verdict = f"과거 유사 재료 상승비율 {win_rate:.0f}%로 우호적 — 초반 관련주 반응 속도 우선 확인"
                elif win_rate <= 35 and avg_change < 0:
                    verdict = f"과거 유사 재료 상승비율 {win_rate:.0f}%로 부진 — 단기 재료 소멸 가능성 유의"
                else:
                    verdict = f"과거 사례 결과가 혼재({win_rate:.0f}% 상승) — 방향성 단정 어려움, 관련주 첫 반응으로 재확인 필요"
                lines.append(f"• 방향성 제안: {verdict}.")
            else:
                lines.append(f"• 방향성 제안: 과거 사례와 유사도가 낮은 신규 유형 소재(최고 유사도 {best_sim*100:.0f}%) "
                              f"— 위 실측 평균({avg_change:+.2f}%)은 참고치일 뿐, 이번 결과부터 새로 학습 데이터로 축적됩니다.")
        else:
            lines.append("• 비교할 수 있는 과거 유사 사례가 아직 충분히 쌓이지 않았습니다(계속 누적 중) — "
                          "현재 이 소재 유형은 수치 근거 없이 판단 보류 권장.")

        prediction_snapshot = {
            "ts": _now_kst().isoformat(),
            "macro_prob": macro_prob,
            "outcome_prob": outcome_prob,
            "macro_train_n": macro_n,
            "outcome_train_n": outcome_n,
        }
        return "\n".join(lines), prediction_snapshot
    except Exception as e:
        log_error("[학습AI] 분석 생성 실패(참고 기능이므로 송출은 계속 진행)", e, title=str(title)[:80])
        return "", {}


def _ml_learn_macro_label(title, category, related_stocks, reason, evidence, is_macro_or_ad):
    """시황/광고 여부는 규칙판정이 이미 그 자리에서 확정하는 값이라 지연 없이
    바로 학습 신호로 쓴다(등락률과 달리 나중에 결과를 기다릴 필요가 없다)."""
    try:
        model = _ml_load_model()
        text = f"{title} {reason} {' '.join(evidence or [])} {category} {' '.join(related_stocks or [])}"
        tokens = _ml_tokenize(text)
        if not tokens:
            return
        _ml_register_tokens(model, tokens)
        _ml_update_class_stats(model["macro_model"], tokens, label=is_macro_or_ad)
        _ml_prune_vocab_if_needed(model)
        _ml_save_model()
    except Exception as e:
        log_error("[학습AI] 시황/광고 라벨 학습 실패", e, title=str(title)[:80])


def _ml_learn_from_completed_record(record):
    """outcome_tracking._engine_outcome_tracking_cycle에서, 등락률이 실제로
    확정된 레코드가 나올 때마다 호출된다. 시황/광고로 제외된 레코드는 애초에
    관련주 반응을 추적하지 않았으므로 학습 대상에서 제외한다."""
    try:
        if record.get("is_macro_or_ad"):
            return
        change = _ml_avg_change(record)
        if change is None:
            return  # 가격 조회 실패 등 결과 자체가 없으면 학습하지 않는다(오염 방지)
        label = 1 if change > ML_OUTCOME_POSITIVE_THRESHOLD else 0

        model = _ml_load_model()
        title = record.get("title", "")
        reason = record.get("reason", "")
        evidence = record.get("evidence") or []
        category = record.get("category", "")
        stocks = record.get("related_stocks") or []
        text = f"{title} {reason} {' '.join(evidence)} {category} {' '.join(stocks)}"
        tokens = _ml_tokenize(text)
        if not tokens:
            return

        # 송출 시점에 저장해둔 예측값이 있으면, 실제 결과와 비교해 적중률 로그를 남긴다.
        prior = record.get("ml_analysis") or {}
        if prior.get("outcome_prob") is not None:
            model["prediction_log"].append({
                "ts": _now_kst().isoformat(),
                "predicted_positive_prob": prior["outcome_prob"],
                "actual_positive": bool(label),
                "title": str(title)[:80],
            })
            if len(model["prediction_log"]) > ML_PREDICTION_LOG_MAX:
                del model["prediction_log"][: len(model["prediction_log"]) - ML_PREDICTION_LOG_MAX]

        _ml_register_tokens(model, tokens)
        _ml_update_class_stats(model["outcome_model"], tokens, label=label)
        _ml_prune_vocab_if_needed(model)
        _ml_save_model()
        _engine_log("info", "[학습AI] 등락 결과 학습 완료 | 라벨=%s | 평균등락=%.2f%% | %s",
                    "상승" if label else "하락/보합", change, str(title)[:60])
    except Exception as e:
        log_error("[학습AI] 등락 결과 학습 실패", e, title=str(record.get("title", ""))[:80])


def _ml_status_report():
    """/학습현황 관리자 명령용 리포트. 누적 학습량과 예측 적중률(백테스트)을 보여준다."""
    model = _ml_load_model()
    macro = model["macro_model"]["class_doc_count"]
    outcome = model["outcome_model"]["class_doc_count"]
    log = model.get("prediction_log") or []

    lines = [
        "🤖 <b>[학습형 AI 분석 현황]</b>",
        f"🕐 {_now_kst().strftime('%Y-%m-%d %H:%M')} KST",
        "",
        f"• 누적 학습 문서(어휘 기준): {model.get('total_docs_seen', 0)}건 · 어휘 수: {len(model.get('vocab_df', {}))}개",
        f"• 시황/광고 판정 학습 표본: 일반(개별호재) {macro.get('0',0)}건 / 시황·광고 {macro.get('1',0)}건",
        f"• 등락 결과 학습 표본: 하락·보합 {outcome.get('0',0)}건 / 상승 {outcome.get('1',0)}건",
        "",
    ]
    if len(log) < 5:
        lines.append(f"• 예측 적중률: 검증 가능한 표본이 아직 부족합니다({len(log)}/5건).")
    else:
        hits = sum(1 for e in log if (e["predicted_positive_prob"] >= 0.5) == e["actual_positive"])
        acc = hits / len(log) * 100
        lines.append(f"• 최근 예측 적중률(상승/하락 방향 기준): {acc:.1f}% (표본 {len(log)}건)")
    lines.append("")
    lines.append("※ 이 분석은 누적 데이터 기반 참고 통계이며, 실제 송출 필터링 로직에는 영향을 주지 않습니다.")
    return "\n".join(lines)
