# backend/api/research_router.py
from engine.adapter import vercel_stream_adapter
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


class ChatRequest(BaseModel):
    thread_id: str
    company: str
    message: str


@router.post("/api/research/chat")
async def chat_stream(request: Request, req: ChatRequest):
    graph = request.app.state.agent_graph
    # 配置会话 ID，实现 PG 状态隔离
    config = {"configurable": {"thread_id": req.thread_id}}

    # 初始化传入图的 payload
    inputs = {
        "company": req.company,
        "query": req.message,
    }

    return StreamingResponse(
        vercel_stream_adapter(graph, config, inputs=inputs),
        media_type="text/event-stream",
    )


class ApproveRequest(BaseModel):
    thread_id: str
    approved: bool
    feedback: str = ""


@router.post("/api/research/approve")
async def approve_step(request: Request, req: ApproveRequest):
    graph = request.app.state.agent_graph
    config = {"configurable": {"thread_id": req.thread_id}}

    # 检查当前会话是否真的处于挂起状态
    state = await graph.aget_state(config)
    if not state.next:
        raise HTTPException(status_code=400, detail="当前没有等待审批的任务")

    if req.approved:
        # 同意：状态注入 approved=True。
        # as_node="reviewer_node" 伪装成是从上一个节点出来的，让状态机顺理成章地流向 publish_node
        await graph.aupdate_state(config, {"approved": True}, as_node="reviewer_node")
    else:
        # 拒绝并打回：清空防死循环计数器，附上反馈意见。
        await graph.aupdate_state(
            config,
            {"approved": False, "feedback": req.feedback, "revision_count": 0},
            as_node="reviewer_node",
        )

    # 唤醒后继续执行，因为后续还有流式输出（比如 publish_node 的最终结果），所以依然接上流适配器
    return StreamingResponse(
        vercel_stream_adapter(graph, config, inputs=None),
        media_type="text/event-stream",
    )
