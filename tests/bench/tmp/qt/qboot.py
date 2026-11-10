#!/usr/bin/env python3
"""Banc de test : démarre une ISO dans QEMU, captures d'écran + sortie série."""
import argparse, os, socket, subprocess, sys, time, shutil
from PIL import Image
p = argparse.ArgumentParser()
p.add_argument("name"); p.add_argument("fw", choices=["bios", "uefi"]); p.add_argument("iso")
p.add_argument("--media", choices=["cd", "usb"], default="cd")
p.add_argument("--disk", action="append", default=[])
p.add_argument("--shots", default="6")          # secondes des captures, ex "4,15"
p.add_argument("--timeout", type=int, default=120)
p.add_argument("--keys", default="")            # "t:touche,t:touche" envoyées via le moniteur
a = p.parse_args()
d = "/tmp/qt"; ser = f"{d}/{a.name}.serial"; mon = f"{d}/{a.name}.mon"
for f in (ser, mon):
    if os.path.exists(f): os.remove(f)
args = ["qemu-system-x86_64", "-machine", "q35", "-m", "1536", "-smp", "1", "-accel", "tcg",
        "-display", "none", "-vga", "std", "-serial", f"file:{ser}", "-monitor", f"unix:{mon},server,nowait", "-no-reboot"]
if a.fw == "uefi":
    vars_ = f"{d}/{a.name}-vars.fd"; shutil.copy("/usr/share/OVMF/OVMF_VARS_4M.fd", vars_)
    args += ["-drive", "if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd", "-drive", f"if=pflash,format=raw,file={vars_}"]
if a.media == "cd":
    args += ["-drive", f"id=cd,if=none,media=cdrom,readonly=on,format=raw,file={a.iso}", "-device", "ide-cd,drive=cd,bootindex=1"]
else:
    args += ["-device", "qemu-xhci", "-drive", f"id=usb,if=none,readonly=on,format=raw,file={a.iso}", "-device", "usb-storage,drive=usb,bootindex=1"]
for i, disk in enumerate(a.disk):
    args += ["-drive", f"id=hd{i},if=none,format=raw,file={disk}", "-device", f"virtio-blk-pci,drive=hd{i},bootindex={i+2}"]
proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
def monitor(cmd):
    for _ in range(50):
        try:
            s = socket.socket(socket.AF_UNIX); s.connect(mon); break
        except OSError: time.sleep(0.2)
    s.settimeout(2)
    try: s.recv(4096)
    except OSError: pass
    s.sendall((cmd + "\n").encode()); time.sleep(0.8); s.close()
t0 = time.time()
shots = sorted(float(x) for x in a.shots.split(",") if x)
keys = sorted((float(k.split(":")[0]), k.split(":", 1)[1]) for k in a.keys.split(",") if k)
done = []
while proc.poll() is None and time.time() - t0 < a.timeout:
    el = time.time() - t0
    for s in shots:
        if s not in done and el >= s:
            ppm = f"{d}/{a.name}-{int(s)}s.ppm"; monitor(f"screendump {ppm}"); time.sleep(0.5)
            if os.path.exists(ppm):
                Image.open(ppm).save(ppm[:-4] + ".png"); os.remove(ppm)
            done.append(s)
    for t, k in keys:
        if ("k", t) not in done and el >= t:
            monitor(f"sendkey {k}"); done.append(("k", t))
    time.sleep(0.3)
if proc.poll() is None:
    proc.kill(); print("TIMEOUT (VM arrêtée)")
print("durée %.0fs" % (time.time() - t0))
print(open(ser, errors="replace").read()[-3000:] if os.path.exists(ser) else "(pas de sortie série)")
