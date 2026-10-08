from fastapi import APIRouter, Header, HTTPException, Request
from linebot.v3.exceptions import InvalidSignatureError

from app.controllers import line

router = APIRouter()


@router.post("/webhook/line")
async def webhook(request: Request, x_line_signature: str = Header(default="")):
    body = (await request.body()).decode("utf-8")
    try:
        await line.handle_webhook(body, x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="invalid signature")
    return "OK"
