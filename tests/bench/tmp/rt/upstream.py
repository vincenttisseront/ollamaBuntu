"""Fausse instance Ollama : indique quel port a servi la requête, diffuse en plusieurs morceaux."""
import http.server, json, sys, time
PORT = int(sys.argv[1])
class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def reply(self, code, obj):
        raw = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_HEAD(self): self.send_response(200); self.send_header("Content-Length", "0"); self.end_headers()
    def do_GET(self):
        if self.path == "/api/ps": return self.reply(200, {"models": [{"name": "charge-sur-%d" % PORT}]})
        self.reply(200, {"served_by": PORT, "path": self.path})
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n)
        d = json.loads(body or b"{}")
        if self.path in ("/api/chat", "/v1/chat/completions"):
            self.send_response(200); self.send_header("Content-Type", "application/x-ndjson"); self.send_header("Transfer-Encoding", "chunked"); self.end_headers()
            for i in range(5):
                line = (json.dumps({"served_by": PORT, "model": d.get("model"), "i": i, "t": time.time()}) + "\n").encode()
                self.wfile.write(b"%x\r\n%s\r\n" % (len(line), line)); self.wfile.flush(); time.sleep(0.3)
            self.wfile.write(b"0\r\n\r\n"); return
        self.reply(200, {"served_by": PORT, "path": self.path, "received": len(body)})
H.do_DELETE = H.do_POST
http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
