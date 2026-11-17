# coding: utf-8
from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.schema import FetchedValue
from sqlalchemy.ext.declarative import declarative_base


Base = declarative_base()
metadata = Base.metadata


class BlackCar(Base):
    __tablename__ = 'black_car'

    id = Column(Integer, primary_key=True)
    plate = Column(String(20), nullable=False, unique=True)


class ParkingOrder(Base):
    __tablename__ = 'parking_order'

    order_id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    plate = Column(String(20), nullable=False)
    in_time = Column(DateTime)
    out_time = Column(DateTime)
    total_fee = Column(Float, server_default=FetchedValue())
    pay_status = Column(String(20), server_default=FetchedValue())


class ParkingRecord(Base):
    __tablename__ = 'parking_record'

    record_id = Column(Integer, primary_key=True)
    plate = Column(String(20), nullable=False)
    in_time = Column(DateTime, server_default=FetchedValue())
    order_id = Column(Integer)
    status = Column(String(20), server_default=FetchedValue())


class SysUser(Base):
    __tablename__ = 'sys_user'

    user_id = Column(Integer, primary_key=True)
    username = Column(String(50), nullable=False, unique=True)
    password = Column(String(100), nullable=False)
    plate = Column(String(20), nullable=True)                                                                                                                        
    create_time = Column(DateTime, server_default=FetchedValue())
                                                                                   

class ServiceTicket(Base):
    """客服工单：Agent 建单、转人工都落这里，工单号用于回访与指标统计。"""
    __tablename__ = 'service_ticket'

    ticket_id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    session_id = Column(String(64))
    plate = Column(String(20))
    category = Column(String(20), nullable=False, default='other')
    summary = Column(String(500), nullable=False)                                                                                                                                                                                                                                                                                                                     
    status = Column(String(20), nullable=False, default='open')
    source = Column(String(20), nullable=False, default='agent')
    create_time = Column(DateTime, nullable=False)


class AgentMessage(Base):
    """Agent 会话记忆：按 session_id 存取最近若干轮，支撑多轮指代与补槽。"""
    __tablename__ = 'agent_message'

    id = Column(Integer, primary_key=True)
    session_id = Column(String(64), nullable=False, index=True)
    role = Column(String(12), nullable=False)
    content = Column(String(1000), nullable=False)
    create_time = Column(DateTime, nullable=False)