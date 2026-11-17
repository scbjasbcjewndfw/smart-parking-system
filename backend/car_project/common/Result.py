import datetime
import decimal
from enum import Enum


class Result:
    """统一 API 返回结果封装"""

    @staticmethod
    def success(msg='操作成功', data=None):
        return {
            "code": 200,
            "msg": msg,
            "data": Result.to_serializable(data)
        }

    @staticmethod
    def fail(code=400, msg='操作失败', data=None):
        return {
            "code": code,
            "msg": msg,
            "data": Result.to_serializable(data)
        }

    @staticmethod
    def to_serializable(data):
        """递归将 ORM 对象及不可 JSON 序列化的类型转换为可序列化类型"""
        if data is None or isinstance(data, bool):
            return data
        if isinstance(data, Enum):
            return data.value
        if isinstance(data, (int, float, str)):
            return data
        if hasattr(data, 'to_dict'):
            return Result.to_serializable(data.to_dict())
        if isinstance(data, (datetime.datetime, datetime.date)):
            return data.isoformat()
        if isinstance(data, decimal.Decimal):
            return str(data)
        if isinstance(data, (list, tuple)):
            return [Result.to_serializable(item) for item in data]
        if isinstance(data, dict):
            return {k: Result.to_serializable(v) for k, v in data.items()}
        return str(data)
