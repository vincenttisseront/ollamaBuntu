import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
assert d["version"] == 1 and d["late-commands"] and d["storage"]["layout"]["name"] == "lvm"
assert ("password" in d["storage"]["layout"]) == (len(sys.argv) > 2)
