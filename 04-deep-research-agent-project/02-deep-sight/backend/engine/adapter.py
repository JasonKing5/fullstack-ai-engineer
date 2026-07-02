# backend/engine/adapter.py
import asyncio
import json
import uuid


async def vercel_stream_adapter(graph_instance, config, inputs=None):
    """
    工业级流适配总线：
    利用 asyncio.Queue 实现多路复用（图事件流 + 后台心跳流），并处理客户端断开连接。
    """
    queue = asyncio.Queue()

    # --- 任务 1：图状态机运行协程 ---
    async def run_graph():
        try:
            # 监听图运行中的 v2 事件流
            async for event in graph_instance.astream_events(
                inputs, config, version="v2"
            ):
                kind = event["event"]
                name = event["name"]

                # 1. 拦截大模型文本流
                if kind == "on_chat_model_stream":
                    # 从元数据中精确获取当前是在哪个图节点里发出的 token
                    node_name = event.get("metadata", {}).get("langgraph_node", "")

                    # 屏蔽 Planner 和 Reviewer 的内部 JSON 思考过程
                    if node_name in ["drafter_node", "publish_node"]:
                        chunk = event["data"]["chunk"]
                        if chunk.content and isinstance(chunk.content, str):
                            await queue.put(f"0:{json.dumps(chunk.content)}\n")

                # 2. 拦截节点启动事件，伪造 Tool Call 触发前端骨架屏 (Generative UI)
                elif kind == "on_chain_start":
                    if name == "retriever_node":
                        call = [
                            {
                                "toolCallId": f"sys_ret_{uuid.uuid4().hex[:6]}",
                                "toolName": "ui_retrieving",
                                "args": {},
                            }
                        ]
                        await queue.put(f"9:{json.dumps(call)}\n")
                    elif name == "reviewer_node":
                        call = [
                            {
                                "toolCallId": f"sys_rev_{uuid.uuid4().hex[:6]}",
                                "toolName": "ui_reviewing",
                                "args": {},
                            }
                        ]
                        await queue.put(f"9:{json.dumps(call)}\n")

            # 3. 运行结束，检查是否因 interrupt_before 挂起
            state = await graph_instance.aget_state(config)
            if state.next and "publish_node" in state.next:
                # 触发真实的人类审批 UI 卡片
                approval_call = [
                    {
                        "toolCallId": f"approve_{config['configurable']['thread_id']}",
                        "toolName": "request_human_approval",
                        "args": {"summary": "AI 研报起草与交叉核对完成，请人工终审。"},
                    }
                ]
                await queue.put(f"9:{json.dumps(approval_call)}\n")

        except asyncio.CancelledError:
            # 捕获客户端断开连接的取消异常，优雅退出
            pass
        except Exception as e:
            # 捕获任何异常（如数据库崩了），发送 Vercel 标准错误协议 (3:)
            error_msg = f"AI 引擎内部错误: {str(e)}"
            await queue.put(f"3:{json.dumps(error_msg)}\n")
        finally:
            # 发送结束停止符
            await queue.put(None)

    # --- 任务 2：SSE 心跳保活协程 ---
    async def keep_alive():
        try:
            while True:
                await asyncio.sleep(15)  # 每 15 秒发送一次心跳
                # 发送 SSE 标准注释行，Vercel SDK 会忽略，但 Nginx/AWS 会认为连接存活
                await queue.put(": keep-alive\n\n")
        except asyncio.CancelledError:
            pass

    # 将两个任务投递到事件循环
    task_graph = asyncio.create_task(run_graph())
    task_heartbeat = asyncio.create_task(keep_alive())

    # --- 消费者逻辑：弹出队列数据发送给前端 ---
    try:
        while True:
            item = await queue.get()
            if item is None:
                break  # 收到停止符，结束流
            yield item
    finally:
        # 如果用户关掉浏览器，StreamingResponse 抛出断开异常，
        # 此 finally 块会被触发。强制杀死图运行和心跳任务，防止幽灵 Token 消耗！
        task_heartbeat.cancel()
        if not task_graph.done():
            task_graph.cancel()
