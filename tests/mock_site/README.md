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

모든 문구와 링크는 로컬 테스트용 합성 데이터이며 실제 서비스로 연결되지 않습니다.

## 기본 mock_site 실행
ARGUS 프로젝트 루트에서:

```powershell
python -m http.server 8000 --directory tests\mock_site
```

새 터미널에서:

```powershell
python main.py
```

검사 URL:

```text
http://127.0.0.1:8000/
```

## Verifier benchmark
`benchmark/`는 기존 detector fixture와 분리된 end-to-end 평가 세트입니다.

- positive 20건: TRANSPARENT / OFFSCREEN / JAMO / HOMOGLYPH / iframe
- benign control 8건
- `ground_truth.json`에 정답을 고정
- 실제 외부 사이트 접속 없이 임시 localhost 서버를 자동 생성
- Detector recall, Verifier precision/recall/F1, 기법별 결과를 자동 계산

프로젝트 루트에서 한 줄로 실행:

```powershell
python tests\run_mock_benchmark.py
```

현재 기준을 완전히 통과해야 exit code 0으로 강제하고 싶다면:

```powershell
python tests\run_mock_benchmark.py --strict
```

처음 튜닝할 때는 `--strict` 없이 실행해서 누락된 case와 예상하지 않은 최종 유지 후보를 먼저 확인하는 것을 권장합니다.
