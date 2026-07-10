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
  isStepCount,
  tool,
} from 'ai'
import { z } from 'zod';
import { deepseek } from '@ai-sdk/deepseek';

export async function POST(req: Request) {
  try {
    const { messages }: { messages: UIMessage[] } = await req.json();

      const result = streamText({
        model: deepseek("deepseek-v4-flash"),
        messages: await convertToModelMessages(messages),
        stopWhen: isStepCount(5),
        tools: {
          weather: tool({
            description: 'Get the weather in a location (fahrenheit)',
            inputSchema: z.object({
              location: z.string().describe('The location to get the weather for'),
            }),
            execute: async ({ location }) => {
              const temperature = Math.round(Math.random() * (90 - 32) + 32);
              return {
                location,
                temperature,
              };
            },
          }),
          convertFahrenheitToCelsius: tool({
            description: 'Convert a temperature in fahrenheit to celsius',
            inputSchema: z.object({
              temperature: z
                .number()
                .describe('The temperature in fahrenheit to convert'),
            }),
            execute: async ({ temperature }) => {
              const celsius = Math.round((temperature - 32) * (5 / 9));
              return {
                celsius,
              };
            },
          }),
        },
      });

      return createUIMessageStreamResponse({
        stream: toUIMessageStream({ stream: result.stream }),
      });
  } catch (err) {
    console.error('DeepSeek error:', err);
  }
}
// ***********************************
