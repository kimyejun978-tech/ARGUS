import json
from pathlib import Path

from url_risk import analyze_url_risk


def build_auxiliary_findings(download_events, url_findings=None, phishing_findings=None):
    """Build non-official auxiliary diagnostics.

    These records never change the official four-technique result.json findings.
    """

    findings = []
    seen = set()

    events = (
        list(download_events or [])
        + list(url_findings or [])
        + list(phishing_findings or [])
    )

    for event in events:
        key = (
            event.get("type", ""),
            event.get("page_url", ""),
            event.get("download_url", ""),
            event.get("suggested_filename", ""),
            event.get("hostname", ""),
            event.get("signal", ""),
        )
        if key in seen:
            continue
        seen.add(key)

        finding = {
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
        for field in (
            "hostname",
            "display_hostname",
            "brand",
            "signal",
            "matched_text",
            "official_domains",
            "confidence",
            "reason",
            "score",
            "signals",
            "external_form_actions",
            "external_iframes",
        ):
            if field in event:
                finding[field] = event[field]

        findings.append(finding)

    return findings


def export_result_extra_json(
    *,
    entry_url,
    download_events,
    phishing_findings=None,
    output_path="result_extra.json",
):
    """Export auxiliary behavior diagnostics separately from result.json."""

    findings = build_auxiliary_findings(
        download_events,
        url_findings=analyze_url_risk(entry_url),
        phishing_findings=phishing_findings,
    )
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
