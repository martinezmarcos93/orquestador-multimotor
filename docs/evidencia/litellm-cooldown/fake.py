import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
puerto, ok = int(sys.argv[1]), sys.argv[2] == "ok"
n = 0
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(json.dumps({"hits": n}).encode())
    def do_POST(self):
        global n
        n += 1
        self.rfile.read(int(self.headers.get("content-length", 0)))
        if not ok:
            self.send_response(500); self.end_headers(); self.wfile.write(b'{"error":{"message":"caido","type":"server_error"}}'); return
        body = {"id": "x", "object": "chat.completion", "created": 1, "model": "m",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "hola"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps(body).encode())
HTTPServer(("127.0.0.1", puerto), H).serve_forever()
