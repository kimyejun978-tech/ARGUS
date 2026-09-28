# ARGUS

ARGUS는 공공 웹페이지에서 시각적으로 숨겨지거나 혼동을 유발하는 텍스트를 점검하는 Windows 데스크톱 프로그램입니다. 공식 탐지 대상은 `TRANSPARENT`, `OFFSCREEN`, `JAMO`, `HOMOGLYPH` 네 가지이며, 자동 다운로드 시도와 URL 사칭 위험 같은 보조 진단은 공식 결과와 분리합니다.

## 개발 환경 설치와 실행

Windows 11과 Python 3.11 이상을 권장합니다.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
python gui.py
```

기본 실행 화면은 `pywebview` 기반 GUI입니다. 기존 Tkinter 화면은 호환성 확인용 `legacy_gui.py`에 보존되어 있습니다.

## GUI 사용법

1. 점검할 `http://` 또는 `https://` 주소를 입력하거나 **파일 선택**으로 로컬 HTML 파일을 고릅니다.
2. **점검 시작**을 누릅니다. 크롤링 중 발견 URL 수가 계속 변하므로 화면은 전체 백분율 대신 실행 중 표시와 실제 집계값을 보여 줍니다.
3. 필요하면 **점검 중지**로 탐지 엔진과 브라우저 자식 프로세스를 함께 종료합니다.
4. 공식 탐지 표의 행을 선택하면 technique, evidence text, URL, location과 원본 상세 정보를 볼 수 있습니다.
5. **보조 위험 진단** 탭은 공식 판정과 분리된 브라우저 동작 진단입니다.
6. **결과 폴더 열기**로 생성된 JSON 파일 위치를 엽니다.

실시간 화면에는 발견한 고유 URL 수, 정밀검사 시도 수, 분석 완료 페이지 수, 현재 URL, 경과 시간, Auto-Tune worker 정보, 공식 탐지 건수와 보조 위험 진단 건수가 표시됩니다.

안전한 수동 점검 샘플은 `tests\manual_fixtures\realistic_public_portal.html`입니다. 외부 자원이나 실제 다운로드 없이 네 가지 공식 technique을 검증하도록 만든 합성 페이지입니다.

## 결과 파일

- `result.json`: 공모전 제출용 공식 결과입니다. 네 가지 공식 technique의 검증된 findings만 포함합니다.
- `result_extra.json`: 자동 다운로드 시도와 브랜드 오타·IDN·유사문자 URL 사칭 위험 같은 보조 진단입니다. URL 위험은 확정 피싱 판정이 아니라 사용자가 공식 도메인을 재확인해야 한다는 경고이며, `result.json` findings에 합쳐지지 않습니다.

ARGUS는 사이트가 다운로드를 시도해도 파일을 저장하거나 열거나 실행하지 않습니다. Playwright 브라우저 컨텍스트는 다운로드를 차단하고, 관련 메타데이터만 `result_extra.json`에 기록합니다.

## 보조 위험 진단

ARGUS는 공식 네 가지 탐지와 별도로 다음 보조 위험을 진단합니다.

- 자동 다운로드 시도
- URL 사칭 위험 (`DOMAIN_IMPERSONATION_RISK`)
- 페이지 단위 피싱 위험 신호 (`PHISHING_RISK`)

URL 사칭 위험은 hostname 문자열에서 알려진 서비스명의 한 글자 오타, IDN/punycode, 유사문자, 비공식 도메인에 사용된 브랜드 별칭을 분석합니다. DNS 조회나 외부 네트워크 평판 API를 사용하지 않으며, 같은 입력에는 같은 결과를 내는 오프라인·결정론적 진단입니다.

페이지 단위 피싱 위험 분석은 URL 사칭 여부와 함께 비밀번호/계정 입력 UI, 로그인·인증 문맥, 브랜드-도메인 불일치, cross-origin form action 및 인증 문맥의 외부 iframe 신호를 결합합니다. 폼을 제출하거나 입력값을 읽지 않으며 외부 평판 API도 사용하지 않습니다.\n\n보조 진단은 피싱 확정 판정이 아닙니다. `PHISHING_RISK`와 URL 사칭 위험은 `result_extra.json`에만 저장되며, 공모전 공식 결과인 `result.json`의 findings와 공식 탐지 건수에는 포함되지 않습니다.

공식 결과는 다음 명령으로 스키마와 의미 규칙을 다시 검증할 수 있습니다.

```powershell
python result_validator.py result.json
```

## 테스트

필수 데스크톱 회귀 테스트:

```powershell
python -m unittest tests.test_desktop_api tests.test_gui_log_parser tests.test_crawler_recovery tests.test_extra_exporter -v
```

빠른 전체 회귀 테스트:

```powershell
python tests\run_regression.py
```

## Windows portable 빌드

빌드는 PyInstaller `onedir` 형식입니다. 실행 파일 하나만 복사하지 말고 생성된 `dist\ARGUS` 폴더 전체를 배포해야 합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1 -Clean
```

빌드 스크립트는 다음 작업을 수행합니다.

- `.venv-build` 격리 환경 생성
- 앱 의존성과 PyInstaller 설치
- `PLAYWRIGHT_BROWSERS_PATH=0`으로 빌드 환경 안에 Chromium 설치
- `ARGUS.exe`, `argus-engine.exe`, 웹 UI, semantic seed, 수동 샘플을 `dist\ARGUS`에 수집

`ARGUS.exe`만 사용자가 실행합니다. `argus-engine.exe`는 GUI가 내부적으로 호출하는 동반 실행 파일입니다. 결과 JSON을 배포 폴더에 기록하므로 설치 위치는 일반 사용자에게 쓰기 가능한 폴더여야 합니다.

### WebView2

Windows 11에는 일반적으로 Evergreen WebView2 Runtime이 포함되지만, clean PC와 관리형 PC에서는 설치 여부를 반드시 확인합니다. 누락된 경우 Microsoft의 Evergreen Bootstrapper 또는 Standalone Installer로 설치한 뒤 ARGUS를 실행합니다. WebView2 Fixed Version Runtime은 용량이 크므로 현재 portable 폴더에는 포함하지 않습니다.

- WebView2 배포 안내: https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution
- Playwright 브라우저 관리: https://playwright.dev/python/docs/browsers
- pywebview 패키징 안내: https://pywebview.flowrl.com/guide/freezing.html

### clean Windows 11 확인 목록

1. Python이 설치되지 않은 Windows 11 VM을 준비합니다.
2. WebView2 Runtime 설치 여부를 확인하고, 없다면 공식 설치 관리자로 설치합니다.
3. `dist\ARGUS` 폴더 전체를 복사해 `ARGUS.exe`를 실행합니다.
4. URL 점검과 `samples\realistic_public_portal.html` 파일 점검을 각각 수행합니다.
5. 시작, 중지, 상세 결과, 보조 진단, 로그, 결과 폴더 열기와 창 종료 후 잔류 `argus-engine.exe`/Chromium 프로세스가 없는지 확인합니다.
6. `result.json`과 `result_extra.json`이 분리되어 생성되고 다운로드 파일이 저장되지 않았는지 확인합니다.
