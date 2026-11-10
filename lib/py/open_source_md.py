import json, sys
items = json.load(open(sys.argv[1]))["items"]
out = ["# OllamaBuntu %s - logiciels libres utilisés" % sys.argv[3], "",
       "OllamaBuntu assemble et configure les projets open source suivants, sans les modifier.", ""]
cats = []
for i in items:
    if i["category"] not in cats:
        cats.append(i["category"])
for c in cats:
    out += ["## " + c, "", "| Projet | Rôle | Licence |", "|---|---|---|"]
    out += ["| [%s](%s) | %s | %s |" % (i["name"], i["url"], i["role"], i["license"]) for i in items if i["category"] == c]
    out.append("")
open(sys.argv[2], "w").write("\n".join(out))
