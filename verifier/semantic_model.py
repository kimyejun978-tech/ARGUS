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

    중요한 open-set 안전장치:
    - 학습 vocabulary에 전혀 없는 n-gram은 분류 증거로 사용하지 않는다.
    - 입력 중 학습 vocabulary와 실제로 겹치는 비율을 semantic support로 계산한다.
    - support가 낮으면 posterior를 0.5 쪽으로 수축한다.

    이 처리가 없으면 완전히 처음 보는 문자열도 클래스별 전체 n-gram 수 차이 때문에
    한쪽 확률이 비정상적으로 높아질 수 있다. 그런 OOD 텍스트는 의미 모델이
    억지로 CONFIRMED하지 않고 open-set branch가 판단하도록 넘기는 것이 목적이다.
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

    def predict_details(self, text: str):
        """(위험 확률, semantic support)을 반환한다."""

        all_grams = _char_ngrams(text)

        if not all_grams:
            return 0.5, 0.0

        total_gram_count = sum(all_grams.values())
        known_grams = Counter(
            {
                gram: count
                for gram, count in all_grams.items()
                if gram in self.vocabulary
            }
        )
        known_gram_count = sum(known_grams.values())
        support = known_gram_count / max(1, total_gram_count)

        # 완전히 미지의 텍스트는 의미 모델이 추측하지 않는다.
        if not known_grams:
            return 0.5, 0.0

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

            # OOV gram은 클래스별 denominator 차이만 누적시켜 오판을 만들 수 있으므로
            # vocabulary에 실제로 존재하는 gram만 likelihood 계산에 사용한다.
            for gram, count in known_grams.items():
                numerator = (
                    self.class_counts[label].get(gram, 0)
                    + self.alpha
                )
                score += count * math.log(numerator / denominator)

            log_scores[label] = score

        logit = log_scores[1] - log_scores[0]
        logit = max(-30.0, min(30.0, logit))
        probability = 1.0 / (1.0 + math.exp(-logit))

        normalized = _normalize_text(text)
        informative_chars = sum(char.isalnum() for char in normalized)
        length_confidence = min(1.0, informative_chars / 14.0)

        # vocabulary overlap가 약 35% 이상일 때 의미 모델의 확률을 온전히 신뢰한다.
        # 그보다 낮으면 0.5 쪽으로 수축시켜 open-set branch에 판단권을 넘긴다.
        support_confidence = min(1.0, support / 0.35)
        confidence = length_confidence * support_confidence

        calibrated = 0.5 + (probability - 0.5) * confidence
        return calibrated, support

    def predict_proba(self, text: str) -> float:
        probability, _ = self.predict_details(text)
        return probability

    def semantic_support(self, text: str) -> float:
        _, support = self.predict_details(text)
        return support


DEFAULT_MODEL = CharNgramNaiveBayes()


def semantic_risk_probability(text: str) -> float:
    return DEFAULT_MODEL.predict_proba(text)


def semantic_risk_with_support(text: str):
    return DEFAULT_MODEL.predict_details(text)
