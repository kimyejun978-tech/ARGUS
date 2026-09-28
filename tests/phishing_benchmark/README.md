# Offline phishing benchmark corpus

This directory is reserved for **sanitized, offline** HTML snapshots used to
measure ARGUS phishing-risk generalization.

Do not put live phishing URLs, credential submissions, executable downloads, or
active network code here. Before adding an external snapshot, run it through
`snapshot_sanitizer.sanitize_snapshot` and verify that scripts, form actions,
redirects, event handlers, remote frames, and credential values are disabled.

The current automated benchmark is intentionally labeled
`sanitized-pattern benchmark`. It is not evidence of real-world phishing
detection performance until independently sourced, sanitized snapshots are
added with provenance and labels.
