// ********** generateText ************
// import { generateText } from 'ai';
// import { deepseek } from '@ai-sdk/deepseek';

// export async function POST() {
//   try {
//     const { text } = await generateText({
//       model: deepseek('deepseek-v4-flash'),
//       prompt: 'Explain the concept of quantum entanglement.',
//     });
//     return Response.json({ text });
//   } catch (err) {
//     console.error('DeepSeek error:', err);
//     return Response.json({ error: String(err) }, { status: 500 });
//   }
// }
// ***********************************


// ********** streamText ************
import {
  streamText,
  UIMessage,
  convertToModelMessages,
  createUIMessageStreamResponse,
  toUIMessageStream,
} from 'ai'
import { deepseek } from '@ai-sdk/deepseek';

export async function POST(req: Request) {
  try {
    const { messages }: { messages: UIMessage[] } = await req.json();

      const result = streamText({
        model: deepseek("deepseek-v4-flash"),
        messages: await convertToModelMessages(messages),
      });

      return createUIMessageStreamResponse({
        stream: toUIMessageStream({ stream: result.stream }),
      });
  } catch (err) {
    console.error('DeepSeek error:', err);
  }
}
// ***********************************
