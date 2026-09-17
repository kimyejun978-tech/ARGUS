# ARGUS Adversarial Open-Set Site

ARGUS가 기존 의미 seed와 겹치지 않는 새로운 표현을 구조적 이상도로 살릴 수 있는지 확인하는 로컬 전용 합성 사이트입니다.

- 외부 서비스 연결 없음
- 실제 광고/계정/결제 기능 없음
- 20개 일반 게시물 + 공통 정상 UI 노이즈
- 모바일에서만 등장하는 합성 후보
- zero-width 문자가 섞인 TRANSPARENT/OFFSCREEN 후보
- 의미가 중립적인 JAMO/HOMOGLYPH 후보
- 늦게 삽입되는 iframe 내부 후보
- 반복되는 skip-link/접근성 도우미/모바일 메뉴/1px 메타데이터 등 정상 대조군

실행:

```powershell
python tests\run_adversarial_benchmark.py
```

현재 benchmark의 positive는 known-semantic CONFIRMED가 아니라 open-set `SUSPICIOUS`로 유지되는 것을 기대합니다. 먼저 일반 모드로 결과를 확인하고, 기준이 안정된 뒤 `--strict`를 사용하세요.
