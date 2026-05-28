---
name: run-local
description: Run the brief pipeline locally. Use when the user wants to test locally, run a source, or preview output.
allowed-tools: Bash
---

Run the local pipeline:

```bash
# Full run (all sources)
python main.py

# Single source test
python main.py --source <source_id>
```

After the run completes, confirm output was written:

```bash
python3 -c "import json,sys; d=json.load(open('output/latest.json')); print('date:', d['date'], '| deep_takes:', len(d['deep_takes']), '| bullets:', len(d['bullets']))"
```

To preview in browser, start the server:

```bash
python3 -m http.server 8081
# then open http://localhost:8081/site/
```
