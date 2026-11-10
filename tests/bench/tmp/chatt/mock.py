import http.server, json, time
LAST = {}
class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_GET(self):
        raw = json.dumps({"last": LAST.get("body")}).encode(); self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}"); LAST["body"] = body
        self.send_response(200); self.send_header("Content-Type", "application/x-ndjson"); self.send_header("Transfer-Encoding", "chunked"); self.end_headers()
        def send(obj, pause=0.25):
            line = (json.dumps(obj) + "\n").encode(); self.wfile.write(b"%x\r\n%s\r\n" % (len(line), line)); self.wfile.flush(); time.sleep(pause)
        m = body.get("model")
        if m == "think-sep":
            for w in ["L'utilisateur ", "demande ", "la capitale. ", "Je réponds ", "brièvement."]: send({"message": {"role": "assistant", "content": "", "thinking": w}}, 0.5)
            for w in ["La capitale ", "de la France ", "est **Paris**."]: send({"message": {"role": "assistant", "content": w}})
        elif m == "think-tags":
            for w in ["<think>", "Calcul : ", "2 + 2 ", "= 4.", "</think>", "\n\n", "Le résultat ", "est **4**."]: send({"message": {"role": "assistant", "content": w}}, 0.4)
        else:
            for w in ["Bonjour ", "!"]: send({"message": {"role": "assistant", "content": w}})
        send({"done": True, "eval_count": 10, "eval_duration": 1000000000, "message": {"role": "assistant", "content": ""}}, 0)
        self.wfile.write(b"0\r\n\r\n")
http.server.ThreadingHTTPServer(("127.0.0.1", 11999), H).serve_forever()
