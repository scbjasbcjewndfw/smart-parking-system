# coding: utf-8
"""数据库初始化脚本：建表 + 可选演示数据。

用法（在 ``backend/car_project`` 目录下）::

    .venv/Scripts/python.exe -m scripts.init_db          # 建表 + 演示数据
    .venv/Scripts/python.exe -m scripts.init_db --no-seed  # 只建表
    .venv/Scripts/python.exe -m scripts.init_db --reset    # 清空重建（危险）

脚本会先打印实际使用的数据库地址（密码已脱敏），避免误连生产库。
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from werkzeug.security import generate_password_hash

from config.database import DB_BACKEND, SAFE_DATABASE_URL, SessionLocal, check_connection, engine, init_db
from models.models import Base, ParkingOrder, ParkingRecord, SysUser
from service.parkingService import calc_amount

#: 演示账号，仅用于本地验证
DEMO_USERNAME = "demo"
DEMO_PASSWORD = "123456"
DEMO_PLATE = "皖AD03683"


def _reset() -> None:
    """删除所有表（仅开发环境使用）。"""
    print("!! 正在删除所有表 ...")
    Base.metadata.drop_all(engine)


def _seed() -> None:
    """写入演示账号与三条不同状态的订单。"""
    now = dt.datetime.now().replace(microsecond=0)

    with SessionLocal() as session:
        existed = session.query(SysUser).filter(SysUser.username == DEMO_USERNAME).first()
        if existed is not None:
            print(f"演示账号 {DEMO_USERNAME} 已存在，跳过用户与订单写入")
            return

        user = SysUser(
            username=DEMO_USERNAME,
            password=generate_password_hash(DEMO_PASSWORD),
            plate=DEMO_PLATE,
            create_time=now - dt.timedelta(days=30),
        )
        session.add(user)
        session.flush()

        # 1) 已结算未支付：昨天停车 2h10m
        in1 = now - dt.timedelta(days=1, hours=3)
        out1 = in1 + dt.timedelta(hours=2, minutes=10)
        amount1 = calc_amount(in1, out1)
        order1 = ParkingOrder(
            user_id=user.user_id,
            plate=DEMO_PLATE,
            in_time=in1,
            out_time=out1,
            total_fee=amount1["total_fee"],
            pay_status="unpaid",
        )
        # 2) 已结算已支付：三天前停车 45 分钟
        in2 = now - dt.timedelta(days=3, hours=2)
        out2 = in2 + dt.timedelta(minutes=45)
        amount2 = calc_amount(in2, out2)
        order2 = ParkingOrder(
            user_id=user.user_id,
            plate=DEMO_PLATE,
            in_time=in2,
            out_time=out2,
            total_fee=amount2["total_fee"],
            pay_status="paid",
        )
        session.add_all([order1, order2])
        session.flush()

        # 3) 在场中：30 分钟前入场，out_time 为空，用于验证"未出场不能支付"
        in3 = now - dt.timedelta(minutes=30)
        order3 = ParkingOrder(
            user_id=user.user_id,
            plate="皖A88B88",
            in_time=in3,
            out_time=None,
            total_fee=0,
            pay_status="unpaid",
        )
        session.add(order3)
        session.flush()

        session.add_all(
            [
                ParkingRecord(plate=DEMO_PLATE, in_time=in1, order_id=order1.order_id, status="out"),
                ParkingRecord(plate=DEMO_PLATE, in_time=in2, order_id=order2.order_id, status="out"),
                ParkingRecord(plate="皖A88B88", in_time=in3, order_id=order3.order_id, status="in"),
            ]
        )
        session.commit()

    print(f"演示账号：{DEMO_USERNAME} / {DEMO_PASSWORD}（绑定车牌 {DEMO_PLATE}）")
    print(f"  订单1 未支付已出场：{amount1['total_fee']} 元")
    print(f"  订单2 已支付：{amount2['total_fee']} 元")
    print("  订单3 皖A88B88 在场中（用于验证未出场禁止支付）")


def main(argv: list[str] | None = None) -> int:
    """脚本入口。

    Args:
        argv: 命令行参数，默认取 ``sys.argv[1:]``。

    Returns:
        进程退出码，0 表示成功。
    """
    parser = argparse.ArgumentParser(description="初始化停车系统数据库")
    parser.add_argument("--no-seed", action="store_true", help="只建表，不写演示数据")
    parser.add_argument("--reset", action="store_true", help="先删表再重建（会丢数据）")
    args = parser.parse_args(argv)

    print(f"数据库后端：{DB_BACKEND}")
    print(f"连接地址：{SAFE_DATABASE_URL}")

    ok, message = check_connection()
    if not ok:
        print(f"连接失败：{message}")
        print("MySQL 用户请检查 .env 中的 CARPARK_DB_* 配置，或改用 CARPARK_DB_BACKEND=sqlite")
        return 1

    if args.reset:
        _reset()

    init_db()
    print("建表完成")

    if not args.no_seed:
        _seed()

    return 0


if __name__ == "__main__":
    sys.exit(main())
