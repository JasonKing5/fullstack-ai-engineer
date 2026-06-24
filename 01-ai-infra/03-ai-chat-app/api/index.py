import os
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi import Request as FastAPIRequest
from fastapi.responses import StreamingResponse
from openai import OpenAI
from pydantic import BaseModel

from .utils.prompt import ClientMessage, convert_to_openai_messages
from .utils.stream import patch_response_with_headers, stream_text
from .utils.tools import AVAILABLE_TOOLS, TOOL_DEFINITIONS

load_dotenv()

app = FastAPI()


class Request(BaseModel):
    messages: List[ClientMessage]


@app.post("/api/chat")
async def handle_chat_data(request: Request, protocol: str = Query("data")):
    messages = request.messages
    openai_messages = convert_to_openai_messages(messages)

    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv(
            "OPENAI_BASE_URL"
        ),  # None = 默认 OpenAI；填 LiteLLM 地址则走代理
    )

    response = StreamingResponse(
        stream_text(
            client, openai_messages, TOOL_DEFINITIONS, AVAILABLE_TOOLS, protocol
        ),
        media_type="text/event-stream",
    )
    return patch_response_with_headers(response, protocol)
