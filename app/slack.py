"""Minimal Slack Web API client (stdlib, no dependencies)."""
import json
import urllib.error
import urllib.parse
import urllib.request


class SlackError(Exception):
    def __init__(self, error: str, retry_after: int | None = None):
        super().__init__(error)
        self.error = error
        self.retry_after = retry_after


class Slack:
    def __init__(self, token: str, opener=urllib.request.urlopen, timeout: int = 8):
        self.token = token
        self.opener = opener
        self.timeout = timeout

    def call(self, method: str, params: dict | None = None) -> dict:
        data = {}
        for k, v in (params or {}).items():
            if v is None:
                continue
            data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
        req = urllib.request.Request(
            f"https://slack.com/api/{method}",
            data=urllib.parse.urlencode(data).encode(),
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with self.opener(req, timeout=self.timeout) as res:
                body = json.loads(res.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise SlackError("ratelimited", int(exc.headers.get("Retry-After", "1"))) from exc
            raise SlackError(f"http_{exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise SlackError("network_error") from exc
        if not body.get("ok"):
            raise SlackError(str(body.get("error", "unknown_error")))
        return body
