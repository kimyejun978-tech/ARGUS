import unicodedata
from urllib.parse import urlsplit


BRAND_PROFILES = (
    ("Facebook", ("facebook", "페이스북"), ("facebook.com", "fb.com")),
    ("Twitch", ("twitch", "트위치"), ("twitch.tv",)),
    ("Instagram", ("instagram", "인스타그램"), ("instagram.com",)),
    ("Google", ("google", "구글"), ("google.com",)),
    ("Microsoft", ("microsoft", "마이크로소프트"), ("microsoft.com",)),
    ("Apple", ("apple", "애플"), ("apple.com",)),
    ("Naver", ("naver", "네이버"), ("naver.com",)),
    ("Kakao", ("kakao", "카카오"), ("kakao.com",)),
    ("PayPal", ("paypal", "페이팔"), ("paypal.com",)),
    ("Netflix", ("netflix", "넷플릭스"), ("netflix.com",)),
    ("Amazon", ("amazon", "아마존"), ("amazon.com",)),
    ("Discord", ("discord", "디스코드"), ("discord.com",)),
    ("Telegram", ("telegram", "텔레그램"), ("telegram.org",)),
    ("Coupang", ("coupang", "쿠팡"), ("coupang.com",)),
)

COMMON_SECOND_LEVEL_SUFFIXES = {
    "co.kr",
    "or.kr",
    "go.kr",
    "ac.kr",
    "co.uk",
    "org.uk",
    "com.au",
    "com.br",
    "co.jp",
}

CONFUSABLE_TO_ASCII = str.maketrans(
    {
        # Cyrillic
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "х": "x",
        "у": "y",
        "і": "i",
        "ј": "j",
        # Greek
        "α": "a",
        "ε": "e",
        "ι": "i",
        "κ": "k",
        "ο": "o",
        "ρ": "p",
        "τ": "t",
        "χ": "x",
        "υ": "y",
        # Common digit substitutions
        "0": "o",
        "1": "l",
        "3": "e",
        "5": "s",
        "7": "t",
    }
)


def _decode_hostname(hostname):
    labels = []
    for label in (hostname or "").strip(".").split("."):
        try:
            labels.append(label.encode("ascii").decode("idna"))
        except (UnicodeError, UnicodeEncodeError):
            labels.append(label)
    return ".".join(labels).casefold()


def _is_official_host(hostname, official_domains):
    return any(
        hostname == domain or hostname.endswith("." + domain)
        for domain in official_domains
    )


def _registrable_label(hostname):
    labels = hostname.split(".")
    if len(labels) < 2:
        return labels[0] if labels else ""

    suffix2 = ".".join(labels[-2:])
    if suffix2 in COMMON_SECOND_LEVEL_SUFFIXES and len(labels) >= 3:
        return labels[-3]
    return labels[-2]


def _ascii_skeleton(value):
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return normalized.translate(CONFUSABLE_TO_ASCII)


def _edit_distance(left, right):
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1]
                    + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _match_brand(hostname, decoded_hostname, profile):
    brand, aliases, official_domains = profile
    if _is_official_host(hostname, official_domains):
        return None

    decoded_labels = [label for label in decoded_hostname.split(".") if label]
    registrable = _registrable_label(decoded_hostname)
    candidates = {registrable}
    candidates.update(decoded_labels)
    for label in decoded_labels:
        candidates.update(part for part in label.split("-") if part)

    for alias in aliases:
        normalized_alias = unicodedata.normalize("NFKC", alias).casefold()
        if normalized_alias in candidates:
            return {
                "brand": brand,
                "signal": "BRAND_ALIAS",
                "matched_text": normalized_alias,
                "official_domains": list(official_domains),
                "confidence": "HIGH",
            }

        if not normalized_alias.isascii() or len(normalized_alias) < 5:
            continue

        for candidate in candidates:
            skeleton = _ascii_skeleton(candidate)
            if not skeleton.isascii():
                continue

            if skeleton == normalized_alias and candidate != normalized_alias:
                return {
                    "brand": brand,
                    "signal": "DOMAIN_HOMOGLYPH",
                    "matched_text": candidate,
                    "official_domains": list(official_domains),
                    "confidence": "HIGH",
                }

            if abs(len(skeleton) - len(normalized_alias)) <= 1 and (
                _edit_distance(skeleton, normalized_alias) == 1
            ):
                return {
                    "brand": brand,
                    "signal": "DOMAIN_TYPOSQUAT",
                    "matched_text": candidate,
                    "official_domains": list(official_domains),
                    "confidence": "MEDIUM",
                }

    return None


def analyze_url_risk(url):
    """Return offline hostname impersonation diagnostics for one URL.

    These findings are auxiliary warnings, not proof that a site is phishing.
    No DNS, reputation service, or target-site request is performed.
    """

    parsed = urlsplit(str(url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return []

    hostname = parsed.hostname.strip(".").casefold()
    decoded_hostname = _decode_hostname(hostname)
    findings = []

    for profile in BRAND_PROFILES:
        match = _match_brand(hostname, decoded_hostname, profile)
        if match is None:
            continue

        signal = match["signal"]
        reason_by_signal = {
            "BRAND_ALIAS": "브랜드 별칭이 공식 도메인이 아닌 주소에 사용됨",
            "DOMAIN_HOMOGLYPH": "브랜드 도메인과 혼동 가능한 유사 문자가 사용됨",
            "DOMAIN_TYPOSQUAT": "브랜드 도메인과 한 글자 차이인 오타형 주소",
        }
        findings.append(
            {
                "type": "DOMAIN_IMPERSONATION_RISK",
                "risk": "SUSPICIOUS",
                "page_url": str(url),
                "requested_url": str(url),
                "hostname": hostname,
                "display_hostname": decoded_hostname,
                "brand": match["brand"],
                "signal": signal,
                "matched_text": match["matched_text"],
                "official_domains": match["official_domains"],
                "confidence": match["confidence"],
                "reason": reason_by_signal[signal],
                "blocked": False,
            }
        )
        break

    return findings
