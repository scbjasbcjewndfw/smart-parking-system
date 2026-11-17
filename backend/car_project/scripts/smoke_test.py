# coding: utf-8
"""端到端冒烟测试：不依赖 pytest，直接打到运行中的服务。

用法（在 ``backend/car_project`` 目录下，先启动 ``python app.py``）::

    .venv/Scripts/python.exe -m scripts.smoke_test
    .venv/Scripts/python.exe -m scripts.smoke_test --base http://127.0.0.1:5000

覆盖主链路：注册 → 登录 → 入场 → 重复入场拦截 → 未出场禁止支付 → 计费
→ 重复计费复用订单 → 查询 → 支付 → 重复支付拦截 → 资料 → 注销。
任何一条断言失败即以非 0 退出码结束，可直接接入 CI。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

#: 断言通过计数
_passed = 0
#: 断言失败明细
_failures: list[str] = []

#: 显式禁用代理。开发机上常设置 HTTP_PROXY/HTTPS_PROXY，
#: urllib 会连 127.0.0.1 也走代理，导致 "upstream connect failed"。
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _call(
    method: str,
    url: str,
    body: dict | None = None,
    token: str | None = None,
) -> tuple[int, dict]:
    """发起一次 JSON 请求。

    Args:
        method: HTTP 方法。
        url: 完整地址。
        body: JSON 请求体。
        token: 可选 JWT。

    Returns:
        ``(HTTP 状态码, 响应 JSON)``，响应非 JSON 时返回 ``{"raw": 文本}``。
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with _opener.open(request, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, {"raw": raw}


def _check(name: str, condition: bool, detail: str = "") -> None:
    """记录一条断言结果。

    Args:
        name: 断言名称。
        condition: 是否通过。
        detail: 失败时补充的信息。
    """
    global _passed
    if condition:
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failures.append(f"{name} {detail}".strip())
        print(f"  [FAIL] {name} {detail}")


def run(base: str) -> int:
    """执行全部用例。

    Args:
        base: 服务根地址，如 ``http://127.0.0.1:5000``。

    Returns:
        进程退出码。
    """
    suffix = str(int(time.time()))[-6:]
    username = f"smoke_{suffix}"
    password = "test123456"
    # 车牌按时间戳生成，避免上一次失败用例残留的未出场订单造成"重复入场"
    plate = f"皖A{suffix[-5:]}"
    free_plate = f"皖B{suffix[-5:]}"

    now = dt.datetime.now().replace(second=0, microsecond=0)
    in_time = (now - dt.timedelta(hours=2, minutes=30)).strftime("%Y-%m-%d %H:%M")
    out_time = now.strftime("%Y-%m-%d %H:%M")

    print(f"\n== 目标服务：{base}，测试账号：{username} ==\n")

    print("[1] 注册与登录")
    status, body = _call("POST", f"{base}/api/user/register", {"username": username, "password": password, "plate": plate})
    _check("注册成功", status == 200 and body.get("code") == 200, str(body))
    _check("返回体不含密码", "password" not in json.dumps(body).lower() or "hash" in json.dumps(body), str(body))

    status, body = _call("POST", f"{base}/api/user/register", {"username": username, "password": password})
    _check("重复注册被拒", body.get("code") == 400, str(body))

    status, body = _call("POST", f"{base}/api/user/register", {"username": f"{username}_x", "password": "123"})
    _check("弱密码被拒", body.get("code") == 400, str(body))

    status, body = _call("POST", f"{base}/api/user/login", {"username": username, "password": "wrong-pass"})
    _check("错误密码返回 401", body.get("code") == 401, str(body))

    status, body = _call("POST", f"{base}/api/user/login", {"username": username, "password": password})
    token = (body.get("data") or {}).get("access_token")
    _check("登录拿到 token", bool(token), str(body))
    if not token:
        print("登录失败，后续用例无法执行")
        return 1
    user_id = (body.get("data") or {}).get("user_id")

    print("\n[2] 未登录访问受保护接口")
    status, body = _call("GET", f"{base}/api/user/profile")
    _check("profile 未带 token 返回 401", status == 401, f"status={status} {body}")

    print("\n[3] 入场登记")
    status, body = _call("POST", f"{base}/api/plate/entry", {"plate": "BADPLATE123"}, token)
    _check("非法车牌被拒", body.get("code") == 400, str(body))

    status, body = _call("POST", f"{base}/api/plate/entry", {"plate": plate}, token)
    entry_order_id = (body.get("data") or {}).get("order_id")
    entry_in_iso = (body.get("data") or {}).get("in_time")
    _check("入场成功", body.get("code") == 200 and entry_order_id, str(body))
    _check("入场返回入场时间", bool(entry_in_iso), str(body))

    status, body = _call("POST", f"{base}/api/plate/entry", {"plate": plate}, token)
    _check("重复入场被拦截", body.get("code") == 400 and "登记" in str(body.get("msg")), str(body))

    print("\n[4] 未出场订单不允许支付")
    status, body = _call("PUT", f"{base}/api/parking/pay/{entry_order_id}", None, token)
    _check("未出场支付被拒", body.get("code") == 400, str(body))

    print("\n[5] 出场计费")
    # 5a 无入场记录的车辆：直接计费应新建订单
    status, body = _call(
        "POST",
        f"{base}/api/parking/fee",
        {"plate": free_plate, "in_time": in_time, "out_time": out_time},
        token,
    )
    fee_free = body.get("data") or {}
    free_order_id = fee_free.get("order_id")
    _check("无入场记录时可直接计费", body.get("code") == 200, str(body))
    _check(
        "2.5 小时应收 12.5 元",
        abs(float(fee_free.get("total_fee", -1)) - 12.5) < 0.01,
        str(fee_free),
    )
    _check("新建订单 updated_existing 为 False", fee_free.get("updated_existing") is False, str(fee_free))

    # 5b 有入场记录的车辆：客户端谎报更早的入场时间，应以系统记录为准并复用同一订单
    entry_in = dt.datetime.fromisoformat(entry_in_iso)
    entry_minute = entry_in.replace(second=0, microsecond=0)
    entry_in_text = entry_minute.strftime("%Y-%m-%d %H:%M")
    entry_out_text = (entry_minute + dt.timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")
    status, body = _call(
        "POST",
        f"{base}/api/parking/fee",
        {
            "plate": plate,
            "in_time": (entry_minute - dt.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"),
            "out_time": entry_out_text,
        },
        token,
    )
    fee_data = body.get("data") or {}
    _check("计费成功", body.get("code") == 200, str(body))
    _check(
        "复用入场订单而非新建",
        fee_data.get("order_id") == entry_order_id,
        f"entry={entry_order_id} fee={fee_data.get('order_id')}",
    )
    _check("篡改入场时间被纠正为系统记录", fee_data.get("in_time_source") == "order", str(fee_data))
    _check(
        "1 分钟按 5÷60 计费",
        abs(float(fee_data.get("total_fee", -1)) - 0.08) < 0.005,
        str(fee_data),
    )
    _check("标记为更新已有订单", fee_data.get("updated_existing") is True, str(fee_data))

    # 5c 同一时间再提交一次，仍应作用于同一订单（不会重复生成）
    status, body = _call(
        "POST",
        f"{base}/api/parking/fee",
        {"plate": plate, "in_time": entry_in_text, "out_time": entry_out_text},
        token,
    )
    again = body.get("data") or {}
    _check("重复计费仍返回同一订单", again.get("order_id") == entry_order_id, str(again))

    status, body = _call(
        "POST",
        f"{base}/api/parking/fee",
        {"plate": plate, "in_time": entry_out_text, "out_time": entry_in_text},
        token,
    )
    _check("出场早于入场被拒", body.get("code") == 400, str(body))

    status, body = _call(
        "POST",
        f"{base}/api/parking/fee",
        {"plate": plate, "in_time": entry_in_text, "out_time": "2099-01-01 00:00"},
        token,
    )
    _check("未来时间被拒", body.get("code") == 400, str(body))

    print("\n[6] 查询")
    quoted_plate = urllib.parse.quote(plate)
    status, body = _call("GET", f"{base}/api/parking/query?plate={quoted_plate}", None, token)
    data = body.get("data") or {}
    orders = data.get("orders") or []
    _check("查询到订单", body.get("code") == 200 and len(orders) == 1, str(data))
    _check("车主信息与绑定车牌一致", (data.get("user") or {}).get("plate") == plate, str(data.get("user")))

    status, body = _call(
        "GET", f"{base}/api/parking/query?plate={urllib.parse.quote('京A00000')}", None, token
    )
    _check("查询他车车牌不返回车主信息", (body.get("data") or {}).get("user") is None, str(body))

    print("\n[7] 支付")
    status, body = _call("PUT", f"{base}/api/parking/pay/{entry_order_id}", None, token)
    _check("支付成功", body.get("code") == 200 and (body.get("data") or {}).get("pay_status") == "paid", str(body))

    status, body = _call("PUT", f"{base}/api/parking/pay/{entry_order_id}", None, token)
    _check("重复支付被拒", body.get("code") == 400, str(body))

    status, body = _call("PUT", f"{base}/api/parking/pay/999999", None, token)
    _check("支付不存在订单返回 404", body.get("code") == 404, str(body))

    print("\n[8] 用户资料与订单列表")
    status, body = _call("GET", f"{base}/api/user/profile", None, token)
    profile = body.get("data") or {}
    _check("profile 可用", body.get("code") == 200, str(body))
    _check(
        "profile 用户 ID 与登录一致",
        str(profile.get("user_id")) == str(user_id),
        f"{profile} vs {user_id}",
    )
    _check("profile 不回传密码", "password" not in profile, str(profile))

    # 越权校验：先让另一个账号造一条订单，再确认本人列表里看不到
    other_name = f"smoke_b_{suffix}"
    other_plate = f"皖C{suffix[-5:]}"
    _call("POST", f"{base}/api/user/register", {"username": other_name, "password": password}, None)
    _, body = _call("POST", f"{base}/api/user/login", {"username": other_name, "password": password}, None)
    other_token = (body.get("data") or {}).get("access_token")
    other_order_id = None
    if other_token:
        _, body = _call(
            "POST",
            f"{base}/api/parking/fee",
            {"plate": other_plate, "in_time": in_time, "out_time": out_time},
            other_token,
        )
        other_order_id = (body.get("data") or {}).get("order_id")
    _check("另一账号订单创建成功", other_order_id is not None, str(body))

    status, body = _call("GET", f"{base}/api/parking/orders", None, token)
    listed = body.get("data") or []
    listed_ids = {item.get("order_id") for item in listed}
    _check("订单列表可用", body.get("code") == 200, str(body))
    _check(
        "订单列表包含本次产生的两条订单",
        {entry_order_id, free_order_id} <= listed_ids,
        f"期望 {entry_order_id},{free_order_id} 实际 {sorted(listed_ids)}",
    )
    _check(
        "看不到其他账号的订单",
        other_order_id not in listed_ids,
        f"泄露了订单 {other_order_id}",
    )

    print("\n[9] 注销账号")
    status, body = _call("DELETE", f"{base}/api/user/delete", {"username": username, "password": "wrong"}, token)
    _check("注销需校验密码", body.get("code") == 401, str(body))

    status, body = _call("DELETE", f"{base}/api/user/delete", {"username": username, "password": password}, token)
    _check("注销成功", body.get("code") == 200, str(body))

    status, body = _call("POST", f"{base}/api/user/login", {"username": username, "password": password})
    _check("注销后无法登录", body.get("code") == 401, str(body))

    print(f"\n== 结果：{_passed} 通过，{len(_failures)} 失败 ==")
    for item in _failures:
        print(f"  - {item}")
    return 0 if not _failures else 1


def main(argv: list[str] | None = None) -> int:
    """脚本入口。

    Args:
        argv: 命令行参数。

    Returns:
        进程退出码。
    """
    # 默认基址跟随 CARPARK_PORT，避免本机 5000 被其他项目占用时打到错误服务上
    _host = os.getenv("CARPARK_HOST", "127.0.0.1")
    if _host in ("0.0.0.0", "::"):
        _host = "127.0.0.1"
    _default_base = f"http://{_host}:{os.getenv('CARPARK_PORT', '5001')}"

    parser = argparse.ArgumentParser(description="停车系统端到端冒烟测试")
    parser.add_argument("--base", default=_default_base, help=f"服务根地址（默认 {_default_base}）")
    args = parser.parse_args(argv)
    return run(args.base.rstrip("/"))


if __name__ == "__main__":
    sys.exit(main())
