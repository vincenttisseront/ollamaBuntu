#!/usr/bin/env python3
"""OllamaBuntu - démon d'un moteur llama.cpp (ollamabuntu-llama@<id>.service).

Il se présente au routeur comme une instance Ollama : le routeur lui envoie les demandes du modèle qui lui est confié (table des moteurs,
/etc/ollamabuntu/engines.json), exactement comme il le fait pour un groupe de GPU. Le démon traduit /api/chat et /api/generate vers llama-server,
lancé À LA DEMANDE (la mémoire n'est prise que pendant l'usage) et arrêté après une période d'inactivité. Le modèle reste celui d'Ollama : son fichier est lu
sur place, sans copie.

Ce que le démon ne fait pas : images, embeddings, mode brut. Tout ce qu'il ne traite pas est relayé tel quel à Ollama, où le modèle est aussi installé.
Il n'écoute que sur 127.0.0.1 ; llama-server aussi (port interne distinct)."""
import collections
import http.client
import http.server
import json
import os
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llamacpp as L  # noqa: E402

ETC = os.environ.get("OB_ETC", "/etc/ollamabuntu")
MODELS_DIR = os.environ.get("OB_MODELS", "/usr/share/ollama/.ollama/models")
OLLAMA_MAIN = os.environ.get("OB_OLLAMA_MAIN", "127.0.0.1:11400")
ENGINES_FILE = os.path.join(ETC, "engines.json")
POOLS_FILE = os.path.join(ETC, "pools.json")
GLOBAL_FILE = os.path.join(ETC, "llama.json")
TICK = float(os.environ.get("OB_ENGINE_TICK", "2"))
RETRY_AFTER_ERROR = float(os.environ.get("OB_ENGINE_RETRY", "20"))
STOP_WAIT = float(os.environ.get("OB_ENGINE_STOP_WAIT", "20"))
IDLE_UNIT = float(os.environ.get("OB_ENGINE_IDLE_UNIT", "60"))   # secondes par « minute » d'inactivité (réduit dans les essais)
START_TIMEOUT = os.environ.get("OB_ENGINE_START_TIMEOUT")        # remplace le délai de démarrage des réglages (essais)


class EngineError(Exception):
    pass


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def say(msg):
    sys.stdout.write("moteur : %s\n" % msg)
    sys.stdout.flush()


def http_json(addr, method, path, body=None, timeout=10):
    host, _, port = addr.rpartition(":")
    c = http.client.HTTPConnection(host, int(port), timeout=timeout)
    try:
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers={"Content-Type": "application/json"})
        r = c.getresponse()
        raw = r.read()
        try:
            return r.status, json.loads(raw or b"{}")
        except ValueError:
            return r.status, {}
    finally:
        c.close()


def ollama_addrs():
    return [OLLAMA_MAIN] + ["127.0.0.1:%d" % int(p["port"]) for p in load_json(POOLS_FILE, {}).get("pools", []) if str(p.get("port", "")).isdigit()]


def unload_ollama(wait=20.0):
    """Décharge les modèles d'Ollama pour libérer la mémoire vidéo avant de lancer llama-server (qui compte dessus)."""
    pending = []
    for addr in ollama_addrs():
        try:
            st, d = http_json(addr, "GET", "/api/ps", timeout=5)
        except OSError:
            continue
        for m in (d.get("models") or []) if st == 200 else []:
            name = m.get("name") or m.get("model")
            if name:
                try:
                    http_json(addr, "POST", "/api/generate", {"model": name, "keep_alive": 0}, timeout=30)
                    pending.append((addr, name))
                except OSError:
                    pass
    t_end = time.time() + wait
    while pending and time.time() < t_end:
        still = []
        for addr, name in pending:
            try:
                st, d = http_json(addr, "GET", "/api/ps", timeout=5)
            except OSError:
                continue
            if any((m.get("name") or m.get("model")) == name for m in d.get("models") or []):
                still.append((addr, name))
        pending = still
        if pending:
            time.sleep(0.5)
    if pending:
        say("modèles encore chargés dans Ollama après %d s : %s" % (wait, ", ".join(n for _, n in pending)))
    return not pending


class Engine:
    def __init__(self, eid):
        self.id = eid
        self.cond = threading.Condition()
        self.state = "stopped"      # stopped | starting | ready | stopping | error
        self.proc = None
        self.tail = collections.deque(maxlen=80)
        self.error = ""
        self.error_until = 0.0
        self.started = None
        self.last_used = time.time()
        self.inflight = 0
        self.requests = 0
        self.spec_drafted = self.spec_accepted = 0   # jetons proposés / acceptés par le brouillon depuis le démarrage de llama-server
        self.failures = 0
        self.cancel = False
        self.start_gen = 0          # numéro du démarrage en cours (ou du dernier)
        self.cancelled_gen = -1     # numéro du dernier démarrage annulé par un arrêt
        self.start_s = 0.0
        self.args, self.warnings, self.caps, self.gguf, self.binary = [], [], {}, "", ""
        self._caps_key = None
        self.sem = None
        self.sem_n = 0

    # ---------------------------------------------------------------- réglages
    def cfg(self):
        """Réglages de CE moteur : son entrée de engines.json, la même table que lit le routeur (une seule source, incluse dans la sauvegarde)."""
        raw = next((e for e in load_json(ENGINES_FILE, {}).get("engines", []) if isinstance(e, dict) and e.get("id") == self.id), None)
        if raw is None:
            raise EngineError("réglages du moteur « %s » introuvables" % self.id)
        try:
            return L.config_clean(raw)
        except ValueError as e:
            raise EngineError("réglages du moteur invalides : %s" % e)

    def binary_path(self):
        b = os.environ.get("OB_LLAMA_BINARY") or load_json(GLOBAL_FILE, {}).get("binary") or ""
        if not b or not os.path.isfile(b) or not os.access(b, os.X_OK):
            raise EngineError("le moteur llama.cpp n'est pas installé (Modèles > Moteur MoE > Installer)")
        return b

    def caps_for(self, binary):
        try:
            key = (binary, os.path.getmtime(binary))
        except OSError:
            key = (binary, 0)
        if key != self._caps_key:
            env = dict(os.environ, LD_LIBRARY_PATH=os.path.dirname(binary) + os.pathsep + os.environ.get("LD_LIBRARY_PATH", ""))
            try:
                r = subprocess.run([binary, "--help"], capture_output=True, text=True, timeout=30, env=env, cwd=os.path.dirname(binary))
                text = (r.stdout or "") + (r.stderr or "")
            except (OSError, subprocess.SubprocessError) as e:
                raise EngineError("llama-server ne démarre pas (%s)" % e)
            self.caps, self._caps_key = L.detect_caps(text), key
        return self.caps

    def slots(self, parallel):
        if self.sem is None or self.sem_n != parallel:
            self.sem, self.sem_n = threading.BoundedSemaphore(parallel), parallel
        return self.sem

    # ---------------------------------------------------------------- démarrage et arrêt
    def ensure_ready(self):
        """Attend que llama-server réponde (le lance si besoin). Retourne les secondes passées à attendre (0 s s'il tournait déjà)."""
        t0 = time.time()
        stopping_since = None
        gen = None
        with self.cond:
            while True:
                if gen is not None and self.state == "stopped" and self.cancelled_gen == gen:
                    raise EngineError("démarrage annulé par un arrêt du moteur")
                if self.state == "ready":
                    if self.proc is not None and self.proc.poll() is None:
                        return time.time() - t0
                    self._dead_locked("llama-server s'est arrêté")
                if self.state in ("stopped", "error"):
                    if self.state == "error" and time.time() < self.error_until:
                        raise EngineError(self.error)   # échec récent : pas de nouvelle tentative immédiate (la cause n'a pas changé)
                    self.state, self.error, self.cancel = "starting", "", False
                    self.start_gen += 1
                    threading.Thread(target=self._start, args=(self.start_gen,), daemon=True, name="start").start()
                if self.state == "starting" and gen is None:
                    gen = self.start_gen
                if self.state == "error":
                    raise EngineError(self.error)
                if self.state == "stopping":
                    stopping_since = stopping_since or time.time()
                    if time.time() - stopping_since > 60:
                        raise EngineError("l'arrêt du moteur précédent est trop long")
                self.cond.wait(0.5)   # « starting » : _start borne lui-même la durée (délai de démarrage)

    def _dead_locked(self, why):
        code = self.proc.poll() if self.proc is not None else None
        say("%s (code %s)" % (why, code))
        self.state, self.proc, self.started = "stopped", None, None
        self.failures += 1
        self.cond.notify_all()

    def _fail(self, msg):
        with self.cond:
            self.state, self.error, self.error_until, self.proc = "error", msg, time.time() + RETRY_AFTER_ERROR, None
            self.failures += 1
            self.cond.notify_all()
        say("échec du démarrage : %s" % msg)

    def _start(self, gen):
        t0 = time.time()
        proc = None
        try:
            cfg = self.cfg()
            binary = self.binary_path()
            gguf, err = L.find_gguf(MODELS_DIR, cfg["model"])
            if err:
                raise EngineError(err)
            if not os.path.isfile(gguf):
                raise EngineError("fichier du modèle introuvable (%s) : réinstallez le modèle dans Ollama" % os.path.basename(gguf))
            if cfg.get("unload_ollama"):
                unload_ollama()
            self.stop_others()
            caps = self.caps_for(binary)
            draft = None
            if cfg.get("spec") == "draft":
                draft, derr = L.find_gguf(MODELS_DIR, cfg.get("draft_model") or "")
                if derr or not os.path.isfile(draft or ""):
                    raise EngineError("modèle brouillon : %s" % (derr or "fichier introuvable : réinstallez-le dans Ollama"))
            args, warns = L.build_args(cfg, caps, binary, gguf, draft_gguf=draft)
            self.spec_drafted = self.spec_accepted = 0
            self.args, self.warnings, self.gguf, self.binary = args, warns, gguf, binary
            for w in warns:
                say("avertissement : " + w)
            env = dict(os.environ, LD_LIBRARY_PATH=os.path.dirname(binary) + os.pathsep + os.environ.get("LD_LIBRARY_PATH", ""))
            self.tail.clear()
            say("démarrage de llama-server : %s" % " ".join(args[1:]))
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=os.path.dirname(binary), text=True, errors="replace")
            threading.Thread(target=self._pump, args=(proc,), daemon=True, name="pump").start()
            bport = cfg["backend_port"]
            while True:
                if self.cancel:
                    self._kill(proc)
                    with self.cond:
                        self.state, self.proc, self.cancelled_gen = "stopped", None, gen
                        self.cond.notify_all()
                    return
                code = proc.poll()
                if code is not None:
                    time.sleep(0.2)   # laisse le lecteur vider la sortie
                    last = [x for x in list(self.tail)[-6:] if x.strip()]
                    raise EngineError("llama-server s'est arrêté au démarrage (code %s) : %s" % (code, " / ".join(last)[-500:] or "aucun message"))
                try:
                    st, _ = http_json("127.0.0.1:%d" % bport, "GET", "/health", timeout=3)
                    if st == 200:
                        break
                except OSError:
                    pass
                limit = float(START_TIMEOUT or cfg["start_timeout"])
                if time.time() - t0 > limit:
                    self._kill(proc)
                    raise EngineError("llama-server n'est pas prêt après %d s (modèle trop long à charger ?)" % limit)
                time.sleep(0.4)
            with self.cond:
                self.state, self.proc, self.started, self.start_s = "ready", proc, time.time(), time.time() - t0
                self.last_used = time.time()
                self.cond.notify_all()
            say("prêt en %.1f s" % self.start_s)
        except EngineError as e:
            if proc is not None and proc.poll() is None:
                self._kill(proc)
            self._fail(str(e))
        except Exception as e:   # le démon ne doit jamais rester bloqué en « starting »
            if proc is not None and proc.poll() is None:
                self._kill(proc)
            self._fail("erreur inattendue : %s" % e)

    def _pump(self, proc):
        for line in proc.stdout:
            line = line.rstrip("\n")
            self.tail.append(line)
            sys.stdout.write("[llama-server] %s\n" % line)
            sys.stdout.flush()

    @staticmethod
    def _kill(proc):
        try:
            proc.terminate()
            try:
                proc.wait(STOP_WAIT)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(5)
        except OSError:
            pass

    def stop(self, why="demandé"):
        with self.cond:
            if self.state == "starting":
                self.cancel = True
                return True
            if self.state != "ready" or self.proc is None:
                return False
            self.state = "stopping"
            proc = self.proc
        say("arrêt de llama-server (%s)" % why)
        self._kill(proc)
        with self.cond:
            self.state, self.proc, self.started = "stopped", None, None
            self.cond.notify_all()
        return True

    def stop_others(self):
        """Un seul moteur à la fois par défaut : ils se disputeraient la mémoire vidéo."""
        d = load_json(ENGINES_FILE, {})
        if d.get("exclusive") is False:
            return
        for e in d.get("engines", []):
            if e.get("id") != self.id and str(e.get("port", "")).isdigit():
                try:
                    http_json("127.0.0.1:%d" % int(e["port"]), "POST", "/engine/stop", {}, timeout=40)
                except OSError:
                    pass

    def watch(self):
        """Arrêt après inactivité ; constat d'un llama-server tombé en marche."""
        while True:
            time.sleep(TICK)
            try:
                cfg = self.cfg()
            except EngineError:
                continue
            with self.cond:
                if self.state == "ready" and self.proc is not None and self.proc.poll() is not None:
                    self._dead_locked("llama-server s'est arrêté pendant l'usage")
                idle = time.time() - self.last_used
                due = self.state == "ready" and self.inflight == 0 and cfg["idle_min"] > 0 and idle > cfg["idle_min"] * IDLE_UNIT
            if due:
                self.stop("inactif depuis %d min" % (idle // IDLE_UNIT))

    def status(self):
        with self.cond:
            running = self.state == "ready" and self.proc is not None and self.proc.poll() is None
            return {"id": self.id, "state": self.state, "pid": self.proc.pid if running else None, "uptime": int(time.time() - self.started) if running and self.started else 0,
                    "idle": int(time.time() - self.last_used), "inflight": self.inflight, "requests": self.requests, "failures": self.failures, "error": self.error,
                    "start_seconds": round(self.start_s, 1), "spec": {"drafted": self.spec_drafted, "accepted": self.spec_accepted}, "gguf": self.gguf, "binary": self.binary, "args": self.args[1:] if self.args else [], "warnings": self.warnings,
                    "caps": self.caps, "tail": list(self.tail)[-25:]}

    def enter(self):
        with self.cond:
            self.inflight += 1
            self.requests += 1
            self.last_used = time.time()

    def note_spec(self, timings):
        """Compte les jetons proposés et acceptés par le brouillon (ce que llama-server indique dans les durées d'une réponse)."""
        n, ok = L.spec_counts(timings)
        if n:
            with self.cond:
                self.spec_drafted += n
                self.spec_accepted += ok

    def leave(self):
        with self.cond:
            self.inflight -= 1
            self.last_used = time.time()


ENGINE = None


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "OllamaBuntu-engine"
    sys_version = ""
    protocol_version = "HTTP/1.0"   # fin de réponse = fermeture : le flux passe tel quel
    timeout = 3600

    def log_message(self, fmt, *args):
        pass

    # ------------------------------------------------ utilitaires
    def reply(self, code, obj, ctype="application/json; charset=utf-8"):
        raw = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 64 * 1024 * 1024:
            raise ValueError("requête trop volumineuse")
        return self.rfile.read(n) if n else b""

    def relay_ollama(self, method, raw):
        """Tout ce que le moteur ne traite pas est relayé à Ollama (le modèle y est aussi installé)."""
        host, _, port = OLLAMA_MAIN.rpartition(":")
        c = http.client.HTTPConnection(host, int(port), timeout=3600)
        try:
            hdrs = {"Content-Type": self.headers.get("Content-Type", "application/json")}
            c.request(method, self.path, body=raw or None, headers=hdrs)
            r = c.getresponse()
            self.send_response(r.status)
            for k, v in r.getheaders():
                if k.lower() in ("content-type", "content-length"):
                    self.send_header(k, v)
            self.end_headers()
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except OSError as e:
            self.reply(502, {"error": "Ollama injoignable : %s" % e})
        finally:
            c.close()

    # ------------------------------------------------ routes
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/engine/status":
            return self.reply(200, ENGINE.status())
        if path == "/api/version":
            return self.reply(200, {"version": "llama.cpp (moteur OllamaBuntu)"})
        if path == "/api/ps":
            return self.reply(200, self.ps())
        self.relay_ollama("GET", b"")

    def ps(self):
        st = ENGINE.status()
        if st["state"] != "ready":
            return {"models": []}
        cfg = ENGINE.cfg()
        size = os.path.getsize(st["gguf"]) if st["gguf"] and os.path.exists(st["gguf"]) else 0
        cpu = int(cfg.get("cpu_bytes") or 0)
        return {"models": [{"name": cfg["model"], "model": cfg["model"], "size": size, "size_vram": max(0, size - cpu), "digest": "", "engine": "llama.cpp",
                            "details": {"format": "gguf", "family": "llama.cpp"}, "expires_at": ""}]}

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            raw = self.body()
        except (ValueError, OSError) as e:
            return self.reply(400, {"error": str(e)})
        if path == "/engine/start":
            try:
                ENGINE.ensure_ready()
                return self.reply(200, {"ok": True, "state": ENGINE.status()["state"]})
            except EngineError as e:
                return self.reply(503, {"error": str(e)})
        if path == "/engine/stop":
            return self.reply(200, {"ok": True, "stopped": ENGINE.stop("demandé")})
        if path == "/engine/restart":
            ENGINE.stop("redémarrage")
            t_end = time.time() + 40
            while ENGINE.status()["state"] in ("stopping", "starting") and time.time() < t_end:
                time.sleep(0.2)
            try:
                ENGINE.ensure_ready()
                return self.reply(200, {"ok": True})
            except EngineError as e:
                return self.reply(503, {"error": str(e)})
        if path in ("/api/chat", "/api/generate"):
            return self.ollama_call("chat" if path == "/api/chat" else "generate", raw)
        if path in ("/v1/chat/completions", "/v1/completions"):
            return self.passthrough(path, raw)
        self.relay_ollama("POST", raw)

    def do_DELETE(self):
        self.relay_ollama("DELETE", self.body())

    do_PUT = do_PATCH = do_DELETE

    # ------------------------------------------------ appel au moteur
    def backend(self):
        return http.client.HTTPConnection("127.0.0.1", ENGINE.cfg()["backend_port"], timeout=3600)

    def with_engine(self, fn):
        """Prend une place, attend llama-server, exécute fn(load_seconds). Réponse 503 explicite si le moteur ne démarre pas."""
        try:
            par = ENGINE.cfg()["parallel"]
        except EngineError as e:
            return self.reply(503, {"error": str(e)})
        sem = ENGINE.slots(par)
        ENGINE.enter()
        got = sem.acquire(timeout=3600)
        try:
            try:
                load = ENGINE.ensure_ready()
            except EngineError as e:
                return self.reply(503, {"error": str(e)})
            return fn(load)
        finally:
            if got:
                sem.release()
            ENGINE.leave()

    def ollama_call(self, kind, raw):
        try:
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ValueError("objet JSON attendu")
            oa, stream = L.chat_to_openai(body) if kind == "chat" else L.generate_to_openai(body)
        except ValueError as e:
            return self.reply(400, {"error": str(e)})
        model = ENGINE.cfg()["model"]
        t0 = time.time()

        def go(load):
            conn = self.backend()
            try:
                conn.request("POST", "/v1/chat/completions", body=json.dumps(oa), headers={"Content-Type": "application/json"})
                r = conn.getresponse()
                if r.status != 200:
                    return self.backend_error(r)
                if not stream:
                    resp = json.loads(r.read() or b"{}")
                    ENGINE.note_spec(resp.get("timings") if isinstance(resp, dict) else None)
                    return self.reply(200, L.response_to_ollama(kind, model, resp, t0, time.time(), load))
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                tr = L.StreamTranslator(kind, model, t0=t0, load_s=load)
                while True:
                    line = r.readline()
                    if not line:
                        break
                    for out in tr.feed(line):
                        self.wfile.write(out)
                        self.wfile.flush()
                for out in tr.close():
                    self.wfile.write(out)
                    self.wfile.flush()
                ENGINE.note_spec(tr.timings)
            except (BrokenPipeError, ConnectionResetError):
                pass   # le client est parti : fermer la connexion à llama-server interrompt la génération
            except OSError as e:
                try:
                    self.reply(502, {"error": "llama-server injoignable : %s" % e})
                except OSError:
                    pass
            except ValueError as e:
                try:
                    self.reply(502, {"error": "réponse illisible de llama-server : %s" % e})
                except OSError:
                    pass
            finally:
                conn.close()
        self.with_engine(go)

    def backend_error(self, r):
        raw = r.read()
        try:
            d = json.loads(raw or b"{}")
            msg = (d.get("error") or {}).get("message") if isinstance(d.get("error"), dict) else d.get("error")
        except ValueError:
            msg = None
        self.reply(r.status if 400 <= r.status < 600 else 502, {"error": str(msg or "erreur de llama-server (HTTP %d)" % r.status)[:500]})

    def passthrough(self, path, raw):
        """API compatible OpenAI : transmise telle quelle (flux compris)."""
        def go(load):
            conn = self.backend()
            try:
                conn.request("POST", path, body=raw, headers={"Content-Type": "application/json"})
                r = conn.getresponse()
                self.send_response(r.status)
                self.send_header("Content-Type", r.getheader("Content-Type", "application/json"))
                self.end_headers()
                while True:
                    chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except OSError as e:
                try:
                    self.reply(502, {"error": "llama-server injoignable : %s" % e})
                except OSError:
                    pass
            finally:
                conn.close()
        self.with_engine(go)


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main(argv):
    global ENGINE
    if len(argv) != 2 or not L.ENGINE_ID_RE.match(argv[1]):
        sys.stderr.write("usage : llama-engine.py <identifiant>\n")
        return 2
    ENGINE = Engine(argv[1])
    try:
        cfg = ENGINE.cfg()
    except EngineError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    port = int(os.environ.get("OB_ENGINE_PORT") or cfg.get("port") or 0)
    if not port:
        sys.stderr.write("port du moteur non défini\n")
        return 1
    srv = Server(("127.0.0.1", port), Handler)

    def bye(*_):
        threading.Thread(target=lambda: (ENGINE.stop("arrêt du service"), os._exit(0)), daemon=True).start()
    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    threading.Thread(target=ENGINE.watch, daemon=True, name="watch").start()
    say("moteur « %s » prêt sur 127.0.0.1:%d pour le modèle %s (llama-server démarré à la première demande)" % (ENGINE.id, port, cfg["model"]))
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
