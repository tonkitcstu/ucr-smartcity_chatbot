"""Chat with the model, using Redis as the conversation memory."""

from redis.asyncio import Redis

from app.clients import llm
from app.services import memory

SYSTEM_PROMPT = "You are a helpful assistant. Reply concisely."


async def reply(r: Redis, session_id: str, message: str) -> str:
    history = await memory.load(r, session_id)

    answer, _used = await llm.chat(
        [{"role": "system", "content": SYSTEM_PROMPT}]
        + history
        + [{"role": "user", "content": message}]
    )

    # Only remember the turn once the model actually answered.
    await memory.append(r, session_id, "user", message)
    await memory.append(r, session_id, "assistant", answer)

    return answer
