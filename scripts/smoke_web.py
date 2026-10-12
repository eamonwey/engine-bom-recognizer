"""HTTP integration checks with synthetic data and mock inference; no cloud call."""
import io
import json
import time
import urllib.request
from PIL import Image

BASE = "http://127.0.0.1:8788"


def upload(path, fields):
    boundary = "bom-smoke-20260917"
    buf = io.BytesIO()
    Image.new("RGB",(400,200),"white").save(buf,format="PNG")
    body = bytearray()
    for name, value in fields.items():
        body.extend(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+name+'"\r\n\r\n'+value+'\r\n').encode())
    body.extend(('--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="smoke.png"\r\nContent-Type: image/png\r\n\r\n').encode())
    body.extend(buf.getvalue())
    body.extend(('\r\n--'+boundary+'--\r\n').encode())
    request = urllib.request.Request(BASE+path, data=bytes(body),
        headers={"Content-Type":"multipart/form-data; boundary="+boundary})
    job_id = json.load(urllib.request.urlopen(request,timeout=10))["job_id"]
    for _ in range(50):
        job = json.load(urllib.request.urlopen(BASE+"/api/jobs/"+job_id,timeout=10))
        if job["status"] != "running":
            if job["status"] != "done":
                raise RuntimeError(job["error"])
            return job_id, job["result"]
        time.sleep(.1)
    raise RuntimeError("mock job did not finish")


inspection_id, inspection = upload("/api/jobs/bom", {"options":json.dumps({"provider":"mock"})})
assert inspection["bom"]["components"]
assert inspection["source_sha256"]
assert inspection["inspection"]["visual_status"] == "not_run"
assert urllib.request.urlopen(BASE+"/api/pages/"+inspection_id+"?page=1").read().startswith(b"\x89PNG")
correct_id, correction = upload("/api/jobs/correct", {"reviewed":json.dumps({"reviewer":"automated integration test",
    "patches":[{"approved":True,"source_page":1,"bbox":[.1,.1,.6,.4],"new_text":"42"}]})})
assert correction["source_sha256"] != correction["output_sha256"]
blob = urllib.request.urlopen(BASE+"/api/corrections/"+correct_id,timeout=10).read()
assert blob.startswith(b"\x89PNG")
print(json.dumps({"http_combined_bom_inspection":"passed","http_preview":"passed","http_correction":"passed","http_download":"passed"}))
