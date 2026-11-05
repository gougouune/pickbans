"""Catches the mistakes node won't: duplicated function declarations in the UI (the later one silently wins).
python tools/check_js.py"""
import collections
import os
import re
import subprocess
import sys

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pickbans", "web", "app.js")
src = open(path, encoding="utf-8").read()
names = re.findall(r"^(?:async )?function (\w+)\(", src, re.M)
dups = {n: c for n, c in collections.Counter(names).items() if c > 1}
consts = collections.Counter(re.findall(r"^(?:const|let) (\w+)\b", src, re.M))
dups.update({n: c for n, c in consts.items() if c > 1})
node = subprocess.run(["node", "-e", f"new Function(require('fs').readFileSync({path!r},'utf8'))"], capture_output=True, text=True)
print("syntax:", "ok" if node.returncode == 0 else node.stderr.strip()[:300])
print("duplicates:", dups or "none")
sys.exit(1 if dups or node.returncode else 0)
