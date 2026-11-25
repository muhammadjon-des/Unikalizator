"""
Instagram Content Publishing API — Reels'ni Trial Reel sifatida joylash.
Token turi avtomatik aniqlanadi:
  IGAA... -> graph.instagram.com (Instagram Login)
  EAA...  -> graph.facebook.com  (Facebook Login / system user token)
Video to'g'ridan-to'g'ri yuklanadi (resumable upload), hosting kerak emas.
"""
import asyncio
import json
from pathlib import Path

import httpx

import config


class InstagramError(Exception):
    pass


def _check(r: httpx.Response) -> dict:
    try:
        data = r.json()
    except Exception:
        raise InstagramError(f"HTTP {r.status_code}: {r.text[:300]}")
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", data)
        raise InstagramError(err.get("error_user_msg") or err.get("message") or str(err))
    return data


class InstagramClient:
    def __init__(self, user_id: str, token: str):
        self.user_id = user_id
        self.token = token
        host = "graph.instagram.com" if token.startswith("IG") else "graph.facebook.com"
        self.graph = f"https://{host}/{config.IG_API_VERSION}"
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(900, connect=30))

    async def close(self):
        await self.http.aclose()

    async def account(self) -> dict:
        r = await self.http.get(
            f"{self.graph}/{self.user_id}",
            params={"fields": "username", "access_token": self.token},
        )
        return _check(r)

    async def publishing_limit(self) -> dict:
        r = await self.http.get(
            f"{self.graph}/{self.user_id}/content_publishing_limit",
            params={"fields": "quota_usage,config", "access_token": self.token},
        )
        return _check(r)

    async def _create_container(self, caption: str, trial_strategy: str | None) -> dict:
        data = {
            "media_type": "REELS",
            "upload_type": "resumable",
            "caption": caption,
            "access_token": self.token,
        }
        if trial_strategy:
            data["trial_params"] = json.dumps({"graduation_strategy": trial_strategy})
        r = await self.http.post(f"{self.graph}/{self.user_id}/media", data=data)
        return _check(r)  # {"id": ..., "uri": ...}

    async def _upload(self, container_id: str, uri: str | None, path: Path) -> None:
        if not uri:
            uri = f"https://rupload.facebook.com/ig-api-upload/{config.IG_API_VERSION}/{container_id}"
        size = path.stat().st_size

        def chunks():
            with open(path, "rb") as f:
                while b := f.read(8 * 1024 * 1024):
                    yield b

        r = await self.http.post(
            uri,
            headers={
                "Authorization": f"OAuth {self.token}",
                "offset": "0",
                "file_size": str(size),
                "Content-Length": str(size),
            },
            content=chunks(),
        )
        data = _check(r)
        if data.get("success") is False:
            raise InstagramError(f"Yuklash muvaffaqiyatsiz: {data}")

    async def _wait_ready(self, container_id: str, timeout: int = 1200) -> None:
        waited = 0
        while waited < timeout:
            r = await self.http.get(
                f"{self.graph}/{container_id}",
                params={"fields": "status_code,status", "access_token": self.token},
            )
            data = _check(r)
            code = data.get("status_code")
            if code == "FINISHED":
                return
            if code in ("ERROR", "EXPIRED"):
                raise InstagramError(f"Instagram videoni qayta ishlay olmadi: {data.get('status')}")
            await asyncio.sleep(10)
            waited += 10
        raise InstagramError("Instagram qayta ishlash vaqti tugadi")

    async def _publish(self, container_id: str) -> str:
        r = await self.http.post(
            f"{self.graph}/{self.user_id}/media_publish",
            data={"creation_id": container_id, "access_token": self.token},
        )
        return _check(r)["id"]

    async def permalink(self, media_id: str) -> str | None:
        r = await self.http.get(
            f"{self.graph}/{media_id}",
            params={"fields": "permalink", "access_token": self.token},
        )
        try:
            return _check(r).get("permalink")
        except InstagramError:
            return None

    async def post_trial_reel(self, path: Path, caption: str, trial_strategy: str) -> str:
        c = await self._create_container(caption, trial_strategy)
        await self._upload(c["id"], c.get("uri"), path)
        await self._wait_ready(c["id"])
        return await self._publish(c["id"])
