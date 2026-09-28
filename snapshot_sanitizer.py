from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit


def _is_remote(value):
    try:
        return urlsplit(value or "").scheme in {"http", "https", "javascript"}
    except Exception:
        return False


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts = []
        self.skip_script_depth = 0

    def handle_starttag(self, tag, attrs):
        lower = tag.lower()
        if lower == "script":
            self.skip_script_depth += 1
            return
        if self.skip_script_depth:
            return

        attrs = list(attrs)
        attr_map = {str(k).lower(): (v or "") for k, v in attrs}
        if lower == "meta" and attr_map.get("http-equiv", "").casefold() == "refresh":
            return

        clean = []
        for key, value in attrs:
            key_lower = str(key).lower()
            value = value or ""

            if key_lower.startswith("on"):
                continue
            if lower == "input" and key_lower == "value":
                continue
            if lower == "form" and key_lower == "action":
                if value:
                    clean.append(("data-argus-original-action", value))
                clean.append(("action", "#"))
                continue
            if lower == "iframe" and key_lower == "src":
                if value:
                    clean.append(("data-argus-original-src", value))
                clean.append(("src", "about:blank"))
                continue
            if lower == "link" and key_lower == "href" and _is_remote(value):
                clean.append(("data-argus-original-href", value))
                continue
            if key_lower in {"href", "src", "srcset"} and _is_remote(value):
                clean.append((f"data-argus-original-{key_lower}", value))
                if key_lower == "href":
                    clean.append(("href", "#"))
                continue

            clean.append((key, value))

        rendered = "".join(
            f' {escape(str(k), quote=True)}="{escape(str(v), quote=True)}"'
            for k, v in clean
        )
        self.parts.append(f"<{tag}{rendered}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        lower = tag.lower()
        if lower == "script":
            if self.skip_script_depth:
                self.skip_script_depth -= 1
            return
        if self.skip_script_depth:
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip_script_depth:
            self.parts.append(data)

    def handle_entityref(self, name):
        if not self.skip_script_depth:
            self.parts.append(f"&{name};")

    def handle_charref(self, name):
        if not self.skip_script_depth:
            self.parts.append(f"&#{name};")

    def handle_comment(self, data):
        if not self.skip_script_depth:
            self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl):
        if not self.skip_script_depth:
            self.parts.append(f"<!{decl}>")


def sanitize_snapshot(html):
    """Disable active/network behaviors while preserving static DOM evidence."""

    parser = _Sanitizer()
    parser.feed(str(html or ""))
    parser.close()
    return "".join(parser.parts)
