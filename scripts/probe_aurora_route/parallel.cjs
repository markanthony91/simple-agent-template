const assert = require("node:assert/strict");
const env = process.env;
const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
async function main() {
  const scope = 7;
  const catalog = await fetch(
    env.CHANNEL_CONSOLE_URL.replace(/\/$/, "") +
      "/api/playground/v1/portfolios",
    {
      headers: { Authorization: "Bearer " + env.PLAYGROUND_API_TOKEN },
      signal: AbortSignal.timeout(10000),
    },
  );
  assert(catalog.ok);
  const portfolio = (await catalog.json()).portfolios.find(
    (p) => p.scope_id === scope,
  );
  assert.equal(portfolio.portfolio_name, "Homologação RAW");
  const aid = portfolio.runtime_assistant_id;
  assert(uuid.test(aid));
  const base = env.HOMOLOGATION_LANGGRAPH_API_URL.replace(/\/$/, "");
  async function request(path, data) {
    const r = await fetch(base + path, {
      method: data ? "POST" : "GET",
      headers: {
        "X-Api-Key": env.HOMOLOGATION_LANGGRAPH_API_KEY,
        "Content-Type": "application/json",
      },
      ...(data ? { body: JSON.stringify(data) } : {}),
      signal: AbortSignal.timeout(data ? 180000 : 10000),
    });
    assert(r.ok, "http_" + r.status);
    return r;
  }
  const a = await (await request("/assistants/" + aid)).json();
  assert.equal(a.graph_id, "agent");
  assert.equal(a.assistant_id, aid);
  assert.equal(String(a.context.portfolio_context.scope_id), "7");
  const meta = { assistant_id: aid, zerai_scope_id: "7" };
  const out = {
    at: new Date().toISOString(),
    scope,
    assistant: aid,
    graph: a.graph_id,
    mode: MODE,
  };
  if (MODE === "preflight") return out;
  assert.equal(MODE, "canary");
  const sessions = [];
  for (let i = 0; i < 4; i++) {
    const t = await (await request("/threads", { metadata: meta })).json();
    assert(uuid.test(t.thread_id));
    assert.equal(t.metadata.assistant_id, aid);
    assert.equal(t.metadata.zerai_scope_id, "7");
    sessions.push(t.thread_id);
  }
  assert.equal(new Set(sessions).size, 4);
  const baseline = performance.now();
  async function turn(thread) {
    const started = performance.now();
    const row = {
      thread,
      start_offset_ms: Math.round(started - baseline),
      first_text_ms: null,
      run: null,
      tools: [],
      status: "incomplete",
    };
    const elapsed = () => Math.round(performance.now() - started);
    try {
      const r = await request("/threads/" + thread + "/runs/stream", {
        assistant_id: aid,
        input: {
          messages: [
            {
              type: "human",
              content:
                "Olá! Pode me cumprimentar em uma frase? Estou apenas testando a saudação.",
            },
          ],
        },
        metadata: meta,
        stream_mode: ["messages-tuple", "values"],
      });
      row.run = r.headers.get("x-run-id");
      assert(uuid.test(row.run));
      assert(r.headers.get("content-type")?.includes("text/event-stream"));
      let buffer = "",
        finalText = false,
        streamError = false;
      const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += value;
        let sep;
        while ((sep = /\r?\n\r?\n/.exec(buffer))) {
          const event = buffer.slice(0, sep.index);
          buffer = buffer.slice(sep.index + sep[0].length);
          const kind = /^event: (\w+)/m.exec(event)?.[1];
          if (!["messages", "values", "error"].includes(kind)) continue;
          const payload = JSON.parse(
            event
              .split(/\r?\n/)
              .filter((l) => l.startsWith("data: "))
              .map((l) => l.slice(6))
              .join("\n"),
          );
          if (
            kind === "messages" &&
            payload[0]?.type === "ai" &&
            payload[0]?.content?.trim() &&
            row.first_text_ms === null
          )
            row.first_text_ms = elapsed();
          if (kind === "error") streamError = true;
          if (kind === "values") {
            const msgs = payload.messages ?? [];
            row.tools = msgs
              .filter((m) => m.type === "tool")
              .map((m) => m.name);
            const last = msgs.at(-1);
            finalText =
              last?.type === "ai" &&
              Boolean(last.content?.length) &&
              !last.tool_calls?.length;
          }
        }
      }
      row.status =
        !streamError && finalText && row.first_text_ms !== null
          ? "ok"
          : "stream_incomplete";
    } catch (e) {
      row.status = e.name === "AssertionError" ? "unexpected_response" : e.name;
    }
    row.total_ms = elapsed();
    return row;
  }
  out.turns = await Promise.all(sessions.map(turn));
  return out;
}
main()
  .then((v) => console.log("SAFE " + JSON.stringify(v)))
  .catch((e) => {
    console.error("safe_error " + e.name);
    process.exitCode = 1;
  });
