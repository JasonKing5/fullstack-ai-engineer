// src/app/page.tsx
'use client';

import { useChat } from '@ai-sdk/react';
import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Bot, User, Send, Loader2 } from 'lucide-react';
import {
  PlannerCard,
  RetrieverCard,
  DrafterCard,
  ReviewerCard,
  ApprovalCard,
} from '@/components/chat/GenerativeUI';

// ── 流式读取工具函数 ──────────────────────────────────────────────────────────
async function readContinueStream(
  res: Response,
  on9: (tc: any) => void,
  on0: (text: string) => void,
) {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: false });
  let buf = '';

  const processLine = (line: string) => {
    if (line.startsWith('9:')) {
      try { on9(JSON.parse(line.slice(2))); } catch { console.warn('9: parse fail', line); }
    } else if (line.startsWith('0:')) {
      try { on0(JSON.parse(line.slice(2))); } catch { console.warn('0: parse fail', line); }
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop() ?? '';
    lines.forEach(processLine);
  }
  const flushed = buf + decoder.decode();
  if (flushed) processLine(flushed);
}

export default function ChatPage() {
  const [isApproving, setIsApproving] = useState(false);
  const [approvalResults, setApprovalResults] = useState<Record<string, 'approved' | 'rejected' | null>>({});
  const [finalReports, setFinalReports] = useState<Record<string, string>>({});
  // 待反馈的拒绝 toolCallId：非 null 时，下一次提交为修改意见而非新问题
  const [pendingRejectionToolCallId, setPendingRejectionToolCallId] = useState<string | null>(null);

  const questionIdRef = useRef('');
  const toolCallQuestionIdRef = useRef<Record<string, string>>({});
  const scrollRef = useRef<HTMLDivElement>(null);

  const [threadId, setThreadId] = useState<string>('');
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setThreadId(`b2b-session-${Math.random().toString(36).substring(7)}`);
    setIsMounted(true);
  }, []);

  const {
    messages,
    data: chatData,
    input,
    handleInputChange,
    handleSubmit,
    isLoading,
    addToolResult,
    setMessages,
    setInput,
  } = useChat({
    api: '/api/research/chat',
    body: { thread_id: threadId, company: 'Tesla' },
    maxSteps: 1,
    onError: (err) => alert(`系统错误: ${err.message}`),
  });

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isLoading, isApproving]);

  // ── 调用 continue 端点，将重跑步骤追加为新 assistant 消息 ────────────────────
  const runContinue = async (continueQuestionId: string) => {
    const continueRes = await fetch('/api/research/continue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ thread_id: threadId, question_id: continueQuestionId }),
    });
    if (!continueRes.body) throw new Error('无数据流返回');

    // 先占位，插入空消息，后续逐步追加 tool invocations
    const retryMsgId = `retry-${Date.now()}`;
    setMessages(prev => [
      ...prev,
      { id: retryMsgId, role: 'assistant', content: '', toolInvocations: [] } as any,
    ]);

    await readContinueStream(
      continueRes,
      (tc) => {
        // 每个事件到达时立即更新消息，实现逐步渲染
        const invocation = { toolCallId: tc.toolCallId, toolName: tc.toolName, args: tc.args, state: 'call' };
        setMessages(prev => prev.map(m =>
          m.id === retryMsgId
            ? { ...m, toolInvocations: [...((m as any).toolInvocations ?? []), invocation] } as any
            : m
        ));
        if (tc.toolName === 'request_human_approval') {
          toolCallQuestionIdRef.current[tc.toolCallId] = continueQuestionId;
          setApprovalResults(prev => ({ ...prev, [tc.toolCallId]: null }));
        }
      },
      () => {}, // 重跑流程不含 0: 行
    );
  };

  // ── 审批：同意 ────────────────────────────────────────────────────────────────
  const handleApprove = async (approved: boolean, toolCallId: string) => {
    addToolResult({ toolCallId, result: { approved } });

    if (!approved) {
      // 拒绝：仅更新 UI，等待用户在输入框输入修改意见
      setApprovalResults(prev => ({ ...prev, [toolCallId]: 'rejected' }));
      setPendingRejectionToolCallId(toolCallId);
      setMessages(prev => [
        ...prev,
        {
          id: `rejection-prompt-${Date.now()}`,
          role: 'assistant',
          content: '已收到您的拒绝请求。请在下方输入具体的修改意见，提交后我将根据您的反馈重新为您检索并生成研报。',
        } as any,
      ]);
      return;
    }

    // 同意：注入状态 → continue 取定稿
    setIsApproving(true);
    setApprovalResults(prev => ({ ...prev, [toolCallId]: 'approved' }));
    setFinalReports(prev => ({ ...prev, [toolCallId]: '' }));

    try {
      const approveRes = await fetch('/api/research/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_id: threadId, approved: true, feedback: '' }),
      });
      if (!approveRes.ok) {
        const err = await approveRes.json().catch(() => ({}));
        throw new Error((err as any).detail || '审批状态更新失败');
      }

      const currentQuestionId = toolCallQuestionIdRef.current[toolCallId] || questionIdRef.current;
      const continueRes = await fetch('/api/research/continue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_id: threadId, question_id: currentQuestionId }),
      });
      if (!continueRes.body) throw new Error('无数据流返回');

      await readContinueStream(
        continueRes,
        () => {},
        (text) => setFinalReports(prev => ({ ...prev, [toolCallId]: (prev[toolCallId] ?? '') + text })),
      );
    } catch (e: any) {
      alert(`审批请求失败: ${e.message}`);
      setApprovalResults(prev => ({ ...prev, [toolCallId]: null }));
    } finally {
      setIsApproving(false);
    }
  };

  // ── 用户提交修改意见后，以反馈继续图执行 ─────────────────────────────────────
  const handleRejectionFeedback = async (feedback: string, toolCallId: string) => {
    // 将用户反馈显示为对话气泡
    setMessages(prev => [
      ...prev,
      { id: `feedback-${Date.now()}`, role: 'user', content: feedback } as any,
    ]);

    setIsApproving(true);
    const continueQuestionId = crypto.randomUUID();

    try {
      const approveRes = await fetch('/api/research/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_id: threadId, approved: false, feedback }),
      });
      if (!approveRes.ok) {
        const err = await approveRes.json().catch(() => ({}));
        throw new Error((err as any).detail || '审批状态更新失败');
      }

      await runContinue(continueQuestionId);
    } catch (e: any) {
      alert(`重新生成失败: ${e.message}`);
    } finally {
      setIsApproving(false);
    }
  };

  if (!isMounted) return null;

  const lastMessage = messages[messages.length - 1];
  const showThinking = isLoading && lastMessage?.role === 'user';

  return (
    <div className="flex flex-col h-screen bg-slate-50 items-center py-8">
      <Card className="w-full max-w-4xl h-[90vh] flex flex-col shadow-xl overflow-hidden border-slate-200">

        {/* Header */}
        <div className="bg-slate-900 p-4 flex items-center justify-between text-white">
          <div className="flex items-center gap-2">
            <Bot className="h-6 w-6 text-blue-400" />
            <h1 className="font-bold text-lg tracking-wide">Enterprise AI Agent</h1>
          </div>
          <Badge variant="secondary" className="bg-slate-700 text-slate-200">
            {threadId}
          </Badge>
        </div>

        {/* Chat Area */}
        <div className="flex-1 min-h-0 overflow-y-auto p-6" ref={scrollRef}>
          {messages.length === 0 && (
            <div className="h-full flex flex-col items-center justify-center text-slate-400 space-y-4 pt-20">
              <Bot className="h-16 w-16 opacity-20" />
              <p>输入你的需求，触发企业级知识库分析引擎...</p>
            </div>
          )}

          {messages.map((m) => {
            const allInvocations = (m as any).toolInvocations || [];
            return (
              <div key={m.id} className={`mb-8 flex gap-4 ${m.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                <div className={`h-8 w-8 rounded-full flex items-center justify-center shrink-0 ${m.role === 'user' ? 'bg-blue-600' : 'bg-slate-800'}`}>
                  {m.role === 'user' ? <User className="h-5 w-5 text-white" /> : <Bot className="h-5 w-5 text-white" />}
                </div>

                <div className={`flex-1 max-w-[85%] ${m.role === 'user' ? 'text-right' : 'text-left'}`}>
                  {m.content && (
                    <div className={`inline-block rounded-xl px-5 py-4 shadow-sm text-left ${m.role === 'user' ? 'bg-blue-600 text-white' : 'bg-white border border-slate-100'}`}>
                      <div className={`prose prose-sm max-w-none ${m.role === 'user' ? 'prose-invert' : 'prose-slate'}`}>
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                      </div>
                    </div>
                  )}

                  {allInvocations.map((tool: any) => {
                    if (tool.toolName === 'ui_planner') {
                      return <PlannerCard key={tool.toolCallId} tool={tool} allInvocations={allInvocations} />;
                    }
                    if (tool.toolName === 'ui_retriever') {
                      return <RetrieverCard key={tool.toolCallId} tool={tool} allInvocations={allInvocations} />;
                    }
                    if (tool.toolName === 'ui_drafter') {
                      return <DrafterCard key={tool.toolCallId} tool={tool} allInvocations={allInvocations} chatData={chatData || []} />;
                    }
                    if (tool.toolName === 'ui_reviewer') {
                      return <ReviewerCard key={tool.toolCallId} tool={tool} allInvocations={allInvocations} />;
                    }
                    if (tool.toolName === 'request_human_approval') {
                      return (
                        <ApprovalCard
                          key={tool.toolCallId}
                          isApproving={isApproving}
                          onApprove={(approved) => handleApprove(approved, tool.toolCallId)}
                          result={approvalResults[tool.toolCallId] ?? null}
                          finalReport={finalReports[tool.toolCallId] ?? ''}
                        />
                      );
                    }
                    return null;
                  })}
                </div>
              </div>
            );
          })}

          {showThinking && (
            <div className="mb-8 flex gap-4 flex-row">
              <div className="h-8 w-8 rounded-full flex items-center justify-center shrink-0 bg-slate-800">
                <Bot className="h-5 w-5 text-white" />
              </div>
              <div className="flex items-center gap-2 px-4 py-3 rounded-xl bg-white border border-slate-100 shadow-sm">
                <Loader2 className="h-4 w-4 text-slate-400 animate-spin" />
                <span className="text-sm text-slate-400">思考中...</span>
              </div>
            </div>
          )}
        </div>

        {/* Input Area */}
        <div className="p-4 bg-white border-t border-slate-100">
          {/* 待反馈提示条 */}
          {pendingRejectionToolCallId && (
            <div className="mb-2 px-3 py-1.5 rounded-lg bg-amber-50 border border-amber-200 text-xs text-amber-700">
              请输入修改意见，提交后将根据您的反馈重新生成研报
            </div>
          )}
          <form
            onSubmit={(e) => {
              if (pendingRejectionToolCallId) {
                e.preventDefault();
                if (!input.trim()) return;
                const feedback = input;
                const toolCallId = pendingRejectionToolCallId;
                setInput('');
                setPendingRejectionToolCallId(null);
                handleRejectionFeedback(feedback, toolCallId);
              } else {
                questionIdRef.current = crypto.randomUUID();
                handleSubmit(e, { body: { question_id: questionIdRef.current } });
              }
            }}
            className="flex gap-3 relative"
          >
            <Input
              value={input}
              onChange={handleInputChange}
              placeholder={pendingRejectionToolCallId ? '请输入修改意见...' : '例如：请分析特斯拉最新财报中的流动性风险...'}
              className="pr-12 py-6 shadow-sm border-slate-300 focus-visible:ring-blue-500 rounded-xl"
            />
            <Button
              type="submit"
              size="icon"
              disabled={isLoading || isApproving}
              className="absolute right-1.5 top-1.5 h-9 w-9 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50"
            >
              <Send className="h-4 w-4" />
            </Button>
          </form>
          <p className="text-center text-xs text-slate-400 mt-3">
            Powered by Next.js, LangGraph, and Qdrant.
          </p>
        </div>
      </Card>
    </div>
  );
}
