# ARGUS Mock Site

실제 불법 사이트에 접속하지 않고 ARGUS 탐지 성능을 검증하기 위한 로컬 전용 모의 사이트입니다.

## 포함한 패턴
- 배너/이벤트 중심 랜딩 페이지
- 게시판과 하위 게시물 링크
- JAMO 자모 분해
- HOMOGLYPH(키릴/전각/숫자 혼용)
- TRANSPARENT(opacity:0, color:transparent, 배경과 동일 색상)
- OFFSCREEN(left:-9999px, 1px 글자)
- iframe 내부 은닉/자모 분해
- 정상 `display:none` UI와 정상 below-the-fold 콘텐츠(오탐 회귀 테스트)
- `HTML5` 같은 정상 숫자 포함 문자열(오탐 회귀 테스트)

모든 문구와 링크는 안전한 테스트용이며 실제 도박/불법 서비스로 연결되지 않습니다.

## 실행
ARGUS 프로젝트 루트에서:

```powershell
cd tests\mock_site
python -m http.server 8000
```

새 터미널에서 프로젝트 루트로 돌아간 뒤:

```powershell
python main.py
```

검사 URL:

```text
http://localhost:8000/
```
