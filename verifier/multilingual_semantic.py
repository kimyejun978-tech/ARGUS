import os
from pathlib import Path

from verifier.semantic_model import CharNgramNaiveBayes


# 기본 실행은 외부 API/다운로드 없이 동작한다.
# 한국어와 영어를 포함한 다국어 seed를 문자 n-gram으로 학습해
# 기존 한국어 위주 모델의 언어 편향을 줄인다.
MULTILINGUAL_POSITIVE_SEEDS = [
    "불법 광고 회원 모집 가입 혜택 안내",
    "우회 주소 접속 신규 회원 이벤트",
    "사설 서비스 가입 코드 홍보",
    "신규 회원 보너스 지급 홍보",
    "hidden promotion join now claim bonus",
    "private betting promotion register now",
    "online casino promotion new member bonus",
    "unauthorized gambling advertisement sign up now",
    "adult advertisement members only access",
    "join with referral code and claim reward",
    "registro promocion bono nuevos miembros",
    "publicite promotionnelle inscription bonus",
    "新規 会員 登録 ボーナス 広告",
    "会员 注册 奖励 广告",
]

MULTILINGUAL_NEGATIVE_SEEDS = [
    "Telegram",
    "social apps Telegram Instagram WhatsApp",
    "download the app and message your friends",
    "create an account",
    "sign in to your account",
    "privacy policy and terms of service",
    "customer support contact us",
    "official product promotion",
    "start free trial",
    "popular apps for Chromebook",
    "account balance and payment settings",
    "newsletter subscription",
    "help center frequently asked questions",
    "skip to main content",
    "skip navigation",
    "skip to primary content",
    "accessibility skip link",
    "공식 앱 목록",
    "개인정보 처리방침",
    "회원 가입",
    "계정 설정",
    "고객센터 문의",
    "무료 체험 시작하기",
    "공식 제품 프로모션",
    "본문 바로가기",
    "메뉴 바로가기",
    "주요 콘텐츠 바로가기",
    "콘텐츠로 바로가기",
    "アプリをダウンロード",
    "プライバシーポリシー",
    "メインコンテンツへスキップ",
    "隐私政策",
    "下载应用",
    "跳到主要内容",
]


_FALLBACK_MODEL = CharNgramNaiveBayes(
    positive_examples=MULTILINGUAL_POSITIVE_SEEDS,
    negative_examples=MULTILINGUAL_NEGATIVE_SEEDS,
)


class _OptionalSentenceTransformerBackend:
    """
    선택적 로컬 다국어 sentence embedding backend.

    ARGUS_MULTILINGUAL_MODEL에 로컬 모델 폴더를 지정했고
    sentence-transformers가 설치돼 있을 때만 사용한다.
    네트워크 다운로드를 시도하지 않으며, 조건이 맞지 않으면 즉시 fallback한다.
    """

    def __init__(self):
        self.model = None
        self.positive_vectors = None
        self.negative_vectors = None
        self.backend_name = "char-ngram-multilingual"

        model_path = os.getenv("ARGUS_MULTILINGUAL_MODEL", "").strip()
        if not model_path:
            return

        path = Path(model_path)
        if not path.exists():
            return

        try:
            from sentence_transformers import SentenceTransformer
        except Exception:
            return

        try:
            model = SentenceTransformer(str(path), device="cpu")
            positive_vectors = model.encode(
                MULTILINGUAL_POSITIVE_SEEDS,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            negative_vectors = model.encode(
                MULTILINGUAL_NEGATIVE_SEEDS,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception:
            return

        self.model = model
        self.positive_vectors = positive_vectors
        self.negative_vectors = negative_vectors
        self.backend_name = "local-sentence-transformer"

    def score(self, text):
        if self.model is None:
            return None

        try:
            vector = self.model.encode(
                [text or ""],
                normalize_embeddings=True,
                show_progress_bar=False,
            )[0]

            positive_similarity = max(
                float(vector @ prototype)
                for prototype in self.positive_vectors
            )
            negative_similarity = max(
                float(vector @ prototype)
                for prototype in self.negative_vectors
            )

            # 양/음 prototype과의 상대적 거리를 0~1로 매핑한다.
            margin = positive_similarity - negative_similarity
            score = 0.5 + 0.5 * max(-1.0, min(1.0, margin * 2.0))
            return max(0.0, min(1.0, score))
        except Exception:
            return None


_OPTIONAL_BACKEND = _OptionalSentenceTransformerBackend()


def multilingual_semantic_details(text):
    """(score, backend_name, semantic_support)을 반환한다."""

    embedding_score = _OPTIONAL_BACKEND.score(text)

    if embedding_score is not None:
        # embedding backend는 고정 vocabulary overlap 개념이 없으므로
        # 모델이 실제로 로드되어 점수를 냈다면 support를 충분한 것으로 본다.
        return embedding_score, _OPTIONAL_BACKEND.backend_name, 1.0

    score, support = _FALLBACK_MODEL.predict_details(text or "")
    return score, _OPTIONAL_BACKEND.backend_name, support


def multilingual_semantic_score(text):
    """기존 호출부 호환용 (score, backend_name) API."""

    score, backend_name, _ = multilingual_semantic_details(text)
    return score, backend_name
