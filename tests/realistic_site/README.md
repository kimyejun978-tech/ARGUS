# ARGUS Realistic Site Benchmark

실제 외부 불법 사이트에 접속하지 않고, 공공기관 게시판과 비슷한 구조에서 ARGUS의 크롤링·오탐 억제·정탐 유지 성능을 검증하는 로컬 전용 벤치마크입니다.

## 구성

- 랜딩 페이지 1개
- 게시판 1개
- 쿼리 기반 공개 게시물 40개
- 의도된 위험 게시물 3개 (`id=12`, `id=27`, `id=34`)
- 정답 positive 5건
- 정상 control 6건
- iframe 내부 은닉 요소 1건 포함
- 정상 skip-link, `display:none` 모달, 모바일 메뉴, 순간 `opacity:0`, 1px 메타정보, 투명 아이콘 라벨 등 오탐 유발 UI 포함
- `id=27`의 일부 정답은 JS로 늦게 삽입되어 5-pass 탐색을 검증

모든 문구와 링크는 로컬 합성 데이터이며 외부 서비스로 연결되지 않습니다.

## 자동 벤치마크

프로젝트 루트에서:

```powershell
python tests\run_realistic_benchmark.py
```

기준을 모두 만족해야 성공하도록 검사하려면:

```powershell
python tests\run_realistic_benchmark.py --strict
```

`--strict`는 최소 페이지 범위, Detector recall, Verifier precision/recall, 정상 control 누출을 함께 확인합니다.

## 수동 실행

```powershell
python -m http.server 8000 --directory tests\realistic_site
```

다른 터미널에서:

```powershell
python main.py
```

입력 URL:

```text
http://127.0.0.1:8000/
```
