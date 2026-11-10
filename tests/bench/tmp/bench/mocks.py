"""Faux OSV (18099), faux registre Ollama (18098), fausse Open WebUI (3000)."""
import json, hashlib, threading, http.server, sys
def J(o): return json.dumps(o).encode()
ECO = "Ubuntu:24.04:LTS"
def vuln(i, src, fixed, sev=None, nested=None):
    v = {"id": i, "summary": "Avis de test " + i, "affected": [{"package": {"name": src, "ecosystem": ECO}, "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": fixed}]}]}]}
    if sev: v["severity"] = [{"type": "Ubuntu", "score": sev}]
    if nested: v["affected"][0]["database_specific"] = {"cves_map": {"ecosystem": ECO, "cves": [{"id": "CVE-2026-9", "severity": [{"type": "Ubuntu", "score": nested}]}]}}
    return v
OSV = {"openssl": [vuln("USN-9001-1", "openssl", "3.0.13-0ubuntu3.16", "high"), vuln("UBUNTU-CVE-2026-0001", "openssl", "3.0.13-0ubuntu3.17", "critical")],
       "glibc": [vuln("USN-9002-1", "glibc", "2.39-0ubuntu8.9", nested="medium")],
       "openssh": [vuln("USN-9003-1", "openssh", "1:9.6p1-3ubuntu13.20")]}
QUERIES = []
class Osv(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        q = json.loads(self.rfile.read(int(self.headers["Content-Length"]))); QUERIES.append(q["package"]["name"])
        body = J({"vulns": OSV.get(q["package"]["name"], [])}); self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
# --- registre
BLOBS = {}
def blob(obj):
    raw = J(obj); d = "sha256:" + hashlib.sha256(raw).hexdigest(); BLOBS[d] = raw; return d, len(raw)
def manifest(size, model_type, quant, extra_layers=(), requires=None):
    cfg = {"model_format": "gguf", "model_family": "test", "model_type": model_type, "file_type": quant}
    if requires: cfg["requires"] = requires
    cd, cs = blob(cfg)
    layers = [{"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:" + hashlib.sha256(model_type.encode() + quant.encode()).hexdigest(), "size": size}]
    layers += [{"mediaType": "application/vnd.ollama.image." + k, "digest": "sha256:" + hashlib.sha256((model_type + k).encode()).hexdigest(), "size": s} for k, s in extra_layers]
    return J({"schemaVersion": 2, "mediaType": "application/vnd.docker.distribution.manifest.v2+json", "config": {"mediaType": "application/vnd.docker.container.image.v1+json", "digest": cd, "size": cs}, "layers": layers})
MAN = {
 "library/llama3.2:3b": manifest(2_019_000_000, "3.2B", "Q4_K_M", [("template", 1400), ("license", 7700)]),
 "library/gpt-oss:20b": manifest(13_000_000_000, "20.9B", "MXFP4"),
 "library/llama3.3:70b": manifest(43_000_000_000, "70.6B", "Q4_K_M"),
 "library/gpt-oss:120b": manifest(65_000_000_000, "116.8B", "MXFP4"),
 "library/nomic-embed-text:latest": manifest(274_000_000, "137M", "F16"),
 "library/qwen3.8:27b": manifest(17_000_000_000, "27B", "Q4_K_M", requires="99.0.0"),
 "library/devstral-small-2:latest": manifest(15_000_000_000, "24B", "Q4_K_M", [("projector", 800_000_000)]),
}
gg = manifest(7_200_000_000, "11.9B", "Q4_K_M", [("projector", 850_000_000), ("draft", 300_000_000)])
ggd = "sha256:" + hashlib.sha256(gg).hexdigest(); MAN["library/gemma4:" + ggd] = gg
MAN["library/gemma4:12b"] = J({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [
    {"mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": "sha256:" + "f" * 64, "size": 1, "annotations": {"runner": "mlx", "format": "safetensors"}},
    {"mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": ggd, "size": len(gg), "annotations": {"runner": "llamacpp", "format": "gguf"}}]})
class Reg(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        p = self.path.split("/")      # /v2/<ns>/<model>/manifests/<ref>
        body = None
        if len(p) >= 6 and p[4] == "manifests":
            body = MAN.get("%s/%s:%s" % (p[2], p[3], p[5]))
        elif len(p) >= 6 and p[4] == "blobs":
            body = BLOBS.get(p[5])
        if body is None:
            body = J({"errors": [{"code": "MANIFEST_UNKNOWN"}]}); self.send_response(404)
        else: self.send_response(200)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
class WebUI(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = J({"status": True}) if self.path == "/health" else J({"version": "0.13.0"}) if self.path == "/api/version" else ("<html>Open WebUI factice " + self.path + " " + "x" * 200000 + "</html>").encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
def serve(port, h): threading.Thread(target=http.server.ThreadingHTTPServer(("127.0.0.1", port), h).serve_forever, daemon=True).start()
if __name__ == "__main__":
    serve(18099, Osv); serve(18098, Reg)
    if "--webui" in sys.argv: serve(3000, WebUI)
    # le manifeste local de qwen3.5:2b est publié tel quel par le registre (cas « à jour »)
    import os, glob, time
    while True:
        for f in glob.glob("/tmp/target/usr/share/ollama/.ollama/models/manifests-v2/ollama.com/library/qwen3.5/2b"):
            MAN["library/qwen3.5:2b"] = open(f, "rb").read()
        open("/tmp/bench/osv-queries.json", "w").write(json.dumps(QUERIES))
        time.sleep(1)
