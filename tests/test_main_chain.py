import pytest


@pytest.mark.asyncio
async def test_stamp_trace_gap_chain(authed):
    all_b = (await (await authed.get("/api/batches")).json())["items"]
    batches = [b for b in all_b if b["status"] == "待盖印"]
    assert batches
    bid = batches[0]["id"]

    stamp = await authed.post(
        f"/api/batches/{bid}/stamp",
        json={"watermark_value": "WM-TEST-001"},
    )
    assert stamp.status == 200
    body = await stamp.json()
    assert body["batch"]["status"] == "已盖印"

    again = await authed.post(
        f"/api/batches/{bid}/stamp",
        json={"watermark_value": "WM-TEST-002"},
    )
    assert again.status == 409

    trace = await authed.post("/api/trace", json={"watermark_value": "WM-ORD-131"})
    assert trace.status == 200
    tbody = await trace.json()
    assert tbody["sources"]
    assert any(d["run_code"] == "gmv-20261114-01" for d in tbody["downstream"])

    gap_resp = await authed.post(
        "/api/gap-reports",
        json={"as_of_date": "2026-11-16"},
    )
    gap = await gap_resp.json()
    assert "缺口" in gap["report"]["summary"]
    assert gap["report"]["gap_count"] >= 0


@pytest.mark.asyncio
async def test_empty_watermark_rejected(authed):
    all_b = (await (await authed.get("/api/batches")).json())["items"]
    bid = next(b["id"] for b in all_b if b["status"] == "待盖印")
    r = await authed.post(f"/api/batches/{bid}/stamp", json={"watermark_value": "  "})
    assert r.status == 400
