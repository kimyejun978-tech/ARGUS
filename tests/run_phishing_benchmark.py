"""Offline phishing-risk benchmark using sanitized metadata cases.

This runner intentionally does not contact live suspicious sites. Replace or
extend CASES with sanitized captures from an approved offline corpus.
"""

from phishing_analyzer import analyze_phishing_page
from tests.test_phishing_analyzer import page


CASES = [
    ("official_login", False, page("https://facebook.com/login", text="Facebook login account password", password=True)),
    ("generic_portal", False, page("https://civic-service.test/login", text="시민서비스 로그인", password=True)),
    ("external_sso", False, page("https://school.example.test/login", text="Sign in to student portal", password=True, action="https://identity.example.test/session")),
    ("typo_brand_login", True, page("https://twtch-login.test/account", text="Twitch login account password", password=True)),
    ("brand_mismatch", True, page("https://account-center.test/signin", text="PayPal sign in account password", password=True)),
    ("brand_mismatch_auth", True, page("https://security-check.test/verify", text="Microsoft account verification", password=False)),
]


def main():
    tp = fp = tn = fn = 0
    for name, expected, sample in CASES:
        predicted = analyze_phishing_page(sample) is not None
        if expected and predicted:
            tp += 1
        elif expected and not predicted:
            fn += 1
        elif not expected and predicted:
            fp += 1
        else:
            tn += 1
        print(f"{name:24s} expected={expected} predicted={predicted}")

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    print()
    print("dataset: sanitized-pattern benchmark (not live-site performance)")
    print("samples:", len(CASES))
    print("TP:", tp, "FP:", fp, "TN:", tn, "FN:", fn)
    print(f"precision: {precision:.3f}")
    print(f"recall: {recall:.3f}")
    print(f"F1: {f1:.3f}")
    print(f"false positive rate: {fpr:.3f}")


if __name__ == "__main__":
    main()
