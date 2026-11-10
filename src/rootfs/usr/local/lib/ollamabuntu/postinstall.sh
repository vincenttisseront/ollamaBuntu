#!/bin/bash
# OllamaBuntu - configuration du système installé (exécuté en chroot par late.sh)
set -Eeuo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SERIAL_TTY=${SERIAL_TTY:-}
say() { echo "[postinstall] $*"; }

say "compte de service ollama"
id ollama >/dev/null 2>&1 || useradd -r -s /bin/false -U -m -d /usr/share/ollama ollama
for g in render video; do getent group "$g" >/dev/null || groupadd -r "$g"; usermod -aG "$g" ollama; done
mkdir -p /usr/share/ollama/.ollama/models
chown -R ollama:ollama /usr/share/ollama
chmod 0755 /usr/local/bin/ollama

say "répertoires de l'appliance"
mkdir -p /var/lib/ollamabuntu/jobs /etc/ollamabuntu/tls
chmod 0700 /etc/ollamabuntu/tls /var/lib/ollamabuntu/jobs

say "cloud-init désactivé (l'appliance utilise son propre assistant)"
mkdir -p /etc/cloud && touch /etc/cloud/cloud-init.disabled

say "droits sudo du menu console"
chmod 0440 /etc/sudoers.d/ollamabuntu
visudo -cf /etc/sudoers.d/ollamabuntu >/dev/null

say "activation des services"
# SYSTEMD_OFFLINE=1 : activation hors ligne garantie, même si systemd ne détecte pas le chroot
export SYSTEMD_OFFLINE=1
systemctl enable ollama.service ollamabuntu-admin.service ollamabuntu-router.service ollamabuntu-firstboot@tty1.service

say "API Ollama : port interne 11400, routeur et contrôle d'accès sur 11434"
E=/etc/ollamabuntu
grep -q '^OLLAMA_HOST=' "$E/ollama-main.env" 2>/dev/null || printf 'OLLAMA_HOST=127.0.0.1:11400\n' >> "$E/ollama-main.env"
chmod 0644 "$E/ollama-main.env"
if [[ ! -f $E/publication.json ]]; then
  if grep -qE '^OLLAMA_HOST="?(0\.0\.0\.0|\[::\]|::)' "$E/ollama.env" 2>/dev/null; then
    # API déjà exposée par une version précédente : même accès, sans clé (signalé dans la console)
    echo '{"enabled": true, "port": 11434, "tls": false, "auth": false, "allow": [], "anonymous": {"perms": ["inference", "read", "manage"], "models": []}, "keys": [], "migrated": true}' > "$E/publication.json"
    say "  API déjà exposée : accès réseau conservé à l'identique, à sécuriser depuis la console"
  else
    echo '{"enabled": false, "port": 11443, "tls": true, "auth": true, "allow": [], "anonymous": {"perms": ["inference", "read"], "models": []}, "keys": []}' > "$E/publication.json"
  fi
fi
chown root:ollama "$E/publication.json"
chmod 0640 "$E/publication.json"

say "langue de l'appliance : bannière de connexion"
/usr/local/sbin/ollamabuntu-setup --refresh-issue 2>/dev/null || cp -f /usr/share/ollamabuntu/issue.fr /etc/issue

say "politique d'usage de l'IA"
if [[ ! -f $E/ai-policy.json ]]; then
  # première version avec politique : fonctions cloud d'Ollama coupées par défaut (données hors serveur)
  grep -q '^OLLAMA_NO_CLOUD=' "$E/ollama.env" 2>/dev/null || { printf 'OLLAMA_NO_CLOUD=1\n' >> "$E/ollama.env"; say "  fonctions cloud d'Ollama désactivées (modifiable : console > Sécurité > Usages de l'IA)"; }
  echo '{"cloud": false, "ollama_internet": true, "webui_locked": false, "webui": {"web_search": false, "image_generation": false, "code_execution": false, "code_interpreter": false, "external_apis": false, "direct_connections": false, "community_sharing": false}}' > "$E/ai-policy.json"
  printf '%s\n' "# Politique d'usage de l'IA (console OllamaBuntu) : fonctions d'Open WebUI" ENABLE_WEB_SEARCH=false ENABLE_IMAGE_GENERATION=false ENABLE_CODE_EXECUTION=false \
    ENABLE_CODE_INTERPRETER=false ENABLE_OPENAI_API=false ENABLE_DIRECT_CONNECTIONS=false ENABLE_COMMUNITY_SHARING=false > "$E/open-webui-policy.env"
  chmod 0600 "$E/open-webui-policy.env"
fi
chmod 0644 "$E/ai-policy.json"
say "durcissement : paquets de sécurité"
D=/var/cache/ollamabuntu/debs
install_local() {   # paquets embarqués dans l'ISO, uniquement absents ou plus anciens (jamais de rétrogradation)
  local p f new cur sel=()
  for p in "$@"; do
    f=""
    for c in "$D/${p}"_*.deb; do [[ -f $c ]] && f=$c; done
    [[ -n $f ]] || continue
    new=$(dpkg-deb -f "$f" Version)
    cur=$(dpkg-query -W -f='${Version}' "$p" 2>/dev/null || true)
    if [[ -z $cur ]] || dpkg --compare-versions "$cur" lt "$new"; then sel+=("$f"); fi
  done
  ((${#sel[@]} == 0)) || DEBIAN_FRONTEND=noninteractive dpkg -i --force-confold "${sel[@]}" >/dev/null
}
if ! command -v nft >/dev/null; then
  install_local libjansson4 libnftnl11 libnftables1 nftables && command -v nft >/dev/null && say "  nftables installé (paquets embarqués)" || say "  nftables absent : pare-feu inactif (installable depuis la console)"
fi
if [[ ! -x /usr/bin/unattended-upgrade ]]; then
  install_local liblzma5 xz-utils distro-info-data python3-distro-info lsb-release python-apt-common python3-apt unattended-upgrades \
    && [[ -x /usr/bin/unattended-upgrade ]] && say "  unattended-upgrades installé (paquets embarqués)" || say "  unattended-upgrades absent (installable depuis la console)"
fi

if [[ -s /etc/crypttab ]] && grep -qvE '^[[:space:]]*(#|$)' /etc/crypttab && [[ ! -x /usr/bin/clevis ]]; then
  say "chiffrement du disque : outils de déverrouillage (clevis, TPM2)"
  install_local libjose0 jose libluksmeta0 luksmeta libpwquality-common libpwquality1 libpwquality-tools libcrack2 cracklib-runtime wamerican libonig5 libjq1 jq \
    libtss2-mu-4.0.1-0t64 libtss2-tcti-device0t64 libtss2-tcti-swtpm0t64 libtss2-tcti-mssim0t64 libtss2-tcti-libtpms0t64 libtss2-tcti-spi-helper0t64 libtss2-tcti-cmd0t64 \
    libtss2-tctildr0t64 libtss2-sys1t64 libtss2-esys-3.0.2-0t64 libtss2-rc0t64 libtss2-fapi1t64 tpm-udev tpm2-tools dracut-install libcurl3t64-gnutls \
    clevis clevis-luks clevis-tpm2 clevis-initramfs \
    && [[ -x /usr/bin/clevis ]] && say "  clevis installé (paquets embarqués)" || say "  clevis absent : déverrouillage par TPM indisponible (phrase de passe seulement)"
fi

say "durcissement : pare-feu"
[[ -f $E/firewall.nft ]] || python3 /usr/local/lib/ollamabuntu/admin/server.py --render-firewall > "$E/firewall.nft"
chmod 0644 "$E/firewall.nft"
systemctl enable ollamabuntu-firewall.service

say "durcissement : mises à jour de sécurité automatiques (première configuration uniquement)"
if [[ ! -f $E/.autoupdates-configured && -x /usr/bin/unattended-upgrade ]]; then
  python3 /usr/local/lib/ollamabuntu/admin/server.py --init-autoupdates && touch "$E/.autoupdates-configured"
fi
systemctl enable apt-daily.timer apt-daily-upgrade.timer >/dev/null 2>&1 || true

say "durcissement : console (Ctrl+Alt+Suppr) et SSH"
systemctl mask ctrl-alt-del.target >/dev/null 2>&1 || true
if command -v sshd >/dev/null && sshd -t 2>&1 | grep -q "50-ollamabuntu"; then
  rm -f /etc/ssh/sshd_config.d/50-ollamabuntu.conf
  say "  configuration SSH durcie refusée par sshd : retirée (SSH reste utilisable)"
fi
if [[ $SERIAL_TTY =~ ^ttyS[0-9]+$ ]]; then
  systemctl enable "ollamabuntu-firstboot@${SERIAL_TTY}.service"
  say "assistant également sur la console série $SERIAL_TTY"
fi
say "terminé"
