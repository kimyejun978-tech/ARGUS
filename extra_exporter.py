import json
from pathlib import Path


def build_auxiliary_findings(download_events):
    """Build non-official auxiliary diagnostics.

    These records never change the official four-technique result.json findings.
    """

    findings = []
    seen = set()

    for event in download_events or []:
        key = (
            event.get("type", ""),
            event.get("page_url", ""),
            event.get("download_url", ""),
            event.get("suggested_filename", ""),
        )
        if key in seen:
            continue
        seen.add(key)

        findings.append(
            {
                "id": f"aux_{len(findings) + 1:03d}",
                "type": event.get("type", "DOWNLOAD_ATTEMPT"),
                "risk": event.get("risk", "INFO"),
                "page_url": event.get("page_url", ""),
                "requested_url": event.get("requested_url", ""),
                "download_url": event.get("download_url", ""),
                "suggested_filename": event.get("suggested_filename", ""),
                "page_triggered": bool(event.get("page_triggered")),
                "blocked": bool(event.get("blocked", True)),
            }
        )

    return findings


def export_result_extra_json(
    *,
    entry_url,
    download_events,
    output_path="result_extra.json",
):
    """Export auxiliary behavior diagnostics separately from result.json."""

    findings = build_auxiliary_findings(download_events)
    result = {
        "meta": {
            "entry_url": entry_url,
            "purpose": "ARGUS auxiliary behavior diagnostics",
            "official_findings": False,
        },
        "auxiliary_findings": findings,
    }

    output = Path(output_path)
    with output.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
        file.write("\n")

    return output.resolve(), result
