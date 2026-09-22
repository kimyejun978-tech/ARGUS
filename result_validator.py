import argparse
import json
import sys
from pathlib import Path


ALLOWED_TECHNIQUES = {
    "TRANSPARENT",
    "OFFSCREEN",
    "JAMO",
    "HOMOGLYPH",
}

META_STRING_FIELDS = (
    "topic",
    "entry_url",
    "started_at",
    "finished_at",
    "tool_version",
)


class ResultValidationError(ValueError):
    """result.json이 제출 형식 또는 무결성 규칙을 위반했다."""


def _require_non_empty_string(value, path):
    if not isinstance(value, str) or not value.strip():
        raise ResultValidationError(f"{path} must be a non-empty string")


def validate_result_data(result):
    """파싱된 ARGUS 결과의 형식과 제출 무결성만 검사한다."""

    if not isinstance(result, dict):
        raise ResultValidationError("top-level JSON value must be an object")

    if "meta" not in result:
        raise ResultValidationError("missing required field: meta")
    if not isinstance(result["meta"], dict):
        raise ResultValidationError("meta must be an object")

    meta = result["meta"]
    for field in META_STRING_FIELDS:
        if field in meta and not isinstance(meta[field], str):
            raise ResultValidationError(f"meta.{field} must be a string")

    if "elapsed_sec" in meta:
        elapsed_sec = meta["elapsed_sec"]
        if (
            isinstance(elapsed_sec, bool)
            or not isinstance(elapsed_sec, (int, float))
        ):
            raise ResultValidationError("meta.elapsed_sec must be a number")
        if elapsed_sec < 0:
            raise ResultValidationError(
                "meta.elapsed_sec must be greater than or equal to 0"
            )

    if "findings" not in result:
        raise ResultValidationError("missing required field: findings")
    if not isinstance(result["findings"], list):
        raise ResultValidationError("findings must be a list")

    seen = set()
    for index, finding in enumerate(result["findings"]):
        path = f"findings[{index}]"
        if not isinstance(finding, dict):
            raise ResultValidationError(f"{path} must be an object")

        for field in ("url", "location", "technique"):
            if field not in finding:
                raise ResultValidationError(
                    f"{path} missing required field: {field}"
                )

        _require_non_empty_string(finding["url"], f"{path}.url")
        _require_non_empty_string(
            finding["location"],
            f"{path}.location",
        )

        technique = finding["technique"]
        if technique not in ALLOWED_TECHNIQUES:
            allowed = ", ".join(sorted(ALLOWED_TECHNIQUES))
            raise ResultValidationError(
                f"{path}.technique must be one of: {allowed}"
            )

        key = (
            finding["url"],
            finding["location"],
            technique,
        )
        if key in seen:
            raise ResultValidationError(
                f"{path} duplicates (url, location, technique): {key!r}"
            )
        seen.add(key)

    return result


def validate_result_file(path):
    """UTF-8/BOM/JSON을 검사한 뒤 파싱된 결과를 반환한다."""

    result_path = Path(path)
    try:
        payload = result_path.read_bytes()
    except OSError as exc:
        raise ResultValidationError(
            f"unable to read {result_path}: {exc}"
        ) from exc

    if payload.startswith(b"\xef\xbb\xbf"):
        raise ResultValidationError("UTF-8 BOM is not allowed")

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResultValidationError(
            f"file is not valid UTF-8: {exc}"
        ) from exc

    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ResultValidationError(
            f"malformed JSON at line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg}"
        ) from exc

    return validate_result_data(result)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate ARGUS result.json submission integrity",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="result.json",
        help="result file to validate (default: result.json)",
    )
    args = parser.parse_args(argv)

    try:
        result = validate_result_file(args.path)
    except ResultValidationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        f"PASS: {args.path} is a valid ARGUS result "
        f"({len(result['findings'])} findings)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
