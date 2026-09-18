import assert from "node:assert/strict";
import { test } from "node:test";
import { createHash } from "node:crypto";
const bridgeToken = "synthetic-bridge";
const env = {
  LLM_BRIDGE_TOKEN_SHA256: createHash("sha256")
    .update(bridgeToken)
    .digest("hex"),
  LOVABLE_API_KEY: "synthetic-gateway",
  LLM_BRIDGE_MODELS: "google/gemini-test,openai/gpt-test",
};
globalThis.Deno = { env: { get: (name) => env[name] }, serve() {} };
const { handle } = await import("./index.ts");
const request = (payload, token = bridgeToken) =>
  new Request("https://bridge.invalid/v1/chat/completions", {
    method: "POST",
    headers: { authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  });
test("authenticated bridge preserves prompt, zero, tools, results and SSE; rejects unsafe inputs", async () => {
  const original = globalThis.fetch;
  const payload = {
    model: "google/gemini-test",
    messages: [
      { role: "system", content: "ONLY_THIS_PROMPT" },
      {
        role: "assistant",
        content: null,
        tool_calls: [
          {
            id: "once",
            type: "function",
            function: { name: "utc_now", arguments: "{}" },
          },
        ],
      },
      { role: "tool", tool_call_id: "once", content: "synthetic" },
    ],
    tools: [
      {
        type: "function",
        function: { name: "utc_now", parameters: { type: "object" } },
      },
    ],
    temperature: 0,
    stream: true,
  };
  let calls = 0;
  globalThis.fetch = async (url, options) => {
    calls++;
    assert.equal(url, "https://ai.gateway.lovable.dev/v1/chat/completions");
    assert.equal(options.headers.authorization, "Bearer synthetic-gateway");
    assert.deepEqual(JSON.parse(options.body), payload);
    return new Response("data: synthetic\n\ndata: [DONE]\n\n", {
      headers: { "content-type": "text/event-stream" },
    });
  };
  try {
    assert.equal((await handle(request(payload, "wrong"))).status, 401);
    assert.equal(
      (await handle(request(payload, env.LLM_BRIDGE_TOKEN_SHA256))).status,
      401,
    );
    const verifier = env.LLM_BRIDGE_TOKEN_SHA256;
    env.LLM_BRIDGE_TOKEN_SHA256 = "";
    assert.equal((await handle(request(payload))).status, 503);
    env.LLM_BRIDGE_TOKEN_SHA256 = verifier;
    assert.equal(
      (await handle(request({ ...payload, model: "arbitrary" }))).status,
      400,
    );
    assert.equal(
      (
        await handle(
          request({ ...payload, base_url: "https://attacker.invalid" }),
        )
      ).status,
      400,
    );
    assert.equal(
      (await handle(request({ ...payload, messages: ["x".repeat(1_048_577)] })))
        .status,
      413,
    );
    assert.equal(calls, 0);
    const response = await handle(request(payload));
    assert.equal(response.status, 200);
    assert.equal(await response.text(), "data: synthetic\n\ndata: [DONE]\n\n");
    assert.equal(calls, 1);
    for (const status of [400, 401, 429, 500]) {
      globalThis.fetch = async () =>
        new Response("private upstream error", { status });
      const result = await handle(request(payload));
      assert.equal(result.status, status);
      assert.ok(!(await result.text()).includes("private"));
    }
    globalThis.fetch = async () => {
      throw new Error("private");
    };
    assert.equal((await handle(request(payload))).status, 502);
  } finally {
    globalThis.fetch = original;
  }
});
