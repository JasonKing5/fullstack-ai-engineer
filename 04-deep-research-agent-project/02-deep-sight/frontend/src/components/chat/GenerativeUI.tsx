// src/components/chat/GenerativeUI.tsx
'use client';

import { useMemo, useState } from 'react';
import { ErrorBoundary } from 'react-error-boundary';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  AlertCircle, Search, Brain, PenLine, Eye, ThumbsUp, ThumbsDown,
  FileCheck2, Copy, Check,
} from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

// ─── 错误降级 ────────────────────────────────────────────────────────────────
function ErrorFallback({ error }: { error: Error }) {
  return (
    <Alert variant="destructive" className="my-1">
      <AlertCircle className="h-4 w-4" />
      <AlertTitle>UI 渲染失败</AlertTitle>
      <AlertDescription className="text-xs">{error.message}</AlertDescription>
    </Alert>
  );
}
function Safe({ children }: { children: React.ReactNode }) {
  return <ErrorBoundary FallbackComponent={ErrorFallback}>{children}</ErrorBoundary>;
}

// ─── 公共样式 ─────────────────────────────────────────────────────────────────
const DONE_ROW = 'px-3 py-2 my-1 rounded-lg border';

// ─── 从 chatData 按类型、轮次、问题 ID 提取流式文本 ──────────────────────────
function useChatDataText(chatData: any[], type: string, round: number, questionId: string): string {
  return useMemo(
    () =>
      chatData
        .filter((d) => d?.type === type && d?.round === round && d?.question_id === questionId)
        .map((d) => d.text)
        .join(''),
    [chatData, type, round, questionId]
  );
}

// ─── Planner Card ─────────────────────────────────────────────────────────────
export function PlannerCard({ tool, allInvocations }: { tool: any; allInvocations: any[] }) {
  return <Safe><_PlannerCard tool={tool} allInvocations={allInvocations} /></Safe>;
}
function _PlannerCard({ tool, allInvocations }: { tool: any; allInvocations: any[] }) {
  const { state, round, queries } = tool.args;

  if (state === 'start') {
    const isDone = allInvocations.some(
      t => t.toolName === 'ui_planner' && t.args.state === 'done' && t.args.round === round
    );
    if (isDone) return null;
    return (
      <div className="px-3 py-2 my-1 flex items-center gap-2 rounded-lg border bg-violet-50 border-violet-100">
        <Brain className="h-4 w-4 text-violet-400 animate-pulse shrink-0" />
        <span className="text-sm text-violet-700">正在制定检索计划...</span>
      </div>
    );
  }

  if (state === 'done' && queries?.length) {
    const label = round > 1 ? `第 ${round} 轮检索计划已就绪` : '检索计划已就绪';
    return (
      <div className={`${DONE_ROW} bg-slate-50 border-slate-100`}>
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-green-500 shrink-0" />
          <span className="text-sm font-medium text-slate-600">{label}</span>
        </div>
        <ul className="mt-1.5 pl-10 space-y-0.5 list-disc">
          {queries.map((q: string, i: number) => (
            <li key={i} className="text-xs text-slate-500 break-all">{q}</li>
          ))}
        </ul>
      </div>
    );
  }
  return null;
}

// ─── Retriever Card ───────────────────────────────────────────────────────────
export function RetrieverCard({ tool, allInvocations }: { tool: any; allInvocations: any[] }) {
  return <Safe><_RetrieverCard tool={tool} allInvocations={allInvocations} /></Safe>;
}
function _RetrieverCard({ tool, allInvocations }: { tool: any; allInvocations: any[] }) {
  const { state, round, queries } = tool.args;

  if (state === 'start') {
    const isDone = allInvocations.some(
      t => t.toolName === 'ui_retriever' && t.args.state === 'done' && t.args.round === round
    );
    if (isDone) return null;
    return (
      <div className="px-3 py-2 my-1 flex items-center gap-2 rounded-lg border bg-blue-50 border-blue-100">
        <Search className="h-4 w-4 text-blue-400 animate-pulse shrink-0" />
        <span className="text-sm text-blue-700">正在检索企业知识库...</span>
      </div>
    );
  }

  if (state === 'done') {
    return (
      <div className={`${DONE_ROW} bg-slate-50 border-slate-100`}>
        <div className="flex items-center gap-2">
          <Search className="h-4 w-4 text-green-500 shrink-0" />
          <span className="text-sm font-medium text-slate-600">
            {queries?.length ?? 0} 个关键词检索完成
          </span>
        </div>
      </div>
    );
  }
  return null;
}

// ─── Drafter Card ─────────────────────────────────────────────────────────────
export function DrafterCard({
  tool,
  allInvocations,
  chatData,
}: {
  tool: any;
  allInvocations: any[];
  chatData: any[];
}) {
  return <Safe><_DrafterCard tool={tool} allInvocations={allInvocations} chatData={chatData} /></Safe>;
}
function _DrafterCard({
  tool,
  allInvocations,
  chatData,
}: {
  tool: any;
  allInvocations: any[];
  chatData: any[];
}) {
  const { state, round, revision_count, question_id } = tool.args;
  const draftText = useChatDataText(chatData, 'draft', round, question_id ?? '');

  if (state === 'start') {
    const isDone = allInvocations.some(
      t => t.toolName === 'ui_drafter' && t.args.state === 'done' && t.args.round === round
    );
    if (isDone) return null;
    return (
      <div className={`${DONE_ROW} bg-amber-50 border-amber-100`}>
        <div className="flex items-center gap-2">
          <PenLine className="h-4 w-4 text-amber-400 animate-pulse shrink-0" />
          <span className="text-sm text-amber-700">正在起草分析报告...</span>
        </div>
        {draftText && (
          <div className="mt-2 pl-6 prose prose-sm max-w-none prose-slate leading-relaxed">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{draftText}</ReactMarkdown>
          </div>
        )}
      </div>
    );
  }

  if (state === 'done') {
    const count = revision_count ?? round;
    const label = count > 1 ? `第 ${count} 轮草稿已生成` : '草稿已生成';
    return (
      <div className={`${DONE_ROW} bg-slate-50 border-slate-100`}>
        <div className="flex items-center gap-2">
          <PenLine className="h-4 w-4 text-green-500 shrink-0" />
          <span className="text-sm font-medium text-slate-600">{label}</span>
        </div>
        {draftText && (
          <div className="mt-2 pl-6 prose prose-sm max-w-none prose-slate leading-relaxed">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{draftText}</ReactMarkdown>
          </div>
        )}
      </div>
    );
  }
  return null;
}

// ─── Reviewer Card ────────────────────────────────────────────────────────────
export function ReviewerCard({ tool, allInvocations }: { tool: any; allInvocations: any[] }) {
  return <Safe><_ReviewerCard tool={tool} allInvocations={allInvocations} /></Safe>;
}
function _ReviewerCard({ tool, allInvocations }: { tool: any; allInvocations: any[] }) {
  const { state, round, feedback, passed } = tool.args;

  if (state === 'start') {
    const isDone = allInvocations.some(
      t => t.toolName === 'ui_reviewer' && t.args.state === 'done' && t.args.round === round
    );
    if (isDone) return null;
    return (
      <div className="px-3 py-2 my-1 flex items-center gap-2 rounded-lg border bg-purple-50 border-purple-100">
        <Eye className="h-4 w-4 text-purple-400 animate-pulse shrink-0" />
        <span className="text-sm text-purple-700">AI 审核员正在进行交叉核对...</span>
      </div>
    );
  }

  if (state === 'done') {
    if (passed) {
      return (
        <div className={`${DONE_ROW} bg-slate-50 border-slate-100`}>
          <div className="flex items-center gap-2">
            <Eye className="h-4 w-4 text-green-500 shrink-0" />
            <span className="text-sm font-medium text-slate-600">质检通过，准备提交人工审核</span>
          </div>
        </div>
      );
    }
    return (
      <div className={`${DONE_ROW} bg-orange-50 border-orange-100`}>
        <div className="flex items-center gap-2">
          <Eye className="h-4 w-4 text-orange-500 shrink-0" />
          <span className="text-sm font-medium text-orange-700">质检未通过，打回重新检索</span>
        </div>
        {feedback && feedback !== '无' && (
          <div className="mt-1.5 pl-6 prose prose-sm max-w-none text-orange-700 leading-relaxed">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{feedback}</ReactMarkdown>
          </div>
        )}
      </div>
    );
  }
  return null;
}

// ─── Copy Button ──────────────────────────────────────────────────────────────
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className="mt-2 flex justify-end">
      <button
        type="button"
        onClick={handleCopy}
        className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-600 transition-colors"
      >
        {copied
          ? <><Check className="h-3.5 w-3.5 text-green-500" /><span className="text-green-500">已复制</span></>
          : <><Copy className="h-3.5 w-3.5" /><span>复制内容</span></>
        }
      </button>
    </div>
  );
}

// ─── Approval Card ────────────────────────────────────────────────────────────
export function ApprovalCard({
  isApproving,
  onApprove,
  result,
  finalReport,
}: {
  isApproving: boolean;
  onApprove: (approved: boolean) => void;
  result: 'approved' | 'rejected' | null;
  finalReport?: string;
}) {
  return (
    <Safe>
      <_ApprovalCard
        isApproving={isApproving}
        onApprove={onApprove}
        result={result}
        finalReport={finalReport}
      />
    </Safe>
  );
}
function _ApprovalCard({
  isApproving,
  onApprove,
  result,
  finalReport,
}: {
  isApproving: boolean;
  onApprove: (approved: boolean) => void;
  result: 'approved' | 'rejected' | null;
  finalReport?: string;
}) {
  if (result === 'approved') {
    const isDone = !isApproving && !!finalReport;
    return (
      <div>
        <div className={`${DONE_ROW} ${isDone ? 'bg-green-50 border-green-200' : 'bg-blue-50 border-blue-200'}`}>
          <div className="flex items-center gap-2">
            <FileCheck2 className={`h-4 w-4 shrink-0 ${isDone ? 'text-green-600' : 'text-blue-500 animate-pulse'}`} />
            <span className={`text-sm font-medium ${isDone ? 'text-green-700' : 'text-blue-700'}`}>
              {isDone ? '定稿已生成' : '已同意，正在生成定稿...'}
            </span>
          </div>
        </div>
        {finalReport && (
          <>
            <div className="mt-3 rounded-xl border border-slate-100 bg-white px-5 py-4 shadow-sm">
              <div className="prose prose-sm max-w-none prose-slate leading-relaxed">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{finalReport}</ReactMarkdown>
              </div>
            </div>
            <CopyButton text={finalReport} />
          </>
        )}
      </div>
    );
  }

  if (result === 'rejected') {
    return (
      <div className={`${DONE_ROW} bg-slate-50 border-slate-200`}>
        <div className="flex items-center gap-2">
          <ThumbsDown className="h-4 w-4 text-slate-500 shrink-0" />
          <span className="text-sm font-medium text-slate-600">已拒绝</span>
        </div>
      </div>
    );
  }

  return (
    <Card className="p-4 my-3 bg-amber-50 border-amber-200 shadow-sm">
      <p className="text-sm text-gray-700 mb-3 leading-relaxed">
        AI 研报起草与交叉核对完成，请您审核。
      </p>
      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          onClick={() => onApprove(true)}
          disabled={isApproving}
          className="bg-green-600 hover:bg-green-700 text-white"
        >
          {isApproving ? '执行中...' : '✅ 同意并生成定稿'}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => onApprove(false)}
          disabled={isApproving}
          className="border-slate-300 text-slate-600 hover:bg-slate-100"
        >
          ❌ 拒绝并重写
        </Button>
      </div>
    </Card>
  );
}
