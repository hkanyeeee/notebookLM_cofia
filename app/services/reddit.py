import time
from typing import Optional, Dict, Any

import httpx

from app.config import (
    PROXY_URL,
    REDDIT_USE_API,
    REDDIT_CLIENT_ID,
    REDDIT_CLIENT_SECRET,
    REDDIT_USERNAME,
    REDDIT_PASSWORD,
    REDDIT_USER_AGENT,
    REDDIT_SCOPES,
    REDDIT_OTP,
    REDDIT_TIMEOUT,
)


class RedditClient:
    """Minimal Reddit OAuth2 client using password grant for script apps.

    Provides token caching and simple content fetchers for posts and comments.
    """

    def __init__(self) -> None:
        self._access_token: Optional[str] = None
        self._token_expiry_ts: float = 0.0

    def _has_valid_token(self) -> bool:
        # Consider token valid if 30 seconds before expiry
        return bool(self._access_token) and (time.time() < self._token_expiry_ts - 30)

    async def _fetch_token(self) -> None:
        auth = (REDDIT_CLIENT_ID or "", REDDIT_CLIENT_SECRET or "")
        headers = {
            "User-Agent": REDDIT_USER_AGENT,
        }
        if REDDIT_OTP:
            headers["X-Reddit-OTP"] = REDDIT_OTP

        data = {
            "grant_type": "password",
            "username": REDDIT_USERNAME or "",
            "password": REDDIT_PASSWORD or "",
            "scope": ",".join([s for s in REDDIT_SCOPES.replace(",", " ").split() if s]),
        }

        client_kwargs: Dict[str, Any] = {
            "timeout": REDDIT_TIMEOUT,
            "headers": headers,
        }
        if PROXY_URL:
            client_kwargs["proxy"] = PROXY_URL

        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.post("https://www.reddit.com/api/v1/access_token", data=data, auth=auth)
            resp.raise_for_status()
            payload = resp.json()
            self._access_token = payload.get("access_token")
            expires_in = int(payload.get("expires_in") or 3600)
            self._token_expiry_ts = time.time() + max(60, expires_in)

    async def _ensure_token(self) -> None:
        if not self._has_valid_token():
            await self._fetch_token()

    async def _oauth_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        await self._ensure_token()
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "User-Agent": REDDIT_USER_AGENT,
        }
        client_kwargs: Dict[str, Any] = {
            "timeout": REDDIT_TIMEOUT,
            "headers": headers,
        }
        if PROXY_URL:
            client_kwargs["proxy"] = PROXY_URL

        async with httpx.AsyncClient(**client_kwargs) as client:
            url = f"https://oauth.reddit.com{path}"
            resp = await client.get(url, params=params)
            if resp.status_code == 401:
                # Try refreshing token once
                await self._fetch_token()
                headers["Authorization"] = f"Bearer {self._access_token}"
                async with httpx.AsyncClient(**client_kwargs) as client2:
                    resp = await client2.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def is_reddit_url(url: str) -> bool:
        u = (url or "").lower()
        return any(host in u for host in ["reddit.com/", "redd.it/"])

    async def fetch_text_from_url(self, url: str) -> Optional[str]:
        """Given any Reddit URL, fetch a reasonable text representation via API.

        Supported:
          - Post permalink: /r/<sub>/comments/<id>/...
          - Shortlink: https://redd.it/<id>
          - User posts/comments pages (best-effort)
        """
        if not REDDIT_USE_API:
            return None

        # Normalize to post ID if possible
        post_id = None
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            path = parsed.path.strip("/")
            parts = path.split("/")
            # Patterns: r/<sub>/comments/<id>/..., or comments/<id>/..., or <id> for redd.it
            if "redd.it" in parsed.netloc and parts and parts[0]:
                post_id = parts[0]
            else:
                if "comments" in parts:
                    idx = parts.index("comments")
                    if idx + 1 < len(parts):
                        post_id = parts[idx + 1]
        except Exception:
            post_id = None

        text_blocks = []

        try:
            if post_id:
                # Use .json to get post + comments in one call via API path
                data = await self._oauth_get(f"/comments/{post_id}.json", params={"raw_json": 1, "limit": 200})
                if isinstance(data, list) and len(data) >= 1:
                    # Listing 0: post, Listing 1: comments
                    post_listing = data[0].get("data", {}).get("children", [])
                    if post_listing:
                        post = post_listing[0].get("data", {})
                        title = post.get("title") or ""
                        selftext = post.get("selftext") or ""
                        url_overridden = post.get("url_overridden_by_dest") or ""
                        text_blocks.append(title)
                        if selftext:
                            text_blocks.append(selftext)
                        elif url_overridden:
                            text_blocks.append(f"Link: {url_overridden}")

                    if len(data) > 1:
                        comments_listing = data[1].get("data", {}).get("children", [])
                        count = 0
                        for child in comments_listing:
                            kind = child.get("kind")
                            if kind != "t1":
                                continue
                            c = child.get("data", {})
                            body = c.get("body") or ""
                            author = c.get("author") or ""
                            if body:
                                text_blocks.append(f"[Comment by u/{author}]\n{body}")
                                count += 1
                                if count >= 20:  # cap to avoid overly long
                                    break
            else:
                # Fallback: try identity to ensure token works, then return None to let fallback path try HTML
                await self._oauth_get("/api/v1/me")
                return None
        except Exception:
            return None

        final_text = "\n\n".join([t for t in text_blocks if t and isinstance(t, str)])
        return final_text or None


# Singleton
reddit_client = RedditClient()


