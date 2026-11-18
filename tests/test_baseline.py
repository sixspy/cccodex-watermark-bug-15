import pytest
from blacksheep.contents import JSONContent


@pytest.mark.asyncio
async def test_login_page(client):
    r = await client.get("/login")
    assert r.status == 200
    text = await r.text()
    assert "密码" in text or "登录" in text


@pytest.mark.asyncio
async def test_login_ok(client):
    r = await client.post(
        "/api/login",
        content=JSONContent({"username": "admin", "password": "123456"}),
    )
    assert r.status == 200
    body = await r.json()
    assert body["ok"] is True
