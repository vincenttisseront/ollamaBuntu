import json, os, sys, time
info = {"version": os.environ["OB_VERSION"], "build_date": time.strftime("%Y-%m-%d %H:%M"),
        "ubuntu": os.environ["OB_BUILD_UBUNTU"], "ollama": os.environ["OB_BUILD_OLLAMA"],
        "models": os.environ["OB_BUILD_MODELS"]}
open(sys.argv[1], "w").write(json.dumps(info, ensure_ascii=False, indent=1) + "\n")
