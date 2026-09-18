import re
import unicodedata
from collections import defaultdict

from verifier.multilingual_semantic import multilingual_semantic_score
from verifier.open_set import open_set_anomaly_score
from verifier.semantic_model import semantic_risk_probability


UI_LANDMARK_HINTS = (
    "dialog",
    "modal",
    "nav",
    "header",
    "footer",
    "menu",
)


def _normalize_text(text):
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"\s+", " ", text).strip()


def _candidate_text(candidate):
    return (
        candidate.get("normalized_text")
        or candidate.get("evidence_text")
        or ""
    )


def _dedupe_candidates(candidates):
    """(url + location + technique) 단위로 5-pass 관측을 합친다."""

    merged = {}
    order = []

    for candidate in candidates:
        key = (
            candidate.get("url"),
            candidate.get("location"),
            candidate.get("technique"),
        )

        scan_pass = candidate.get("scan_pass")

        if key not in merged:
            item = dict(candidate)
            item["observation_count"] = 1
            item["scan_passes"] = [scan_pass] if scan_pass else []
            merged[key] = item
            order.append(key)
            continue

        item = merged[key]
        item["observation_count"] += 1

        if scan_pass and scan_pass not in item["scan_passes"]:
            item["scan_passes"].append(scan_pass)

        old_reasons = item.get("reason", [])
        new_reasons = candidate.get("reason", [])
        item["reason"] = list(dict.fromkeys([*old_reasons, *new_reasons]))

        old_text = item.get("evidence_text") or ""
        new_text = candidate.get("evidence_text") or ""

        if len(new_text) > len(old_text):
            item["evidence_text"] = new_text

        if candidate.get("normalized_text") and not item.get("normalized_text"):
            item["normalized_text"] = candidate["normalized_text"]

        if len(new_reasons) >= len(old_reasons):
            for field in (
                "rect",
                "opacity_source",
                "display_source",
            ):
                if candidate.get(field) is not None:
                    item[field] = candidate[field]

    return [merged[key] for key in order]


def _selector_parent(selector):
    if not selector or " > " not in selector:
        return ""
    return selector.rsplit(" > ", 1)[0]


def _build_page_context(pages):
    page_titles = {}
    page_elements = defaultdict(list)

    for page in pages or []:
        url = page.get("url", "")
        page_titles[url] = page.get("title", "")
        seen = set()

        for element in page.get("elements", []):
            selector = element.get("selector", "")
            text = _normalize_text(element.get("text", ""))
            key = (selector, text)

            if not selector or not text or key in seen:
                continue

            seen.add(key)
            page_elements[url].append(
                {
                    "selector": selector,
                    "text": text,
                }
            )

    return page_titles, page_elements


def _context_text(candidate, page_titles, page_elements, max_chars=900):
    url = candidate.get("url", "")
    selector = candidate.get("location", "")
    own = _normalize_text(_candidate_text(candidate))
    parent = _selector_parent(selector)
    grandparent = _selector_parent(parent)

    nearby = []
    seen_text = {own} if own else set()

    def collect(prefix, limit):
        if not prefix:
            return

        count = 0

        for element in page_elements.get(url, []):
            other_selector = element["selector"]
            other_text = element["text"]

            if other_selector == selector:
                continue
            if not other_selector.startswith(prefix + " > "):
                continue
            if other_text in seen_text:
                continue

            seen_text.add(other_text)
            nearby.append(other_text)
            count += 1

            if count >= limit:
                break

    collect(parent, 8)
    if len(nearby) < 4:
        collect(grandparent, 6)

    parts = []
    title = _normalize_text(page_titles.get(url, ""))

    if own:
        parts.extend([own, own])
    if title:
        parts.append(title)

    parts.extend(nearby)
    return " ".join(parts)[:max_chars]


def _technique_strength(candidate):
    technique = candidate.get("technique")
    reasons = " ".join(candidate.get("reason", [])).lower()

    if technique in {"JAMO", "HOMOGLYPH"}:
        return 0.78

    if technique == "TRANSPARENT":
        score = 0.56

        # opacity:0 자체도 공모전 대표 은닉 패턴이므로 color:transparent와
        # 비슷한 수준의 구조 강도로 본다. 단, open-set 최종 통과는 여전히
        # 희귀성/Unicode 이상/반복 패널티 등 추가 신호가 필요하다.
        if "opacity가 0" in reasons:
            score += 0.08
        if "텍스트 색상이 완전히 투명" in reasons:
            score += 0.08
        if "배경 색상이 동일" in reasons:
            score += 0.06

        return min(0.78, score)

    if technique == "OFFSCREEN":
        if reasons and all(
            "display:none" in reason
            for reason in candidate.get("reason", [])
        ):
            return 0.28

        score = 0.48

        if "글자 크기" in reasons:
            score += 0.12
        if "화면 밖 좌표" in reasons:
            score += 0.16

        return min(0.80, score)

    return 0.40


def _ui_landmark_penalty(candidate):
    blob = " ".join(
        str(candidate.get(field, ""))
        for field in (
            "location",
            "opacity_source",
            "display_source",
        )
    ).lower()

    return 0.10 if any(hint in blob for hint in UI_LANDMARK_HINTS) else 0.0


def _repetition_stats(candidates, total_pages):
    exact_pages = defaultdict(set)
    location_pages = defaultdict(set)
    text_pages = defaultdict(set)
    techniques_by_element = defaultdict(set)

    for candidate in candidates:
        url = candidate.get("url")
        technique = candidate.get("technique")
        location = candidate.get("location")
        text = _normalize_text(_candidate_text(candidate))

        exact_pages[(technique, location, text)].add(url)
        location_pages[(technique, location)].add(url)
        text_pages[(technique, text)].add(url)
        techniques_by_element[(url, location)].add(technique)

    def stats(candidate):
        url = candidate.get("url")
        technique = candidate.get("technique")
        location = candidate.get("location")
        text = _normalize_text(_candidate_text(candidate))

        exact_count = len(exact_pages[(technique, location, text)])
        location_count = len(location_pages[(technique, location)])
        text_count = len(text_pages[(technique, text)])
        repeat_count = max(exact_count, location_count)
        repeat_ratio = repeat_count / max(1, total_pages)
        multi_technique_count = len(techniques_by_element[(url, location)])

        return {
            "exact_repeat_count": exact_count,
            "location_repeat_count": location_count,
            "text_repeat_count": text_count,
            "repeat_count": repeat_count,
            "repeat_ratio": repeat_ratio,
            "multi_technique_count": multi_technique_count,
        }

    return stats


def _template_penalty(repeat_count, repeat_ratio):
    if repeat_count <= 1:
        return 0.0

    count_penalty = min(0.28, 0.07 * (repeat_count - 1))
    ratio_penalty = min(0.12, repeat_ratio * 0.45)
    return count_penalty + ratio_penalty


def _novelty_bonus(repeat_count):
    if repeat_count <= 1:
        return 0.10
    if repeat_count == 2:
        return 0.06
    if repeat_count == 3:
        return 0.03
    return 0.0


def verify_candidates(candidate_groups, pages=None):
    """
    Contextual Verifier v3.

    Known branch:
      기존 문자 n-gram과 다국어 의미 모델을 독립적으로 계산한 뒤
      두 branch의 합의 정도까지 확인한다. 한 모델만 과신한 정상 UI 문구가
      바로 CONFIRMED가 되는 것을 막는다.

    Open-set branch:
      의미 모델이 처음 보는 문구라도 사이트 내부 희귀성, 은닉 강도,
      다중 기법, 렌더링 상태 선택성, Unicode 이상도를 결합해 탐지한다.

    localhost/file 입력도 실제 verifier를 그대로 통과한다. 테스트 표식 때문에
    강제 정답 처리하지 않아야 모의 사이트가 의미/open-set 회귀검사 역할을 한다.
    """

    raw_candidates = [
        candidate
        for group in candidate_groups
        for candidate in group
    ]
    candidates = _dedupe_candidates(raw_candidates)

    page_titles, page_elements = _build_page_context(pages or [])
    page_urls = {
        page.get("url")
        for page in (pages or [])
        if page.get("url")
    }
    total_pages = max(1, len(page_urls))
    repetition_for = _repetition_stats(candidates, total_pages)

    verified = []
    rejected = []

    for candidate in candidates:
        item = dict(candidate)

        context = _context_text(
            candidate,
            page_titles,
            page_elements,
        )
        evidence_text = _candidate_text(candidate)

        legacy_evidence = semantic_risk_probability(evidence_text)
        legacy_context = semantic_risk_probability(context)
        multilingual_evidence, semantic_backend = multilingual_semantic_score(
            evidence_text
        )
        multilingual_context, _ = multilingual_semantic_score(context)

        legacy_branch_score = (
            0.58 * legacy_evidence
            + 0.42 * legacy_context
        )
        multilingual_branch_score = (
            0.58 * multilingual_evidence
            + 0.42 * multilingual_context
        )
        semantic_score = (
            0.50 * legacy_branch_score
            + 0.50 * multilingual_branch_score
        )
        semantic_agreement = max(
            0.0,
            1.0 - abs(legacy_branch_score - multilingual_branch_score),
        )

        structure_score = _technique_strength(candidate)
        repetition = repetition_for(candidate)
        repeat_count = repetition["repeat_count"]
        repeat_ratio = repetition["repeat_ratio"]

        template_penalty = _template_penalty(
            repeat_count,
            repeat_ratio,
        )
        ui_penalty = _ui_landmark_penalty(candidate)

        if ui_penalty and repeat_count >= 3:
            ui_penalty += 0.08

        multi_technique_bonus = min(
            0.16,
            0.08 * max(0, repetition["multi_technique_count"] - 1),
        )
        novelty_bonus = _novelty_bonus(repeat_count)

        known_score = (
            0.56 * semantic_score
            + 0.27 * structure_score
            + novelty_bonus
            + multi_technique_bonus
            - template_penalty
            - ui_penalty
        )
        known_score = max(0.0, min(1.0, known_score))

        open_score, open_reasons = open_set_anomaly_score(
            candidate,
            structure_score=structure_score,
            repeat_count=repeat_count,
            repeat_ratio=repeat_ratio,
            multi_technique_count=repetition["multi_technique_count"],
            total_pages=total_pages,
        )

        technique = candidate.get("technique")

        if technique in {"JAMO", "HOMOGLYPH"}:
            semantic_floor = 0.56
            known_floor = 0.60
        else:
            semantic_floor = 0.60
            known_floor = 0.60

        max_branch = max(legacy_branch_score, multilingual_branch_score)
        min_branch = min(legacy_branch_score, multilingual_branch_score)

        semantic_consensus = (
            (min_branch >= 0.54 and max_branch >= 0.64)
            or max_branch >= 0.82
        )

        known_confirmed = (
            semantic_score >= semantic_floor
            and known_score >= known_floor
            and semantic_consensus
        )

        if technique in {"JAMO", "HOMOGLYPH"}:
            open_suspicious = (
                open_score >= 0.60
                and repeat_count <= 2
            )
        else:
            open_suspicious = (
                (
                    open_score >= 0.66
                    and structure_score >= 0.60
                    and repeat_count <= 2
                )
                or (
                    open_score >= 0.64
                    and repetition["multi_technique_count"] >= 2
                    and structure_score >= 0.60
                    and repeat_count <= 3
                )
            )

        if known_confirmed:
            status = "CONFIRMED"
            is_violation = True
        elif open_suspicious:
            status = "SUSPICIOUS"
            is_violation = True
        else:
            status = "BENIGN_LIKELY"
            is_violation = False

        verification_score = max(known_score, open_score)

        item["semantic_score"] = round(semantic_score, 3)
        item["legacy_semantic_score"] = round(legacy_branch_score, 3)
        item["multilingual_score"] = round(multilingual_branch_score, 3)
        item["semantic_agreement"] = round(semantic_agreement, 3)
        item["semantic_backend"] = semantic_backend
        item["structure_score"] = round(structure_score, 3)
        item["known_score"] = round(known_score, 3)
        item["open_set_score"] = round(open_score, 3)
        item["verification_score"] = round(verification_score, 3)
        item["verification_status"] = status
        item["template_repeat_count"] = repeat_count
        item["template_repeat_ratio"] = round(repeat_ratio, 3)
        item["multi_technique_count"] = repetition["multi_technique_count"]
        item["is_violation"] = is_violation

        reason_parts = [
            f"known 의미 {semantic_score:.2f}",
            f"legacy {legacy_branch_score:.2f}",
            f"다국어 {multilingual_branch_score:.2f}",
            f"의미 합의 {semantic_agreement:.2f}",
            f"구조 강도 {structure_score:.2f}",
            f"known 결합 {known_score:.2f}",
            f"open-set {open_score:.2f}",
        ]

        if repeat_count >= 2:
            reason_parts.append(
                f"동일/유사 위치가 {repeat_count}개 페이지에서 반복"
            )
        if ui_penalty:
            reason_parts.append("공통 UI 문맥 패널티 적용")
        if repetition["multi_technique_count"] >= 2:
            reason_parts.append(
                f"동일 요소에서 {repetition['multi_technique_count']}개 기법 중첩"
            )
        if open_reasons:
            reason_parts.append("open-set: " + ", ".join(open_reasons))

        if status == "CONFIRMED":
            prefix = "알려진 의미·구조 결합 검증에서 기준 초과"
            item["verification_reason"] = prefix + "; " + ", ".join(reason_parts)
            verified.append(item)
        elif status == "SUSPICIOUS":
            prefix = (
                "알려진 의미 유형과 일치하지 않아도 구조적 이상도가 높아 "
                "신유형 의심 후보로 유지"
            )
            item["verification_reason"] = prefix + "; " + ", ".join(reason_parts)
            verified.append(item)
        else:
            prefix = "의미 및 open-set 결합 검증에서 정상 UI 가능성이 더 높음"
            item["verification_reason"] = prefix + "; " + ", ".join(reason_parts)
            rejected.append(item)

    return verified, rejected
