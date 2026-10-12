"""Download pinned author drawings and licenses; no inferred ground truth."""
import concurrent.futures
import hashlib
import json
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "passport": ("Foundation-Devices/passport-assembly", "21c8763968f106c6c611c1c20d8914c71051750f", "CERN-OHL-S-2.0"),
    "arcblue": ("guansk/ArcBlue-HMT-Lite", "8b5ed9b6e23af8c16be793d1557407da5425781e", "CERN-OHL-S-2.0"),
    "openamr": ("openAMRobot/openamr-platform-hw", "161564dcc146532b3de40e8436e8a4a81f49f0dd", "CERN-OHL-P-2.0; third-party notices take precedence"),
}


def fetch(entry):
    name, repo, commit, license_name, path = entry
    url = "https://raw.githubusercontent.com/" + repo + "/" + commit + "/" + urllib.parse.quote(path)
    target = ROOT / "data/public" / (name + "_source") / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        blob = target.read_bytes()
    else:
        blob = urllib.request.urlopen(url, timeout=60).read()
    if blob.startswith(b"version https://git-lfs.github.com/spec/"):
        url = "https://media.githubusercontent.com/media/" + repo + "/" + commit + "/" + urllib.parse.quote(path)
        blob = urllib.request.urlopen(url, timeout=90).read()
    if path.lower().endswith(".pdf") and not blob.startswith(b"%PDF"):
        raise ValueError("not a PDF: " + path)
    target.write_bytes(blob)
    print(name, path, len(blob), flush=True)
    return {"source":name,"repository":"https://github.com/"+repo,"commit":commit,
            "license":license_name,"path":str(target.relative_to(ROOT)).replace("\\","/"),
            "original_path":path,"download_url":url,"sha256":hashlib.sha256(blob).hexdigest()}


def main():
    entries = []
    for name, (repo, commit, license_name) in SOURCES.items():
        directory = ROOT / "data/public" / (name + "_source")
        if not directory.exists():
            subprocess.run(["git","clone","--filter=blob:none","--no-checkout","https://github.com/"+repo+".git",str(directory)],check=True)
        paths = subprocess.check_output(["git","ls-tree","-r","--name-only",commit],cwd=str(directory)).decode().splitlines()
        for path in paths:
            pdf = path.lower().endswith(".pdf") and "Archive/" not in path and not path.startswith("datasheets/")
            if pdf or path.lower().endswith(".csv") or path.startswith("LICENSE") or path in ("README.md","README_zh.md","LICENSING.md","NOTICE.md",".reuse/dep5","mechanical-bom.md"):
                entries.append((name,repo,commit,license_name,path))
    records = []
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch, entry):entry for entry in entries}
        for future in concurrent.futures.as_completed(futures):
            try:
                records.append(future.result())
            except Exception as exc:
                errors.append({"entry":list(futures[future]),"error":str(exc)})
    out = ROOT / "data/public/validation_sources.json"
    out.write_text(json.dumps({"files":sorted(records,key=lambda r:r["path"]),"errors":errors},ensure_ascii=False,indent=2),encoding="utf-8")
    if errors:
        raise RuntimeError("download failures recorded: %d" % len(errors))


if __name__ == "__main__":
    main()
