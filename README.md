# ARGUS

> 공공 웹사이트의 은닉·우회 광고 표현을 자동으로 탐색하고 검증하는 Windows 데스크톱 점검 도구

ARGUS는 하나의 시작 URL을 입력하면 하위 페이지를 자동으로 탐색하고, 브라우저 렌더링 상태를 분석해 화면에 숨겨진 광고성 표현이나 우회 표기를 찾아내는 프로젝트입니다.

단순히 숨겨진 DOM 요소를 모두 탐지 결과로 내보내지 않고, 구조 탐지 이후 별도의 검증 단계를 거쳐 정상 UI 가능성이 높은 후보를 제외합니다.

---

## 주요 기능

- **시작 URL 1개로 자동 탐색**
  - 같은 사이트의 하위 페이지를 자동 발견
  - HTML 링크, robots.txt, sitemap 기반 discovery
  - iframe 내부 요소 분석
- **Playwright 기반 실제 브라우저 분석**
  - 데스크톱 즉시 상태
  - 데스크톱 안정화 상태
  - 데스크톱 스크롤 상태
  - 모바일 안정화 상태
  - 모바일 스크롤 상태
- **4가지 핵심 탐지 기법**
  - TRANSPARENT
  - OFFSCREEN
  - JAMO
  - HOMOGLYPH
- **후보 검증**
  - 구조 탐지만으로 바로 확정하지 않음
  - 문맥·의미·반복 패턴 등을 함께 검토
  - CONFIRMED, SUSPICIOUS, BENIGN_LIKELY로 구분
- **자동 다운로드 안전 처리**
  - 웹사이트가 다운로드를 시도해도 파일을 저장·실행하지 않음
  - 관련 이벤트는 공식 탐지와 분리된 보조 진단으로 기록
- **Auto-Tune**
  - 실행 환경의 CPU/RAM과 짧은 벤치마크 결과를 바탕으로 적절한 browser worker 수 선택
- **GUI**
  - pywebview + HTML/CSS/JavaScript
  - 검사 시작/중지
  - 현재 검사 URL
  - 분석 완료 페이지
  - 경과 시간
  - 공식 탐지 결과
  - 보조 위험 진단
  - 시스템 로그

---

## 탐지 기법

| Technique | 설명 |
| --- | --- |
| TRANSPARENT | 투명도, 투명 색상, 배경과 동일한 색상 등으로 숨겨진 텍스트 후보 |
| OFFSCREEN | 화면 밖 좌표, 극단적으로 작은 글자 등으로 보이지 않게 배치된 후보 |
| JAMO | 완성형 한글 대신 분리된 자모 조합을 사용하는 우회 표현 후보 |
| HOMOGLYPH | 서로 비슷하게 보이는 문자·숫자·다른 문자 체계를 섞은 우회 표현 후보 |

ARGUS는 위 조건에 해당한다는 이유만으로 결과를 확정하지 않습니다. 탐지 후보는 verifier를 거쳐 최종 판정됩니다.

---

## 동작 흐름

~~~text
입력 URL
   ↓
HTTP discovery + Playwright browser crawl
   ↓
페이지별 5-pass DOM 관측
   ↓
TRANSPARENT / OFFSCREEN / JAMO / HOMOGLYPH detector
   ↓
contextual verifier
   ↓
공식 결과: result.json
보조 진단: result_extra.json
~~~

---

## 기술 스택

- Python
- Playwright
- pywebview
- HTML / CSS / JavaScript
- asyncio

---

## 프로젝트 구조

~~~text
ARGUS/
├─ main.py                  # CLI 실행 및 전체 분석 파이프라인
├─ gui.py                   # 기본 데스크톱 GUI 실행 진입점
├─ desktop.py               # pywebview window
├─ desktop_api.py           # Web UI ↔ Python bridge
├─ crawler.py               # 페이지 DOM 수집
├─ crawler_parallel.py      # 병렬 브라우저/HTTP crawler
├─ fast_discovery.py        # robots/sitemap/HTML discovery
├─ autotune.py              # worker Auto-Tune
├─ detectors/
│  ├─ transparent.py
│  ├─ offscreen.py
│  ├─ jamo.py
│  └─ homoglyph.py
├─ verifier/                # 후보 검증
├─ webui/                   # HTML/CSS/JS GUI
├─ json_exporter.py         # 공식 result.json
├─ extra_exporter.py        # 보조 result_extra.json
├─ result_validator.py      # result.json validator
└─ tests/                   # unit / regression / benchmark
~~~

---

## 설치

### 1. 저장소 복제

~~~powershell
git clone https://github.com/kimyejun978-tech/ARGUS.git
cd ARGUS
~~~

### 2. 가상환경 생성

~~~powershell
py -m venv .venv
~~~

PowerShell에서:

~~~powershell
.\.venv\Scripts\Activate.ps1
~~~

PowerShell 실행 정책 때문에 activation이 막히는 경우에는 가상환경의 Python을 직접 사용할 수 있습니다.

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
~~~

### 3. 의존성 설치

~~~powershell
pip install -r requirements.txt
python -m playwright install chromium
~~~

---

## 실행

### GUI

~~~powershell
python gui.py
~~~

GUI에서 URL을 입력하고 **점검 시작**을 누르면 자동 탐색이 시작됩니다.

로컬 HTML 파일도 파일 선택 기능으로 검사할 수 있습니다.

### CLI

~~~powershell
python main.py
~~~

실행 후 검사할 URL 또는 HTML 파일 경로를 입력합니다.

---

## 출력 파일

### result.json

공식 탐지 결과입니다.

각 finding은 기본적으로 다음 정보를 포함합니다.

~~~json
{
  "url": "https://example.test/page",
  "location": "body > ...",
  "technique": "OFFSCREEN",
  "evidence_text": "..."
}
~~~

공식 technique 값은 다음 4종입니다.

~~~text
TRANSPARENT
OFFSCREEN
JAMO
HOMOGLYPH
~~~

결과 파일 검증:

~~~powershell
python result_validator.py result.json
~~~

### result_extra.json

자동 다운로드 시도 등 **공식 4종 탐지에 포함되지 않는 보조 행동 진단**을 저장합니다.

이 파일의 항목은 공식 result.json finding과 별도로 취급합니다.

---

## 주요 환경 변수

| 환경 변수 | 기본값 | 설명 |
| --- | ---: | --- |
| ARGUS_MAX_PAGES | 10000 | 최대 분석 완료 페이지 |
| ARGUS_MAX_SECONDS | 1620 | 비상 watchdog 시간(초) |
| ARGUS_DISCOVERY_WORKERS | 8 | HTTP discovery worker 수 |
| ARGUS_WORKERS | Auto-Tune | browser worker를 직접 지정 |
| ARGUS_AUTOTUNE | 활성 | Auto-Tune 활성/비활성 |
| ARGUS_RETUNE | 0 | 캐시를 무시하고 재측정 |

예:

~~~powershell
$env:ARGUS_MAX_PAGES="100"
$env:ARGUS_MAX_SECONDS="300"
python main.py
~~~

---

## 테스트

전체 unit test:

~~~powershell
python -m unittest discover -s tests -v
~~~

빠른 회귀 테스트:

~~~powershell
python tests\run_regression.py
~~~

전체 회귀 테스트:

~~~powershell
python tests\run_regression.py --full
~~~

테스트에는 mock site, realistic fixture, adversarial scenario, mutation fuzz, scale benchmark 등이 포함되어 있습니다.

---

## 안전 원칙

ARGUS는 웹사이트를 분석할 때 다음 원칙을 따릅니다.

- 자동 다운로드 파일을 저장하거나 실행하지 않음
- 비-HTML 다운로드 대상은 분석 페이지에서 제외
- 브라우저 분석은 별도 context에서 수행
- 공식 탐지 결과와 보조 행동 진단을 분리
- 탐지 후보를 곧바로 확정하지 않고 verifier를 거침

공개되었거나 점검 권한이 있는 웹사이트를 대상으로 사용하세요.

---

## 현재 상태

현재 ARGUS는 탐지 엔진, verifier, GUI, 결과 exporter, validator, Auto-Tune, regression benchmark를 함께 개발·검증하고 있습니다.

대형 사이트에서는 query parameter, 게시판 pagination, 정렬 URL 조합 등으로 탐색 URL 수가 크게 증가할 수 있어 크롤링 효율화 작업도 계속 진행 중입니다.

---

## Repository

https://github.com/kimyejun978-tech/ARGUS
