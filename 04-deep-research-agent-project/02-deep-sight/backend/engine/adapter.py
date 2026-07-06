# backend/engine/adapter.py
import asyncio
import json
import uuid


def _tc(tool_name: str, round_num: int, suffix: str, args: dict) -> str:
    """构造一条 9: tool call 流数据行"""
    call = {
        "toolCallId": f"{tool_name}_{suffix}_r{round_num}_{uuid.uuid4().hex[:4]}",
        "toolName": tool_name,
        "args": {"round": round_num, **args},
    }
    return f"9:{json.dumps(call)}\n"


async def vercel_stream_adapter(graph_instance, config, inputs=None, question_id: str = ""):
    """
    工业级流适配总线：
    利用 asyncio.Queue 实现多路复用（图事件流 + 后台心跳流），并处理客户端断开连接。
    """
    queue = asyncio.Queue()

    # --- 任务 1：图状态机运行协程 ---
    async def run_graph():
        round_num = 0          # 当前执行轮次（每次 planner 启动 +1）
        pending_queries: list  = []  # planner 产出的关键词，retriever 启动时用

        try:
            async for event in graph_instance.astream_events(
                inputs, config, version="v2"
            ):
                kind = event["event"]
                name = event["name"]

                # ── 1. 大模型文本 token 流 ───────────────────────────────────
                if kind == "on_chat_model_stream":
                    node_name = event.get("metadata", {}).get("langgraph_node", "")
                    chunk = event["data"]["chunk"]
                    if not (chunk.content and isinstance(chunk.content, str)):
                        pass
                    elif node_name == "drafter_node":
                        data_line = [{"type": "draft", "round": round_num, "question_id": question_id, "text": chunk.content}]
                        await queue.put(f"2:{json.dumps(data_line)}\n")
                    elif node_name == "publish_node":
                        await queue.put(f"0:{json.dumps(chunk.content)}\n")

                # ── 2. 节点启动事件 ──────────────────────────────────────────
                elif kind == "on_chain_start":
                    if name == "planner_node":
                        round_num += 1
                        await queue.put(_tc("ui_planner", round_num, "start",
                                           {"state": "start"}))

                    elif name == "retriever_node":
                        await queue.put(_tc("ui_retriever", round_num, "start",
                                           {"state": "start", "queries": pending_queries}))

                    elif name == "drafter_node":
                        await queue.put(_tc("ui_drafter", round_num, "start",
                                           {"state": "start", "question_id": question_id}))

                    elif name == "reviewer_node":
                        await queue.put(_tc("ui_reviewer", round_num, "start",
                                           {"state": "start"}))

                # ── 3. 节点完成事件（携带输出数据）──────────────────────────
                elif kind == "on_chain_end":
                    output = event["data"].get("output") or {}

                    if name == "planner_node":
                        queries = output.get("search_queries", [])
                        pending_queries = queries
                        await queue.put(_tc("ui_planner", round_num, "done",
                                           {"state": "done", "queries": queries}))

                    elif name == "retriever_node":
                        await queue.put(_tc("ui_retriever", round_num, "done",
                                           {"state": "done", "queries": pending_queries}))

                    elif name == "drafter_node":
                        revision_count = output.get("revision_count", round_num)
                        await queue.put(_tc("ui_drafter", round_num, "done",
                                           {"state": "done", "revision_count": revision_count, "question_id": question_id}))

                    elif name == "reviewer_node":
                        feedback = output.get("feedback", "")
                        passed = not feedback or feedback == "无"
                        await queue.put(_tc("ui_reviewer", round_num, "done",
                                           {"state": "done", "feedback": feedback,
                                            "passed": passed}))

                    elif name == "publish_node":
                        # publish_node 是普通函数（非 LLM），不会触发 on_chat_model_stream
                        # 必须在 on_chain_end 中捕获 final_report 并以 0: 文本行推送给前端
                        final_report = output.get("final_report", "")
                        if final_report:
                            await queue.put(f"0:{json.dumps(final_report)}\n")

            # ── 4. 流结束，检查是否挂起等待人工审批 ──────────────────────────
            state = await graph_instance.aget_state(config)
            if state.next and "publish_node" in state.next:
                approval_call = {
                    "toolCallId": f"approve_{config['configurable']['thread_id']}_{question_id}",
                    "toolName": "request_human_approval",
                    "args": {"summary": "AI 研报起草与交叉核对完成，请人工终审。"},
                }
                await queue.put(f"9:{json.dumps(approval_call)}\n")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            error_msg = f"AI 引擎内部错误: {str(e)}"
            await queue.put(f"3:{json.dumps(error_msg)}\n")
        finally:
            await queue.put(None)

    # --- 任务 2：心跳保活协程 ---
    async def keep_alive():
        try:
            while True:
                await asyncio.sleep(15)
                await queue.put("2:[]\n")
        except asyncio.CancelledError:
            pass

    task_graph = asyncio.create_task(run_graph())
    task_heartbeat = asyncio.create_task(keep_alive())

    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        task_heartbeat.cancel()
        if not task_graph.done():
            task_graph.cancel()
