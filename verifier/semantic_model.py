import math
import re
import unicodedata
from collections import Counter


# 외부 API/GPU 없이 실행 가능한 초경량 문자 n-gram 분류기.
# 단일 키워드 포함 여부가 아니라 여러 문자 조합의 분포를 함께 본다.
# seed 문장은 실제 사이트 주소/서비스를 포함하지 않는 합성 학습 예시다.
POSITIVE_SEEDS = [
    "불법 광고 회원 모집 충전 환전 안내",
    "사설 서비스 신규 가입 혜택 지급",
    "우회 주소 접속 회원 가입 이벤트",
    "가입 코드 문의 신규 회원 혜택",
    "실시간 베팅 서비스 가입 보너스",
    "슬롯 이벤트 신규 회원 충전 혜택",
    "카지노 이벤트 가입 후 혜택 지급",
    "불법 도박 홍보 가입 충전 환전",
    "사설 토토 가입 코드 이벤트",
    "바카라 신규 회원 이벤트",
    "온라인 카지노 가입 보너스",
    "베팅 사이트 가입 및 충전 안내",
    "성인 광고 회원 전용 바로가기",
    "19금 광고 가입 문의",
    "제휴 문의 우회 링크 회원 모집",
    "고액 배당 신규 회원 가입 혜택",
    "실시간 게임 베팅 충전 이벤트",
    "가입 즉시 보너스 지급 환전 가능",
]

NEGATIVE_SEEDS = [
    "Telegram",
    "Telegram 앱으로 메시지를 보내세요",
    "소셜 앱 목록 Telegram Instagram WhatsApp",
    "앱을 다운로드하고 친구와 대화하세요",
    "개인정보 처리방침",
    "이용약관 및 개인정보 보호",
    "로그인",
    "회원 가입",
    "계정 만들기",
    "비밀번호 찾기",
    "고객센터 문의",
    "앱 목록",
    "게임 앱을 설치하세요",
    "Chromebook에서 인기 앱을 사용하세요",
    "메신저 앱으로 친구와 연락하세요",
    "뉴스레터 구독 신청",
    "결제 수단을 관리하세요",
    "계정 충전 잔액을 확인하세요",
    "출금 계좌를 등록하세요",
    "이벤트 참여 혜택 안내",
    "공식 제품 프로모션",
    "무료 체험 시작하기",
    "지원 센터",
    "다운로드",
    "공유",
    "앱 열기",
    "설정 저장",
    "서비스 소개",
    "제품 기능 살펴보기",
    "알림 켜기",
    "언어 선택",
    "도움말",
    "자주 묻는 질문",
    "공식 커뮤니티",
    "소셜 미디어 앱",
]


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
    작은 합성 seed corpus로 즉시 학습하는 Multinomial Naive Bayes.

    목적은 완성형 ML 모델이 아니라 단일 키워드 if문을 제거하고,
    문자 조합과 주변 문맥을 함께 평가할 수 있는 가벼운 기본 모델을 제공하는 것이다.
    추후 실제 라벨 데이터가 생기면 seed 대신 외부 학습 데이터로 교체할 수 있다.
    """

    def __init__(self, positive_examples=None, negative_examples=None, alpha=0.5):
        self.alpha = float(alpha)
        self.class_counts = {0: Counter(), 1: Counter()}
        self.doc_counts = {0: 0, 1: 0}
        self.total_ngrams = {0: 0, 1: 0}
        self.vocabulary = set()

        positives = positive_examples or POSITIVE_SEEDS
        negatives = negative_examples or NEGATIVE_SEEDS

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
