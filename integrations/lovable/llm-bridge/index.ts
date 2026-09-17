// Dedicated server-to-server bridge: no prompts, business rules or tool execution.
import { timingSafeEqual } from "node:crypto";

const error = (status: number, message: string) =>
  Response.json({ error: { message, type: "bridge_error" } }, { status });

export async function handle(request: Request): Promise<Response> {
  if (request.method !== "POST") return error(405, "POST required");
  const token = Deno.env.get("LLM_BRIDGE_TOKEN");
  const key = Deno.env.get("LOVABLE_API_KEY");
  const models = (Deno.env.get("LLM_BRIDGE_MODELS") || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
  if (!token || !key || !models.length)
    return error(503, "Bridge not configured");
  const expected = new TextEncoder().encode(`Bearer ${token}`);
  const received = new TextEncoder().encode(
    request.headers.get("authorization") || "",
  );
  if (
    expected.length !== received.length ||
    !timingSafeEqual(expected, received)
  )
    return error(401, "Unauthorized");
  // A body cap prevents this endpoint from buffering arbitrary uploads.
  const reader = request.body?.getReader();
  if (!reader) return error(400, "Missing body");
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > 1_048_576) {
      await reader.cancel();
      return error(413, "Body too large");
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  let payload;
  try {
    payload = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return error(400, "Invalid JSON");
  }
  if (
    !payload ||
    !models.includes(payload.model) ||
    !Array.isArray(payload.messages)
  )
    return error(400, "Invalid model or messages");
  const allowed = new Set([
    "model",
    "messages",
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "stream",
    "stream_options",
  ]);
  if (Object.keys(payload).some((key) => !allowed.has(key)))
    return error(400, "Unsupported parameter");
  try {
    const upstream = await fetch(
      "https://ai.gateway.lovable.dev/v1/chat/completions",
      {
        method: "POST",
        headers: {
          authorization: `Bearer ${key}`,
          "content-type": "application/json",
        },
        body: JSON.stringify(payload),
        signal: AbortSignal.any([request.signal, AbortSignal.timeout(120_000)]),
      },
    );
    if (!upstream.ok) {
      await upstream.body?.cancel();
      return error(upstream.status, "LLM provider rejected the request");
    }
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "content-type":
          upstream.headers.get("content-type") || "text/event-stream",
        "cache-control": "no-store",
      },
    });
  } catch {
    return error(request.signal.aborted ? 499 : 502, "LLM connection failed");
  }
}

Deno.serve(handle);
