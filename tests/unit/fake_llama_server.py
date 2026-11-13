#!/usr/bin/env python3
"""Faux llama-server pour les essais : mêmes options, /health, /v1/chat/completions en JSON ou en flux SSE. Comportements par FAKE_MODE (variable d'environnement) :
crash (sort au démarrage), hang (jamais prêt), slow (prêt après 1,2 s) ; par le texte de la demande : ERREUR (400), MEURS (sort en pleine réponse), LENT (flux lent), ATTENDS (0,4 s)."""
import json, os, sys, threading, time, http.server
HELP = """-fa, --flash-attn [on|off|auto]  Flash Attention
-c, --ctx-size N
-ngl, --n-gpu-layers N
-np, --parallel N
--n-cpu-moe N
--override-tensor <p>
--cache-type-k TYPE
--jinja
--no-webui
-t, --threads N"""
LOG = os.environ.get("FAKE_LOG", "")
MODE = os.environ.get("FAKE_MODE", "")
def log(kind, **kw):
    if LOG:
        with open(LOG, "a") as f:
            f.write(json.dumps(dict(kind=kind, t=time.time(), **kw)) + "\n")
if "--help" in sys.argv:
    print(HELP); sys.exit(0)
args = sys.argv[1:]
port = int(args[args.index("--port") + 1])
log("start", args=args, pid=os.getpid(), ld=os.environ.get("LD_LIBRARY_PATH", ""))
if MODE == "crash":
    print("error: failed to load model boom", file=sys.stderr, flush=True); sys.exit(3)
T0 = time.time()
class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_GET(self):
        ready = MODE != "hang" and time.time() - T0 > (1.2 if MODE == "slow" else 0.0)
        raw = json.dumps({"status": "ok"} if ready else {"error": {"message": "Loading model"}}).encode()
        self.send_response(200 if ready else 503); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        log("request", path=self.path, body=body)
        text = " ".join(str(m.get("content")) for m in body.get("messages", []))
        if "ERREUR" in text:
            raw = json.dumps({"error": {"code": 400, "message": "the request exceeds the available context size", "type": "exceed_context_size_error"}}).encode()
            self.send_response(400); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        if "ATTENDS" in text: time.sleep(0.4)
        if "MEURS" in text:
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"par"}}]}\n\n'); self.wfile.flush(); time.sleep(0.1); os._exit(1)
        timings = {"prompt_n": 7, "prompt_ms": 12.5, "predicted_n": 2, "predicted_ms": 25.0}
        if not body.get("stream"):
            raw = json.dumps({"choices": [{"message": {"role": "assistant", "content": "Bonjour"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 7, "completion_tokens": 2}, "timings": timings}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Transfer-Encoding", "chunked"); self.end_headers()
        def chunk(b):
            self.wfile.write(("%x\r\n" % len(b)).encode() + b + b"\r\n"); self.wfile.flush()
        try:
            pieces = ["Bon", "jour"] if "LENT" not in text else ["x"] * 200
            for p in pieces:
                chunk(b"data: " + json.dumps({"choices": [{"delta": {"content": p}}]}).encode() + b"\n\n")
                if "LENT" in text: time.sleep(0.05)
            chunk(b"data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}).encode() + b"\n\n")
            chunk(b"data: " + json.dumps({"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2}, "timings": timings}).encode() + b"\n\n")
            chunk(b"data: [DONE]\n\n"); self.wfile.write(b"0\r\n\r\n")
        except (BrokenPipeError, ConnectionResetError):
            log("aborted")
srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H); srv.daemon_threads = True
try: srv.serve_forever()
except KeyboardInterrupt: pass
