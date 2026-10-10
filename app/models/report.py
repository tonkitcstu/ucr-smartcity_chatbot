from pydantic import BaseModel


class ReportDraft(BaseModel):
    """รายงานหนึ่งใบที่ AI ร่าง · location / images เป็นเลขป้าย [ตำแหน่ง n] / [รูป n]"""
    desc: str
    tags: list[str]
    location: int | None
    images: list[int]


class Analysis(BaseModel):
    """รูปแบบที่ตัววิเคราะห์ต้องตอบ (structured output)"""
    reports: list[ReportDraft]
