import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path


SEED_PATH = Path(__file__).with_name("semantic_seed.json")


def _load_seed_corpus():
    """
    의미 분류 학습 데이터를 코드와 분리한다.
    실제 라벨 데이터가 쌓이면 semantic_seed.json만 교체하면 되고
    verifier 로직 자체를 수정할 필요가 없다.
    """

    try:
        with SEED_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)

        positives = [
            str(item).strip()
            for item in data.get("positive", [])
            if str(item).strip()
        ]
        negatives = [
            str(item).strip()
            for item in data.get("negative", [])
            if str(item).strip()
        ]

        if positives and negatives:
            return positives, negatives
    except (OSError, ValueError, TypeError):
        pass

    # 패키징 누락 등 비정상 상황에서도 실행 자체는 가능하게 하는 최소 fallback.
    return (
        ["불법 광고 회원 모집", "우회 광고 가입 유도"],
        ["로그인", "회원 가입", "개인정보 처리방침", "앱 목록"],
    )


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"\s+", " ", text).strip()


def _char_ngrams(text: str, min_n=2, max_n=5):
    normalized = _normalize_text(text)

    if not normalized:
        return Counter()

    wrapped = "^" + normalized + "$"
    grams = Counter()

    for n in range(min_n, max_n + 1):
        if len(wrapped) < n:
            continue

        for index in range(len(wrapped) - n + 1):
            grams[wrapped[index:index + n]] += 1

    return grams


class CharNgramNaiveBayes:
    """
    외부 API/GPU가 필요 없는 초경량 문자 n-gram Multinomial Naive Bayes.

    단일 키워드 포함 여부가 아니라 여러 문자 조합의 분포를 함께 평가한다.
    학습 데이터는 semantic_seed.json에서 읽기 때문에 향후 실제 라벨 데이터로
    교체해도 이 코드의 판정 로직은 바뀌지 않는다.
    """

    def __init__(self, positive_examples=None, negative_examples=None, alpha=0.5):
        self.alpha = float(alpha)
        self.class_counts = {0: Counter(), 1: Counter()}
        self.doc_counts = {0: 0, 1: 0}
        self.total_ngrams = {0: 0, 1: 0}
        self.vocabulary = set()

        if positive_examples is None or negative_examples is None:
            loaded_positive, loaded_negative = _load_seed_corpus()
            positives = positive_examples or loaded_positive
            negatives = negative_examples or loaded_negative
        else:
            positives = positive_examples
            negatives = negative_examples

        self._fit(positives, negatives)

    def _fit(self, positives, negatives):
        for label, examples in ((1, positives), (0, negatives)):
            for text in examples:
                grams = _char_ngrams(text)
                self.class_counts[label].update(grams)
                self.doc_counts[label] += 1

        self.vocabulary = (
            set(self.class_counts[0])
            | set(self.class_counts[1])
        )

        for label in (0, 1):
            self.total_ngrams[label] = sum(
                self.class_counts[label].values()
            )

    def predict_proba(self, text: str) -> float:
        grams = _char_ngrams(text)

        if not grams:
            return 0.5

        total_docs = self.doc_counts[0] + self.doc_counts[1]
        vocab_size = max(1, len(self.vocabulary))
        log_scores = {}

        for label in (0, 1):
            prior = (
                (self.doc_counts[label] + 1)
                / (total_docs + 2)
            )
            score = math.log(prior)
            denominator = (
                self.total_ngrams[label]
                + self.alpha * vocab_size
            )

            for gram, count in grams.items():
                numerator = (
                    self.class_counts[label].get(gram, 0)
                    + self.alpha
                )
                score += count * math.log(numerator / denominator)

            log_scores[label] = score

        logit = log_scores[1] - log_scores[0]
        logit = max(-30.0, min(30.0, logit))
        probability = 1.0 / (1.0 + math.exp(-logit))

        # 짧은 단일 토큰은 모델이 과신하지 않도록 0.5 쪽으로 완만하게 수축한다.
        informative_chars = sum(
            char.isalnum()
            for char in _normalize_text(text)
        )
        confidence = min(1.0, informative_chars / 14.0)

        return 0.5 + (probability - 0.5) * confidence


DEFAULT_MODEL = CharNgramNaiveBayes()


def semantic_risk_probability(text: str) -> float:
    return DEFAULT_MODEL.predict_proba(text)
