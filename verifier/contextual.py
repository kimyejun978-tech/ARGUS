import re
import time
import unicodedata
from collections import defaultdict

from verifier.multilingual_semantic import multilingual_semantic_details
from verifier.open_set import BIDI_OR_ZERO_WIDTH, open_set_anomaly_score
from verifier.semantic_model import semantic_risk_with_support


DIGIT_ONLY_HOMOGLYPH_REASON = "단어 내부 숫자가 유사한 알파벳 문자 대신 사용됨"\n\n\nUI_LANDMARK_HINTS = (
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


def _is_visibly_rendered(element):
    style = element.get("style") or {}

    try:
        font_size = float(str(style.get("fontSize", "16px")).replace("px", ""))
    except (TypeError, ValueError):
        font_size = 16.0

    try:
        opacity = float(element.get("effectiveOpacity", 1.0))
    except (TypeError, ValueError):
        opacity = 1.0

    try:
        text_alpha = float(element.get("textColorAlpha", 1.0))
    except (TypeError, ValueError):
        text_alpha = 1.0

    return (
        not element.get("displayNoneSource")
        and opacity > 0.001
        and text_alpha > 0.001
        and not element.get("sameTextBackground")
        and style.get("visibility") not in {"hidden", "collapse"}
        and font_size > 1.0
        and element.get("inViewport") is True
    )


def _build_visible_text_index(pages):
    visible = defaultdict(lambda: defaultdict(set))

    for page in pages or []:
        url = page.get("url", "")

        for element in page.get("elements", []):
            if not _is_visibly_rendered(element):
                continue

            text = _normalize_text(element.get("text", ""))
            selector = element.get("selector", "")

            if text and selector:
                visible[url][text].add(selector)

    return visible


def _build_page_context(pages):
    page_titles = {}
    page_elements = defaultdict(list)
    page_descendants = defaultdict(lambda: defaultdict(list))

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
            item = {
                "selector": selector,
                "text": text,
            }
            page_elements[url].append(item)

            # 기존 _context_text는 후보마다 페이지 전체 element 목록을 선형 검색했다.
            # 한 번만 ancestor prefix index를 만들어 같은 의미의 검색을 O(1)에 가깝게
            # 가져온다. 입력 순서를 그대로 append하므로 주변 텍스트 선택 순서도 같다.
            parent = _selector_parent(selector)
            while parent:
                page_descendants[url][parent].append(item)
                parent = _selector_parent(parent)

    return page_titles, page_elements, page_descendants


def _context_text(
    candidate,
    page_titles,
    page_elements,
    page_descendants=None,
    max_chars=900,
):
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

        if page_descendants is None:
            source = page_elements.get(url, [])
        else:
            source = page_descendants.get(url, {}).get(prefix, [])

        for element in source:
            other_selector = element["selector"]
            other_text = element["text"]

            if other_selector == selector:
                continue
            if (
                page_descendants is None
                and not other_selector.startswith(prefix + " > ")
            ):
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


def _is_digit_only_homoglyph(candidate):
    """
    ASCII 숫자 치환만 근거인 HOMOGLYPH 후보를 구분한다.

    W3C, C14N, UTF8Mode, 0x1f 같은 정상 기술 표기에도 내부 숫자가 흔하므로
    이 패턴만으로 open-set SUSPICIOUS 승격을 허용하지 않는다. detector는
    후보를 계속 생성하고, 알려진 의미 신호나 zero-width/bidi 같은 추가
    변조 신호가 있으면 verifier가 유지할 수 있다.
    """

    if candidate.get("technique") != "HOMOGLYPH":
        return False

    reasons = {
        str(reason).strip()
        for reason in candidate.get("reason", [])
        if str(reason).strip()
    }

    return reasons == {DIGIT_ONLY_HOMOGLYPH_REASON}


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


def _independent_technique_count(techniques):
    """
    동일 요소에서 여러 detector가 울려도 항상 독립 증거는 아니다.

    TRANSPARENT + OFFSCREEN은 같은 CSS 숨김 상태에서 함께 발생하기 쉬우므로
    둘만 겹친 경우에는 1개의 구조 계열 증거로 취급한다. JAMO/HOMOGLYPH처럼
    텍스트 변조 계열이 섞이면 독립적인 추가 증거로 인정한다.
    """

    techniques = set(techniques or [])
    if not techniques:
        return 0

    css_only = {"TRANSPARENT", "OFFSCREEN"}
    if techniques.issubset(css_only):
        return 1

    return len(techniques)


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
        techniques = techniques_by_element[(url, location)]
        multi_technique_count = len(techniques)
        independent_technique_count = _independent_technique_count(techniques)

        return {
            "exact_repeat_count": exact_count,
            "location_repeat_count": location_count,
            "text_repeat_count": text_count,
            "repeat_count": repeat_count,
            "repeat_ratio": repeat_ratio,
            "multi_technique_count": multi_technique_count,
            "independent_technique_count": independent_technique_count,
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


def verify_candidates(candidate_groups, pages=None, profile=None):
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

    profile_enabled = profile is not None
    if profile_enabled:
        profile.clear()
        profile["started"] = time.perf_counter()
        profile["stages"] = defaultdict(float)
        profile["semantic_backends"] = set()

    stage_started = time.perf_counter()
    raw_candidates = [
        candidate
        for group in candidate_groups
        for candidate in group
    ]
    if profile_enabled:
        profile["stages"]["flatten"] += time.perf_counter() - stage_started
        profile["raw_candidate_count"] = len(raw_candidates)

    stage_started = time.perf_counter()
    candidates = _dedupe_candidates(raw_candidates)
    if profile_enabled:
        profile["stages"]["dedupe"] += time.perf_counter() - stage_started
        profile["dedup_candidate_count"] = len(candidates)

    stage_started = time.perf_counter()
    (
        page_titles,
        page_elements,
        page_descendants,
    ) = _build_page_context(pages or [])
    if profile_enabled:
        profile["stages"]["build_page_context"] += (
            time.perf_counter() - stage_started
        )

    stage_started = time.perf_counter()
    visible_text_index = _build_visible_text_index(pages or [])
    if profile_enabled:
        profile["stages"]["build_visible_index"] += (
            time.perf_counter() - stage_started
        )

    stage_started = time.perf_counter()
    page_urls = {
        page.get("url")
        for page in (pages or [])
        if page.get("url")
    }
    total_pages = max(1, len(page_urls))
    repetition_for = _repetition_stats(candidates, total_pages)
    if profile_enabled:
        profile["stages"]["build_repetition"] += (
            time.perf_counter() - stage_started
        )

    verified = []
    rejected = []

    # 같은 텍스트/문맥이 CSS detector 중첩이나 반복 UI 때문에 수백~수천 번
    # 재사용된다. 의미 모델 결과는 순수 함수이므로 per-run cache로 중복 계산을 제거한다.
    legacy_semantic_cache = {}
    multilingual_semantic_cache = {}
    context_cache = {}

    def legacy_details(text):
        key = text or ""
        if key not in legacy_semantic_cache:
            legacy_semantic_cache[key] = semantic_risk_with_support(key)
        return legacy_semantic_cache[key]

    def multilingual_details(text):
        key = text or ""
        if key not in multilingual_semantic_cache:
            multilingual_semantic_cache[key] = multilingual_semantic_details(key)
        result = multilingual_semantic_cache[key]
        if profile_enabled and len(result) >= 2:
            profile["semantic_backends"].add(str(result[1]))
        return result

    loop_started = time.perf_counter()

    for candidate in candidates:
        item = dict(candidate)

        context_started = time.perf_counter() if profile_enabled else None
        context_key = (
            candidate.get("url", ""),
            candidate.get("location", ""),
            _candidate_text(candidate),
        )
        context = context_cache.get(context_key)

        if context is None:
            context = _context_text(
                candidate,
                page_titles,
                page_elements,
                page_descendants,
            )
            context_cache[context_key] = context
        if profile_enabled:
            profile["stages"]["candidate_context"] += (
                time.perf_counter() - context_started
            )

        evidence_text = _candidate_text(candidate)
        normalized_evidence = _normalize_text(evidence_text)
        strong_text_obfuscation = any(
            char in BIDI_OR_ZERO_WIDTH
            for char in (evidence_text or "")
        )
        visible_equivalent_count = len(
            visible_text_index.get(candidate.get("url", ""), {}).get(
                normalized_evidence,
                set(),
            )
        )
        visible_equivalent_present = visible_equivalent_count > 0

        semantic_started = time.perf_counter() if profile_enabled else None
        legacy_evidence, legacy_support = legacy_details(evidence_text)
        legacy_context, legacy_context_support = legacy_details(context)
        (
            multilingual_evidence,
            semantic_backend,
            multilingual_support,
        ) = multilingual_details(evidence_text)
        (
            multilingual_context,
            _,
            multilingual_context_support,
        ) = multilingual_details(context)
        if profile_enabled:
            profile["stages"]["semantic_models"] += (
                time.perf_counter() - semantic_started
            )

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
            0.08 * max(0, repetition["independent_technique_count"] - 1),
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

        open_started = time.perf_counter() if profile_enabled else None
        open_score, open_reasons = open_set_anomaly_score(
            candidate,
            structure_score=structure_score,
            repeat_count=repeat_count,
            repeat_ratio=repeat_ratio,
            multi_technique_count=repetition["independent_technique_count"],
            total_pages=total_pages,
        )
        if profile_enabled:
            profile["stages"]["open_set"] += (
                time.perf_counter() - open_started
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

        # n-gram 모델이 실제로 아는 패턴이 충분히 겹칠 때만 CONFIRMED로 승격한다.
        # "서비스", "이벤트" 같은 일반 단어 몇 개만 겹쳐 두 branch가 동시에 높아지는
        # 정상 문구는 open-set 쪽 판단에 남기고 의미 branch 단독 확정을 막는다.
        semantic_support_ok = max(
            legacy_support,
            multilingual_support,
        ) >= 0.55

        css_visible_duplicate = (
            technique in {"TRANSPARENT", "OFFSCREEN"}
            and visible_equivalent_present
            and not strong_text_obfuscation
        )

        known_confirmed = (
            semantic_score >= semantic_floor
            and known_score >= known_floor
            and semantic_consensus
            and semantic_support_ok
            and not css_visible_duplicate
        )

        if technique in {"JAMO", "HOMOGLYPH"}:
            digit_only_homoglyph = _is_digit_only_homoglyph(candidate)

            if digit_only_homoglyph:
                # ASCII digit-internal은 정상 기술 식별자에서도 매우 흔하다.
                # 구조 점수만으로는 open-set 승격하지 않고, 의미 모델이 실제
                # 학습 패턴을 충분히 지지하거나 zero-width/bidi 변조가 함께
                # 있을 때만 SUSPICIOUS로 유지한다. known_confirmed 경로는
                # 그대로이므로 B0NUS 같은 알려진 광고성 문맥은 계속 잡힌다.
                open_suspicious = (
                    open_score >= 0.60
                    and repeat_count <= 2
                    and (
                        semantic_support_ok
                        or strong_text_obfuscation
                    )
                )
            else:
                open_suspicious = (
                    open_score >= 0.60
                    and repeat_count <= 2
                )
        else:
            # 동일 텍스트가 어떤 scan pass에서 정상적으로 화면 안에 렌더링됐다면
            # 탭/슬라이드/반응형 UI의 상태 복제일 가능성이 높다. 이런 CSS 후보는
            # open-set 구조 점수만으로 SUSPICIOUS로 승격하지 않는다.
            open_suspicious = (
                (
                    not visible_equivalent_present
                    or strong_text_obfuscation
                )
                and (
                    (
                        open_score >= 0.66
                        and structure_score >= 0.60
                        and repeat_count <= 2
                    )
                    or (
                        open_score >= 0.64
                        and repetition["independent_technique_count"] >= 2
                        and structure_score >= 0.60
                        and repeat_count <= 3
                    )
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
        item["legacy_semantic_support"] = round(legacy_support, 3)
        item["legacy_context_support"] = round(legacy_context_support, 3)
        item["multilingual_support"] = round(multilingual_support, 3)
        item["multilingual_context_support"] = round(
            multilingual_context_support,
            3,
        )
        item["semantic_support_ok"] = semantic_support_ok
        item["visible_equivalent_present"] = visible_equivalent_present
        item["visible_equivalent_count"] = visible_equivalent_count
        item["strong_text_obfuscation"] = strong_text_obfuscation
        item["css_visible_duplicate"] = css_visible_duplicate
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
        item["independent_technique_count"] = repetition["independent_technique_count"]
        item["is_violation"] = is_violation

        reason_parts = [
            f"known 의미 {semantic_score:.2f}",
            f"legacy {legacy_branch_score:.2f}",
            f"다국어 {multilingual_branch_score:.2f}",
            f"의미 합의 {semantic_agreement:.2f}",
            (
                "의미 support "
                f"legacy={legacy_support:.2f}, "
                f"multi={multilingual_support:.2f}"
            ),
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
        if visible_equivalent_present:
            reason_parts.append(
                f"동일 텍스트가 정상 화면 상태에서 {visible_equivalent_count}개 위치에 관측"
            )
            if strong_text_obfuscation:
                reason_parts.append(
                    "zero-width/bidi 변조 신호가 있어 visible-state 억제를 우회"
                )
            elif technique in {"TRANSPARENT", "OFFSCREEN"}:
                reason_parts.append(
                    "정상 가시 상태의 동일 문구가 있어 CSS-only CONFIRMED 승격 억제"
                )
        if repetition["multi_technique_count"] >= 2:
            if repetition["independent_technique_count"] >= 2:
                reason_parts.append(
                    f"동일 요소에서 {repetition['multi_technique_count']}개 기법 중첩"
                )
            else:
                reason_parts.append(
                    "TRANSPARENT/OFFSCREEN CSS 중첩은 독립 증거로 가산하지 않음"
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

    if profile_enabled:
        profile["stages"]["candidate_loop"] += time.perf_counter() - loop_started
        profile["legacy_cache_entries"] = len(legacy_semantic_cache)
        profile["multilingual_cache_entries"] = len(multilingual_semantic_cache)
        profile["context_cache_entries"] = len(context_cache)
        profile["verified_count"] = len(verified)
        profile["rejected_count"] = len(rejected)
        profile["total"] = time.perf_counter() - profile["started"]
        profile["stages"] = dict(profile["stages"])
        profile["semantic_backends"] = sorted(profile["semantic_backends"])

    return verified, rejected
