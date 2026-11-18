import os

import pytest_asyncio
from blacksheep.contents import JSONContent
from blacksheep.testing import TestClient

from app.db import init_db
from app.main import app


def _cookie_jar(response) -> dict[str, str]:
    jar: dict[str, str] = {}
    cookies = getattr(response, "cookies", None)
    if isinstance(cookies, dict):
        for name, value in cookies.items():
            # BlackSheep returns Cookie objects; need .value
            raw = getattr(value, "value", None)
            jar[str(name)] = str(raw if raw is not None else value)
        if jar:
            return jar
    headers = getattr(response, "headers", None) or []
    for key, val in headers:
        if key.lower() == b"set-cookie":
            raw = val.decode("latin-1")
            part = raw.split(";", 1)[0]
            if "=" in part:
                n, v = part.split("=", 1)
                jar[n] = v
    return jar


@pytest_asyncio.fixture()
async def client(tmp_path):
    db = tmp_path / "test.db"
    os.environ["DATABASE_PATH"] = str(db)
    init_db(str(db))
    await app.start()
    c = TestClient(app)
    try:
        yield c
    finally:
        await app.stop()


@pytest_asyncio.fixture()
async def authed(client):
    r = await client.post(
        "/api/login",
        content=JSONContent({"username": "admin", "password": "123456"}),
    )
    assert r.status == 200
    jar = _cookie_jar(r)

    class Authed:
        def __init__(self, inner, cookies):
            self._c = inner
            self._jar = cookies

        async def get(self, path, query=None):
            return await self._c.get(path, query=query, cookies=self._jar)

        async def post(self, path, json=None):
            return await self._c.post(
                path,
                content=JSONContent(json or {}),
                cookies=self._jar,
            )

    return Authed(client, jar)
