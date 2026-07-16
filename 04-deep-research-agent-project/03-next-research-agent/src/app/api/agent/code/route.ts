import { ToolLoopAgent, tool } from 'ai';
import { deepseek } from "@ai-sdk/deepseek";
import { z } from 'zod';

const execPromise = promisify(exec);



export async function POST() {
  try {
    const weatherAgent = new ToolLoopAgent({
      model: deepseek("deepseek-v4-flash"),
      instructions: 'You are an expert software engineer.',
      tools: {
        runCode: tool({
          description: 'Execute Python code',
          inputSchema: z.object({
            code: z.string(),
          }),
          execute: async ({ code }) => {
            // Execute code and return result
            return { output: 'Code executed successfully' };
          },
        }),
      },
    });

    const result = await weatherAgent.generate({
      prompt: '生成一个求和函数用python',
    });

    console.log(result.text); // agent's final answer
    console.log(result.steps); // steps taken by the agent

    return Response.json({ text: result.text, steps: result.steps });
  } catch (err) {
    console.error('DeepSeek error:', err);
  }
}
