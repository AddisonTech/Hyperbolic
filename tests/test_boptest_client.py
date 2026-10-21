"""BOPTEST client against a mocked HTTP transport, using the documented response shapes."""

import json

import httpx
import pytest

from hyperbolic.boptest import BoptestClient, BoptestError


def wrap(payload, status=200, message="ok"):
    return httpx.Response(status, json={"status": status, "message": message, "payload": payload})


class FakeService:
    def __init__(self):
        self.seen = []
        self.advances = 0
        self.fail_next = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.seen.append((request.method, path, body))
        if self.fail_next:
            self.fail_next -= 1
            return httpx.Response(503, text="busy")
        if path == "/testcases/multizone_office_simple_air/select":
            return httpx.Response(200, json={"testid": "abc123"})
        if path == "/status/abc123":
            return wrap("Running")
        if path == "/step/abc123":
            return wrap({"step": body["step"]})
        if path == "/scenario/abc123":
            return wrap({"electricity_price": body["electricity_price"],
                         "time_period": {"time": 950400.0, "hvac_reaZonCor_TZon_y": 294.0}})
        if path == "/advance/abc123":
            self.advances += 1
            if self.advances > 2:
                return wrap({}, message="End of test case scenario time period reached.")
            return wrap({"time": 950400.0 + 3600 * self.advances})
        if path == "/forecast/abc123":
            return wrap({"time": [0, 3600], **{p: [1.0, 2.0] for p in body["point_names"]}})
        if path == "/kpi/abc123":
            return wrap({"ener_tot": 1.5, "tdis_tot": 3.0})
        if path == "/stop/abc123":
            return wrap(None)
        if path == "/inputs/abc123":
            return httpx.Response(400, json={"status": 400, "message": "bad request", "payload": None})
        return httpx.Response(404, json={"status": 404, "message": "not found", "payload": None})


@pytest.fixture
def svc():
    return FakeService()


@pytest.fixture
def client(svc):
    return BoptestClient(url="https://example.test", transport=httpx.MockTransport(svc), sleep=lambda s: None)


def test_full_flow(client, svc):
    assert client.select("multizone_office_simple_air") == "abc123"
    client.wait_until_running()
    client.set_step(3600)
    y0 = client.set_scenario("typical_heat_day", "dynamic")
    assert y0["time"] == 950400.0
    fc = client.forecast(["TDryBul", "PriceElectricPowerDynamic"], 43200, 3600)
    assert fc["TDryBul"] == [1.0, 2.0]
    assert client.advance({"hvac_oveAhu_TSupSet_u": 288.15, "hvac_oveAhu_TSupSet_activate": 1})["time"] > y0["time"]
    client.advance({})
    assert client.advance({}) == {}  # end of scenario
    assert client.kpi()["ener_tot"] == 1.5
    client.stop()
    assert client.testid is None
    methods = {(m, p) for m, p, _ in svc.seen}
    assert ("PUT", "/scenario/abc123") in methods and ("POST", "/advance/abc123") in methods
    assert ("PUT", "/forecast/abc123") in methods and ("PUT", "/stop/abc123") in methods
    scen = next(b for m, p, b in svc.seen if p == "/scenario/abc123")
    assert scen == {"time_period": "typical_heat_day", "electricity_price": "dynamic"}
    fcb = next(b for m, p, b in svc.seen if p == "/forecast/abc123")
    assert fcb == {"point_names": ["TDryBul", "PriceElectricPowerDynamic"], "horizon": 43200, "interval": 3600}


def test_server_errors_are_retried(client, svc):
    svc.fail_next = 2
    assert client.select("multizone_office_simple_air") == "abc123"


def test_persistent_server_errors_raise(client, svc):
    svc.fail_next = 99
    with pytest.raises(BoptestError):
        client.select("multizone_office_simple_air")


def test_client_errors_raise_with_message(client):
    client.select("multizone_office_simple_air")
    with pytest.raises(BoptestError, match="bad request"):
        client.inputs()


def test_calls_need_a_test(client):
    with pytest.raises(BoptestError):
        client.kpi()
