"""Loopback-only OpenAI protocol fixture. NOT a real LLM or agent implementation."""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

PATH = "INSTITUTIONS/fastpay/policy.md"


def decide(messages):
    last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
    raw = messages[last_user]["content"]
    query = raw if isinstance(raw, str) else " ".join(x.get("text", "") for x in raw)
    results = [m for m in messages[last_user + 1 :] if m["role"] == "tool"]
    if "LONG" in query:
        return (
            "STREAM_START " + "Synthetic explanatory text. " * 60 + "STREAM_END",
            None,
        )
    if "CANCEL" in query:
        return ("CANCEL_START " + "Waiting for cancellation. " * 200, None)
    if "ERROR" in query:
        return ("ERROR_START partial response ", "disconnect")
    if "CONFIRMAR ACORDO " in query:
        if not results:
            return None, (
                "create_agreement",
                {"offer_id": query.split()[-1], "explicit_confirmation": True},
            )
        return "Agreement confirmed." if json.loads(results[-1]["content"]).get(
            "created"
        ) else "Agreement refused.", None
    if "VERIFY" in query:
        if not results:
            return None, (
                "verify_customer_identity",
                {"cpf": "12345678900", "full_name": "João da Silva"},
            )
        return "Identity verified.", None
    if "DEBT" in query:
        if not results:
            return None, ("get_customer", {"cpf": "12345678900"})
        data = json.loads(results[-1]["content"])
        return (
            "Debt total " + data["debt"]["current_amount"]
        ) if "debt" in data else "Identity verification required. Debt withheld.", None
    if "OFFER" in query:
        if not results:
            return None, ("okf_read", {"path": PATH})
        if len(results) == 1:
            return None, (
                "generate_offer",
                {"payment_type": "installment", "installments": 3, "policy_path": PATH},
            )
        return "Review the simulated offer and confirm using its button.", None
    if "POLICY" in query:
        if not results:
            return None, ("okf_index", {})
        if len(results) == 1:
            return None, ("okf_read", {"path": PATH})
        return "Synthetic policy consulted. Policy source: " + PATH, None
    return "This subject is outside the synthetic documents.", None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    cancellations = 0

    def log_message(self, *_):
        pass  # No prompts or credentials in logs.

    def do_GET(self):
        body = json.dumps({"data": [{"id": "synthetic-protocol"}], "cancellations": Handler.cancellations}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        text, call = decide(request["messages"])
        completion_id = "chatcmpl-" + uuid4().hex
        tool = None
        if isinstance(call, tuple):
            tool = {
                "index": 0,
                "id": "call_" + uuid4().hex,
                "type": "function",
                "function": {"name": call[0], "arguments": json.dumps(call[1])},
            }
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def emit(delta, finish=None):
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "synthetic-protocol",
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.flush()

        try:
            emit({"role": "assistant", "content": ""})
            if tool:
                emit({"tool_calls": [tool]})
            else:
                for offset in range(0, len(text), 30):
                    emit({"content": text[offset : offset + 30]})
                    time.sleep(0.05)
            if call == "disconnect":
                return
            emit({}, "tool_calls" if tool else "stop")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            Handler.cancellations += 1
            print("provider_cancelled", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 3042), Handler).serve_forever()
