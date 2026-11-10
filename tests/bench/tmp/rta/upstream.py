import http.server, json, sys, time
PORT = int(sys.argv[1])
MODELS = ["llama3.2:3b", "qwen3:32b", "mistral:latest"]
class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def reply(self, obj):
        raw = json.dumps(obj).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_HEAD(self): self.send_response(200); self.send_header("Content-Length", "0"); self.end_headers()
    def do_GET(self):
        if self.path == "/api/tags": return self.reply({"models": [{"name": m} for m in MODELS]})
        if self.path == "/v1/models": return self.reply({"object": "list", "data": [{"id": m} for m in MODELS]})
        if self.path == "/api/ps": return self.reply({"models": [{"name": m} for m in MODELS[:2]]})
        self.reply({"served_by": PORT, "path": self.path})
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n)
        if self.path == "/api/chat":
            self.send_response(200); self.send_header("Transfer-Encoding", "chunked"); self.end_headers()
            for i in range(3):
                line = (json.dumps({"served_by": PORT, "i": i, "auth_seen": "authorization" in {k.lower() for k in self.headers}}) + "\n").encode()
                self.wfile.write(b"%x\r\n%s\r\n" % (len(line), line)); self.wfile.flush(); time.sleep(0.2)
            self.wfile.write(b"0\r\n\r\n"); return
        self.reply({"served_by": PORT, "path": self.path, "auth_seen": "authorization" in {k.lower() for k in self.headers}})
    do_DELETE = do_POST
http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
