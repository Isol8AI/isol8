import { http, HttpResponse } from 'msw';

const API_BASE = 'http://localhost:8000/api/v1';
const ONE_DAY_MS = 86400000;

export const handlers = [
  http.get(`${API_BASE}/chat/models`, () => {
    return HttpResponse.json([
      { id: 'Qwen/Qwen2.5-72B-Instruct', name: 'Qwen 2.5 72B' },
      { id: 'meta-llama/Llama-3.3-70B-Instruct', name: 'Llama 3.3 70B' },
      { id: 'google/gemma-2-9b-it', name: 'Gemma 2 9B' },
      { id: 'Qwen/Qwen2.5-7B-Instruct', name: 'Qwen 2.5 7B' },
    ]);
  }),

  http.post(`${API_BASE}/users/sync`, () => {
    return HttpResponse.json({
      status: 'exists',
      user_id: 'user_test_123',
    });
  }),

  http.get(`${API_BASE}/chat/sessions`, () => {
    const sessions = [
      {
        id: 'session_1',
        name: 'Test Conversation',
        created_at: new Date().toISOString(),
      },
      {
        id: 'session_2',
        name: 'Another Chat',
        created_at: new Date(Date.now() - ONE_DAY_MS).toISOString(),
      },
    ];
    // Return paginated response format
    return HttpResponse.json({
      sessions: sessions,
      total: sessions.length,
      limit: 50,
      offset: 0,
    });
  }),

  http.get(`${API_BASE}/chat/sessions/:sessionId/messages`, ({ params }) => {
    if (params.sessionId === 'session_1') {
      return HttpResponse.json([
        {
          id: 'msg_1',
          role: 'user',
          content: 'Hello!',
          timestamp: new Date().toISOString(),
        },
        {
          id: 'msg_2',
          role: 'assistant',
          content: 'Hi there! How can I help you today?',
          model_used: 'Qwen/Qwen2.5-72B-Instruct',
          timestamp: new Date().toISOString(),
        },
      ]);
    }
    return HttpResponse.json([]);
  }),

  http.post(`${API_BASE}/chat/stream`, () => {
    const encoder = new TextEncoder();
    const chunks = ['Hello', '! How ', 'can I ', 'help you', ' today?'];

    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode('data: {"type":"session","session_id":"session_new"}\n\n')
        );

        for (const chunk of chunks) {
          controller.enqueue(
            encoder.encode(`data: {"type":"content","content":"${chunk}"}\n\n`)
          );
        }

        controller.enqueue(encoder.encode('data: {"type":"done"}\n\n'));
        controller.close();
      },
    });

    return new HttpResponse(stream, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      },
    });
  }),
];
