# backend/api/research_router.py
from typing import List, Optional

from engine.adapter import vercel_stream_adapter
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()

_STREAM_HEADERS = {
    "Content-Type": "text/plain; charset=utf-8",
    "x-vercel-ai-data-stream": "v1",
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}

# Message 类来接收 Vercel 发来的消息体
class Message(BaseModel):
    role: str
    content: str
    id: Optional[str] = None


class ChatRequest(BaseModel):
    thread_id: str
    company: str
    messages: List[Message]
    question_id: Optional[str] = ""


@router.post("/api/research/chat")
async def chat_stream(request: Request, req: ChatRequest):
    graph = request.app.state.agent_graph
    config = {"configurable": {"thread_id": req.thread_id}}

    user_message = req.messages[-1].content

    # 初始化 payload，同时重置跨问题的状态字段
    inputs = {
        "company": req.company,
        "query": user_message,
        "context": [],
        "revision_count": 0,
        "feedback": "",
    }

    return StreamingResponse(
        vercel_stream_adapter(graph, config, inputs=inputs, question_id=req.question_id or ""),
        media_type="text/plain",
        headers=_STREAM_HEADERS,
    )


class ApproveRequest(BaseModel):
    thread_id: str
    approved: bool
    feedback: str = ""


@router.post("/api/research/approve")
async def approve_step(request: Request, req: ApproveRequest):
    """纯状态注入：将人类决策写入 LangGraph 状态，不负责流式输出。"""
    graph = request.app.state.agent_graph
    config = {"configurable": {"thread_id": req.thread_id}}

    state = await graph.aget_state(config)
    if not state.next:
        raise HTTPException(status_code=400, detail="当前没有等待审批的任务")

    if req.approved:
        await graph.aupdate_state(config, {"approved": True}, as_node="reviewer_node")
    else:
        await graph.aupdate_state(
            config,
            {"approved": False, "feedback": req.feedback, "revision_count": 0},
            as_node="reviewer_node",
        )

    return {"ok": True, "action": "approved" if req.approved else "rejected"}


class ContinueRequest(BaseModel):
    thread_id: str
    question_id: str = ""


@router.post("/api/research/continue")
async def continue_graph(request: Request, req: ContinueRequest):
    """继续执行已暂停的图，流式返回后续所有事件。"""
    graph = request.app.state.agent_graph
    config = {"configurable": {"thread_id": req.thread_id}}

    return StreamingResponse(
        vercel_stream_adapter(graph, config, inputs=None, question_id=req.question_id),
        media_type="text/plain",
        headers=_STREAM_HEADERS,
    )
