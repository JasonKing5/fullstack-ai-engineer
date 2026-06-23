import os
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi import Request as FastAPIRequest
from fastapi.responses import StreamingResponse
from openai import OpenAI
from pydantic import BaseModel
from vercel import oidc
from vercel.headers import set_headers

from .utils.prompt import ClientMessage, convert_to_openai_messages
from .utils.stream import patch_response_with_headers, stream_text
from .utils.tools import AVAILABLE_TOOLS, TOOL_DEFINITIONS

load_dotenv()

api_key = os.getenv("LITELLM_API_KEY")


app = FastAPI()


@app.middleware("http")
async def _vercel_set_headers(request: FastAPIRequest, call_next):
    set_headers(dict(request.headers))
    return await call_next(request)


class Request(BaseModel):
    messages: List[ClientMessage]


@app.post("/api/chat")
async def handle_chat_data(request: Request, protocol: str = Query("data")):
    messages = request.messages
    openai_messages = convert_to_openai_messages(messages)

    # client = OpenAI(api_key=oidc.get_vercel_oidc_token(), base_url="https://ai-gateway.vercel.sh/v1")

    client = OpenAI(
        base_url="https://www.litellm.org/",
        api_key=api_key,
    )

    response = StreamingResponse(
        stream_text(
            client, openai_messages, TOOL_DEFINITIONS, AVAILABLE_TOOLS, protocol
        ),
        media_type="text/event-stream",
    )
    return patch_response_with_headers(response, protocol)
