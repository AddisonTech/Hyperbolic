"""Thin client for the BOPTEST and BOPTEST-Service REST API.

API reference: https://github.com/ibpsa/project1-boptest#test-case-restful-api
and https://github.com/NREL/boptest-service#boptest-service-apis.

Every core endpoint wraps its result as {"status", "message", "payload"}.
The service endpoint testcases/{name}/select returns {"testid"} directly.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

import httpx

DEFAULT_URL = "https://api.boptest.net"


class BoptestError(RuntimeError):
    pass


class Simulator(Protocol):
    """What the runners need from a simulator. BoptestClient and MockBoptest both satisfy it."""

    testid: str | None

    def select(self, testcase: str) -> str: ...
    def set_scenario(self, time_period: str, electricity_price: str) -> dict[str, float]: ...
    def set_step(self, seconds: int) -> None: ...
    def advance(self, u: dict[str, float]) -> dict[str, float]: ...
    def forecast(self, points: list[str], horizon: int, interval: int) -> dict[str, list[float]]: ...
    def kpi(self) -> dict[str, float | None]: ...
    def stop(self) -> None: ...


class BoptestClient:
    def __init__(
        self,
        url: str = DEFAULT_URL,
        timeout: float = 300.0,
        retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
    ) -> None:
        self.url = url.rstrip("/")
        self.retries = retries
        self.testid: str | None = None
        self._sleep = sleep
        self._http = httpx.Client(base_url=self.url, timeout=timeout, transport=transport)

    # -- plumbing ---------------------------------------------------------

    def _request(self, method: str, path: str, json: dict | None = None) -> Any:
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                resp = self._http.request(method, path, json=json)
            except httpx.TransportError as exc:
                last = exc
            else:
                if resp.status_code < 500:
                    return self._unwrap(resp)
                last = BoptestError(f"{method} {path}: HTTP {resp.status_code}: {resp.text[:300]}")
            if attempt < self.retries:
                self._sleep(2 ** (attempt + 1))
        raise BoptestError(f"{method} {path} failed after {self.retries + 1} attempts: {last}")

    @staticmethod
    def _unwrap(resp: httpx.Response) -> Any:
        try:
            body = resp.json()
        except ValueError as exc:
            raise BoptestError(f"HTTP {resp.status_code}: response is not JSON: {resp.text[:300]}") from exc
        if resp.status_code != 200:
            msg = body.get("message") if isinstance(body, dict) else body
            raise BoptestError(f"HTTP {resp.status_code}: {msg}")
        if isinstance(body, dict) and "payload" in body:
            return body["payload"]
        return body

    def _tid(self) -> str:
        if not self.testid:
            raise BoptestError("no test selected; call select() first")
        return self.testid

    # -- service API --------------------------------------------------------

    def testcases(self) -> Any:
        return self._request("GET", "/testcases")

    def select(self, testcase: str) -> str:
        body = self._request("POST", f"/testcases/{testcase}/select")
        testid = body.get("testid") if isinstance(body, dict) else None
        if not testid:
            raise BoptestError(f"select returned no testid: {body}")
        self.testid = testid
        return testid

    def status(self) -> str:
        return str(self._request("GET", f"/status/{self._tid()}"))

    def wait_until_running(self, timeout_s: float = 600.0, poll_s: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_s
        while True:
            if "running" in self.status().lower():
                return
            if time.monotonic() > deadline:
                raise BoptestError(f"test {self.testid} not running after {timeout_s:.0f} s")
            self._sleep(poll_s)

    def stop(self) -> None:
        if self.testid:
            try:
                self._request("PUT", f"/stop/{self.testid}")
            finally:
                self.testid = None

    # -- core test API ----------------------------------------------------------

    def version(self) -> Any:
        return self._request("GET", "/version")

    def name(self) -> Any:
        return self._request("GET", f"/name/{self._tid()}")

    def inputs(self) -> dict:
        return self._request("GET", f"/inputs/{self._tid()}")

    def measurements(self) -> dict:
        return self._request("GET", f"/measurements/{self._tid()}")

    def forecast_points(self) -> dict:
        return self._request("GET", f"/forecast_points/{self._tid()}")

    def get_step(self) -> float:
        return self._request("GET", f"/step/{self._tid()}")

    def set_step(self, seconds: int) -> None:
        self._request("PUT", f"/step/{self._tid()}", json={"step": seconds})

    def initialize(self, start_time: float, warmup_period: float) -> dict:
        return self._request(
            "PUT", f"/initialize/{self._tid()}", json={"start_time": start_time, "warmup_period": warmup_period}
        )

    def get_scenario(self) -> dict:
        return self._request("GET", f"/scenario/{self._tid()}")

    def set_scenario(self, time_period: str, electricity_price: str) -> dict[str, float]:
        """Set the scenario. Setting time_period also initializes the test and
        returns the initial measurements."""
        body = self._request(
            "PUT",
            f"/scenario/{self._tid()}",
            json={"time_period": time_period, "electricity_price": electricity_price},
        )
        y = body.get("time_period") if isinstance(body, dict) else None
        if not isinstance(y, dict) or "time" not in y:
            raise BoptestError(f"scenario did not initialize a time period: {body}")
        return y

    def advance(self, u: dict[str, float]) -> dict[str, float]:
        """Advance one step. Returns {} once the scenario period is complete."""
        y = self._request("POST", f"/advance/{self._tid()}", json=u)
        return y or {}

    def forecast(self, points: list[str], horizon: int, interval: int) -> dict[str, list[float]]:
        return self._request(
            "PUT",
            f"/forecast/{self._tid()}",
            json={"point_names": points, "horizon": horizon, "interval": interval},
        )

    def kpi(self) -> dict[str, float | None]:
        return self._request("GET", f"/kpi/{self._tid()}")

    def results(self, points: list[str], start_time: float, final_time: float) -> dict:
        return self._request(
            "PUT",
            f"/results/{self._tid()}",
            json={"point_names": points, "start_time": start_time, "final_time": final_time},
        )
