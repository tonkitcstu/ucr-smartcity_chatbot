from pydantic import BaseModel


class HealthStatus(BaseModel):
    """4 ตัวที่บอทต้องมีครบถึงจะตอบผู้แจ้งได้ · true = อยู่"""
    database: bool
    redis: bool
    worker: bool
    sweeper: bool
