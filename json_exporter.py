import json
from pathlib import Path


TOOL_VERSION = "0.1.0"
TOPIC = "TOPIC"


def build_findings(candidate_groups):
    """탐지 후보들을 공모전 findings 스키마로 변환하고 중복을 제거한다."""

    findings = []
    seen = set()

    for group in candidate_groups:
        for candidate in group:
            key = (
                candidate["url"],
                candidate["location"],
                candidate["technique"],
            )

            # 공모전의 1건 단위인 (url + location + technique) 기준 중복 제거
            if key in seen:
                continue

            seen.add(key)

            findings.append(
                {
                    "id": f"f_{len(findings) + 1:03d}",
                    "url": candidate["url"],
                    "is_violation": candidate.get("is_violation", True),
                    "location": candidate["location"],
                    "evidence_text": candidate["evidence_text"],
                    "technique": candidate["technique"],
                }
            )

    return findings


def export_result_json(
    *,
    entry_url,
    started_at,
    finished_at,
    elapsed_sec,
    candidate_groups,
    output_path="result.json",
):
    """공모전 표준 형식의 result.json을 UTF-8(BOM 없음)으로 생성한다."""

    result = {
        "meta": {
            "topic": TOPIC,
            "entry_url": entry_url,
            "started_at": started_at,
            "finished_at": finished_at,
            "elapsed_sec": elapsed_sec,
            "tool_version": TOOL_VERSION,
        },
        "findings": build_findings(candidate_groups),
    }

    output = Path(output_path)

    with output.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2,
        )
        file.write("\n")

    return output.resolve(), result
