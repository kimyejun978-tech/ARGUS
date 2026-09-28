import re
from urllib.parse import urlsplit

from url_risk import BRAND_PROFILES, analyze_url_risk


AUTH_RE = re.compile(
    r"\b(login|log in|sign in|verify|verification|password|account|security code|otp)\b"
    r"|로그인|비밀번호|계정|본인.?확인|인증|인증번호",
    re.IGNORECASE,
)


def _host(url):
    try:
        return (urlsplit(str(url or "")).hostname or "").casefold().strip(".")
    except Exception:
        return ""


def _is_official_host(hostname, official_domains):
    return any(
        hostname == domain or hostname.endswith("." + domain)
        for domain in official_domains
    )


def _combined_text(page):
    chunks = [str(page.get("title", ""))]
    for state in page.get("security_states", []) or []:
        for key in (
            "title",
            "visibleText",
        ):
            chunks.append(str(state.get(key, "")))
        for key in (
            "headings",
            "labels",
            "imageAlts",
            "ariaLabels",
            "placeholders",
        ):
            chunks.extend(str(item) for item in (state.get(key, []) or []))
    return " ".join(chunks).casefold()


def _alias_in_text(alias, text):
    alias = str(alias).casefold()
    if not alias:
        return False
    if alias.isascii() and alias.replace("-", "").isalnum():
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", text))
    return alias in text


def _brand_mismatches(page_url, text):
    hostname = _host(page_url)
    matches = []
    for brand, aliases, official_domains in BRAND_PROFILES:
        if _is_official_host(hostname, official_domains):
            continue
        alias = next(
            (
                alias
                for alias in aliases
                if _alias_in_text(alias, text)
            ),
            None,
        )
        if alias:
            matches.append(
                {
                    "brand": brand,
                    "matched_text": alias,
                    "official_domains": list(official_domains),
                }
            )
    return matches


def _collect_form_signals(page_url, states):
    hostname = _host(page_url)
    has_password = False
    identifier_count = 0
    external_actions = set()
    external_iframes = set()

    for state in states:
        input_types = state.get("inputTypes", {}) or {}
        has_password = has_password or int(input_types.get("password", 0) or 0) > 0

        for form in state.get("forms", []) or []:
            has_password = has_password or bool(form.get("hasPassword"))
            identifier_count += int(form.get("identifierCount", 0) or 0)
            action = str(form.get("action", "") or "")
            action_host = _host(action)
            if action_host and hostname and action_host != hostname:
                external_actions.add(action)

        for frame_url in state.get("iframeUrls", []) or []:
            frame_host = _host(frame_url)
            if frame_host and hostname and frame_host != hostname:
                external_iframes.add(str(frame_url))

    return {
        "has_password": has_password,
        "identifier_count": identifier_count,
        "external_actions": sorted(external_actions),
        "external_iframes": sorted(external_iframes),
    }


def analyze_phishing_page(page):
    """Return an auxiliary phishing-risk finding for one rendered page.

    The analyzer never submits forms, reads credential values, or contacts a
    reputation service. A finding is a risk signal, not proof of phishing.
    """

    page_url = str(page.get("url", "") or "")
    if not page_url:
        return None

    states = list(page.get("security_states", []) or [])
    text = _combined_text(page)
    auth_language = bool(AUTH_RE.search(text))
    form = _collect_form_signals(page_url, states)
    domain_findings = analyze_url_risk(page_url)
    brand_mismatches = _brand_mismatches(page_url, text)

    signals = []
    score = 0.0

    if domain_findings:
        finding = domain_findings[0]
        signals.append(
            {
                "name": "DOMAIN_IMPERSONATION",
                "weight": 0.36,
                "detail": finding.get("reason", "도메인 사칭 신호"),
            }
        )
        score += 0.36

    if brand_mismatches:
        brand = brand_mismatches[0]
        signals.append(
            {
                "name": "BRAND_DOMAIN_MISMATCH",
                "weight": 0.32,
                "detail": (
                    f"{brand['brand']} 표시가 공식 도메인이 아닌 페이지에서 관측됨"
                ),
            }
        )
        score += 0.32
    else:
        brand = None

    if form["has_password"]:
        signals.append(
            {
                "name": "PASSWORD_FIELD",
                "weight": 0.18,
                "detail": "비밀번호 입력 필드가 렌더링됨",
            }
        )
        score += 0.18

    if form["identifier_count"] > 0:
        signals.append(
            {
                "name": "IDENTIFIER_FIELD",
                "weight": 0.05,
                "detail": "계정/이메일 식별 입력 필드가 함께 관측됨",
            }
        )
        score += 0.05

    if auth_language:
        signals.append(
            {
                "name": "AUTHENTICATION_LANGUAGE",
                "weight": 0.08,
                "detail": "로그인·인증 관련 문구가 관측됨",
            }
        )
        score += 0.08

    if form["external_actions"]:
        signals.append(
            {
                "name": "CROSS_ORIGIN_FORM_ACTION",
                "weight": 0.20,
                "detail": "폼 action이 현재 페이지와 다른 호스트를 가리킴",
            }
        )
        score += 0.20

    if form["external_iframes"] and (form["has_password"] or auth_language):
        signals.append(
            {
                "name": "CROSS_ORIGIN_AUTH_IFRAME",
                "weight": 0.08,
                "detail": "인증 문맥에서 외부 호스트 iframe이 관측됨",
            }
        )
        score += 0.08

    identity_risk = bool(domain_findings or brand_mismatches)
    credential_context = bool(form["has_password"] or auth_language)
    external_credential = bool(form["has_password"] and form["external_actions"])

    # Normal login pages are intentionally not flagged only because they have
    # a password field or an SSO iframe. Identity mismatch is the primary gate.
    should_flag = (
        (identity_risk and credential_context)
        or (identity_risk and form["external_actions"])
        or (external_credential and bool(brand_mismatches))
    )
    if not should_flag:
        return None

    score = round(min(score, 1.0), 3)
    risk = "HIGH_RISK" if score >= 0.72 and form["has_password"] else "SUSPICIOUS"
    reason = "; ".join(signal["detail"] for signal in signals[:4])

    return {
        "type": "PHISHING_RISK",
        "risk": risk,
        "page_url": page_url,
        "score": score,
        "signals": signals,
        "reason": reason,
        "brand": brand["brand"] if brand else (
            domain_findings[0].get("brand") if domain_findings else ""
        ),
        "hostname": _host(page_url),
        "external_form_actions": form["external_actions"],
        "external_iframes": form["external_iframes"],
        "blocked": False,
    }


def analyze_phishing_pages(pages):
    findings = []
    seen = set()
    for page in pages or []:
        finding = analyze_phishing_page(page)
        if not finding:
            continue
        key = (finding.get("type"), finding.get("page_url"))
        if key in seen:
            continue
        seen.add(key)
        findings.append(finding)
    return findings
