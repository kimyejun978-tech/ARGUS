from pathlib import Path

try:
    import webview
except ImportError as exc:
    raise SystemExit(
        "pywebview가 설치되어 있지 않습니다. "
        "'pip install -r requirements.txt'를 먼저 실행해 주세요."
    ) from exc

from desktop_api import ArgusDesktopApi


ROOT = Path(__file__).resolve().parent
WEBUI = ROOT / "webui"


class DesktopBridge(ArgusDesktopApi):
    def choose_file(self):
        if not webview.windows:
            return {"ok": False, "message": "창이 아직 준비되지 않았습니다."}

        try:
            result = webview.windows[0].create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=(
                    "HTML 파일 (*.html;*.htm)",
                    "모든 파일 (*.*)",
                ),
            )
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

        if not result:
            return {"ok": False, "cancelled": True}

        return {"ok": True, "path": result[0]}


def run_app():
    api = DesktopBridge(ROOT)
    index_url = (WEBUI / "index.html").resolve().as_uri()

    webview.create_window(
        "ARGUS · 공공 웹사이트 점검 시스템",
        index_url,
        js_api=api,
        width=1380,
        height=900,
        min_size=(1100, 720),
        background_color="#07111f",
    )
    webview.start(debug=False)


if __name__ == "__main__":
    run_app()
