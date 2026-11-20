"""기상청 공공데이터 클라이언트(app.info.kma): ASOS 일자료·단기예보 읽기, 오류 코드, 키 다루기.

네트워크를 쓰지 않는다(kma.TRANSPORT 를 가짜로 바꿔 끼운다). 응답 모양은 PM 실측(11-20)을 따른다.
"""

import logging
from datetime import date, datetime

import httpx
import pytest

from app.info import kma
from app.info.kma import DayFcst, DayObs, KmaConn, KmaFailed
from tests.kma_doubles import (
    KEY,
    KEY_ENCODED,
    KmaMock,
    asos_day,
    fcst,
    gateway_body,
    gateway_xml,
    no_data_body,
    ok_body,
)

BASE = "https://apis.data.go.kr/1360000"
NOT_REGISTERED = "이 서비스키는 해당 기상청 서비스에 등록되지 않았습니다(공공데이터포털에서 활용신청을 확인해 주세요)."


@pytest.fixture
def use(monkeypatch):
    def install(mock: KmaMock) -> KmaMock:
        monkeypatch.setattr(kma, "TRANSPORT", mock)
        return mock

    return install


def _query(request: httpx.Request) -> str:
    return request.url.query.decode()


async def test_asos_daily_reads_strings_and_blanks(use):
    mock = use(KmaMock(asos=(200, ok_body([asos_day("2025-12-01", "1.5", "-3.0", ""),
                                            asos_day("2025-12-02", "", "", "12.5")]))))
    days = await kma.asos_daily(KmaConn(BASE, KEY), "108", date(2025, 12, 1), date(2025, 12, 2))
    assert days == [DayObs(date(2025, 12, 1), 1.5, -3.0, 0.0), DayObs(date(2025, 12, 2), None, None, 12.5)]
    request = mock.requests[0]
    assert request.url.path == "/1360000/AsosDalyInfoService/getWthrDataList"
    params = dict(request.url.params)
    assert {k: params[k] for k in ("dataType", "dataCd", "dateCd", "startDt", "endDt", "stnIds")} == {
        "dataType": "JSON", "dataCd": "ASOS", "dateCd": "DAY", "startDt": "20251201", "endDt": "20251202",
        "stnIds": "108"}


@pytest.mark.parametrize("key", [KEY, KEY_ENCODED])
async def test_decoded_and_encoded_keys_are_sent_encoded_once(use, key):
    mock = use(KmaMock(asos=(200, ok_body([]))))
    await kma.asos_daily(KmaConn(BASE, key), "108", date(2025, 12, 1), date(2025, 12, 1))
    assert f"serviceKey={KEY_ENCODED}&" in _query(mock.requests[0])


async def test_no_data_is_an_empty_list(use):
    use(KmaMock(asos=(200, no_data_body())))
    assert await kma.asos_daily(KmaConn(BASE, KEY), "108", date(2025, 12, 1), date(2025, 12, 7)) == []


async def test_unregistered_key_gateway_json_403(use):
    use(KmaMock(asos=(403, gateway_body("30"))))
    with pytest.raises(KmaFailed) as e:
        await kma.asos_daily(KmaConn(BASE, KEY), "108", date(2025, 12, 1), date(2025, 12, 7))
    assert (e.value.code, e.value.message) == ("not_registered", NOT_REGISTERED)


async def test_unregistered_key_gateway_xml(use):
    use(KmaMock(asos=(200, gateway_xml("30"))))
    with pytest.raises(KmaFailed) as e:
        await kma.asos_daily(KmaConn(BASE, KEY), "108", date(2025, 12, 1), date(2025, 12, 7))
    assert e.value.code == "not_registered"


@pytest.mark.parametrize(("reason", "code"), [
    ("22", "rate_limited"), ("31", "key_expired"), ("32", "ip_not_allowed"), ("20", "bad_key"), ("99", "unknown")])
async def test_gateway_codes(use, reason, code):
    use(KmaMock(fcst=(403, gateway_body(reason, "x"))))
    with pytest.raises(KmaFailed) as e:
        await kma.short_forecast(KmaConn(BASE, KEY), 60, 127)
    assert e.value.code == code and e.value.message == kma.FAILED_MESSAGES[code]


@pytest.mark.parametrize(("answer", "code"), [
    ((500, {}), "server_error"), ((401, {}), "bad_key"), ((200, "<html>oops</html>"), "unknown"),
    (httpx.ReadTimeout("slow"), "timeout"), (httpx.ConnectError("no"), "bad_url"),
    ((200, "<response><header><resultCode>00</resultCode></header></response>"), "unknown"),
    ((200, []), "unknown"),
    ((200, {"response": {"header": {"resultCode": "11", "resultMsg": "NO_MANDATORY_REQUEST_PARAMETERS_ERROR"}}}),
     "bad_request"),
])
async def test_http_and_result_failures(use, answer, code):
    use(KmaMock(asos=answer))
    with pytest.raises(KmaFailed) as e:
        await kma.asos_daily(KmaConn(BASE, KEY), "108", date(2025, 12, 1), date(2025, 12, 7))
    assert e.value.code == code


@pytest.mark.parametrize(("now", "base"), [
    (datetime(2026, 11, 20, 0, 5), ("20261119", "2300")), (datetime(2026, 11, 20, 2, 9), ("20261119", "2300")),
    (datetime(2026, 11, 20, 2, 10), ("20261120", "0200")), (datetime(2026, 11, 20, 13, 59), ("20261120", "1100")),
    (datetime(2026, 11, 20, 21, 15), ("20261120", "2000")), (datetime(2026, 11, 20, 23, 30), ("20261120", "2300")),
])
def test_forecast_base_time_rule(now, base):
    assert kma.base_datetime(now.replace(tzinfo=kma.KST)) == base


async def test_short_forecast_groups_days_and_leaves_missing_blank(use):
    items = [
        fcst("20261120", "2100", "TMP", "4.0"), fcst("20261120", "2100", "POP", "10"),
        fcst("20261120", "2200", "POP", "30"),
        fcst("20261121", "0600", "TMN", "-5.0"), fcst("20261121", "1500", "TMX", "3.0"),
        fcst("20261121", "0900", "POP", "20"), fcst("20261121", "1500", "POP", "60"),
        fcst("20261122", "1500", "TMX", "6.0"), fcst("20261122", "0900", "TMP", "-1.0"),
    ]
    mock = use(KmaMock(fcst=(200, ok_body(items, total=len(items)))))
    now = datetime(2026, 11, 20, 21, 15, tzinfo=kma.KST)
    days = await kma.short_forecast(KmaConn(BASE, KEY), 60, 127, now=now)
    assert days == [DayFcst(date(2026, 11, 20), None, None, 30), DayFcst(date(2026, 11, 21), -5.0, 3.0, 60),
                    DayFcst(date(2026, 11, 22), None, 6.0, None)]  # TMN 이 없으면 TMP 로 채우지 않는다
    params = dict(mock.requests[0].url.params)
    assert mock.requests[0].url.path == "/1360000/VilageFcstInfoService_2.0/getVilageFcst"
    assert (params["base_date"], params["base_time"], params["nx"], params["ny"], params["dataType"]) == (
        "20261120", "2000", "60", "127", "JSON")
    assert int(params["numOfRows"]) >= 1100  # 실측 totalCount 1016


async def test_service_key_never_logged(use, caplog):
    caplog.set_level(logging.DEBUG)
    use(KmaMock(asos=(200, ok_body([asos_day("2025-12-01", "1.0", "-1.0")])), fcst=(403, gateway_body("30"))))
    await kma.asos_daily(KmaConn(BASE, KEY), "108", date(2025, 12, 1), date(2025, 12, 1))
    with pytest.raises(KmaFailed) as e:
        await kma.short_forecast(KmaConn(BASE, KEY), 60, 127)
    for secret in (KEY, KEY_ENCODED):
        assert secret not in caplog.text and secret not in str(e.value) and secret not in repr(e.value)
    assert "serviceKey=…" in caplog.text  # httpx 의 요청 줄(주소)은 남되 키는 지운다
