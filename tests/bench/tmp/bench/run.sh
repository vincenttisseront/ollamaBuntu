#!/bin/bash
T=/tmp/target
for d in dev dev/pts proc sys run; do mountpoint -q $T/$d || mount --bind /$d $T/$d; done
pkill -f "admin/server.py"; pkill -f "ollama serve"; pkill -f mocks.py; sleep 1
if [ -n "${NOSTUB:-}" ]; then rm -f $T/usr/local/bin/docker $T/usr/local/bin/systemctl; else bash /tmp/bench/stubs.sh; fi
rm -rf $T/tmp/gpufake; cp -a /tmp/gpufake $T/tmp/gpufake
python3 /tmp/bench/mocks.py ${WEBUI:+--webui} > /tmp/bench/mocks.log 2>&1 &
chroot --userspec=ollama:ollama $T /usr/bin/env -i HOME=/usr/share/ollama PATH=/usr/local/bin:/usr/bin:/bin OLLAMA_HOST=127.0.0.1:11434 /usr/local/bin/ollama serve > /tmp/ollama-serve.log 2>&1 &
for i in $(seq 1 30); do curl -s http://127.0.0.1:11434/api/version >/dev/null && break; sleep 1; done
for m in llama3.2:3b qwen3.5:2b ob-tiny; do printf 'FROM /tmp/ob-tiny.gguf\n' > $T/tmp/Modelfile; chroot --userspec=ollama:ollama $T /usr/bin/env -i HOME=/usr/share/ollama OLLAMA_HOST=127.0.0.1:11434 /usr/local/bin/ollama create $m -f /tmp/Modelfile >/dev/null 2>&1; done
chroot $T /usr/bin/env -i HOME=/root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin OB_HTTPS_PORT=18443 OB_HTTP_PORT=0 OB_WEBUI_TLS_PORT=18843 \
  OB_OSV_URL=http://127.0.0.1:18099 OB_REGISTRY=http://127.0.0.1:18098 OB_OLLAMA_LOG=/tmp/gpufake/ollama.log OB_PCI_ROOT=/tmp/gpufake/pci OB_WEBUI_MIN_FREE_KB=1 \
  OB_OLLAMA_MAIN=127.0.0.1:11434 OB_NFT=/usr/local/bin/nft-stub ${EXTRA_ENV:-} python3 /usr/local/lib/ollamabuntu/admin/server.py > /tmp/admin.log 2>&1 &
for i in $(seq 1 30); do curl -sk https://127.0.0.1:18443/api/ping >/dev/null && break; sleep 1; done
${CLIENT:-python3 /tmp/bench/client.py}
pkill -f "admin/server.py"; pkill -f "ollama serve"; pkill -f mocks.py
