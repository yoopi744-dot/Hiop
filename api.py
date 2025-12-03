import os
import time
import base64
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)


# -----------------------------
# CREATE PRIVATE REPO
# -----------------------------
def create_repo(username, token, repo_name):
    url = "https://api.github.com/user/repos"
    headers = {"Authorization": f"token {token}"}
    data = {"name": repo_name, "private": True}
    r = requests.post(url, json=data, headers=headers)
    return r.json()


# -----------------------------
# UPLOAD FILE TO REPO
# -----------------------------
def upload_file(username, repo, token, path, content):
    url = f"https://api.github.com/repos/{username}/{repo}/contents/{path}"
    headers = {"Authorization": f"token {token}"}
    data = {
        "message": "add workflow",
        "content": base64.b64encode(content.encode()).decode()
    }
    r = requests.put(url, json=data, headers=headers)
    return r.json()


# -----------------------------
# DELETE REPO AFTER TIME
# -----------------------------
def delete_repo(username, repo, token):
    url = f"https://api.github.com/repos/{username}/{repo}"
    headers = {"Authorization": f"token {token}"}
    r = requests.delete(url, headers=headers)
    return r.status_code


# -----------------------------
# MAIN API ENDPOINT
# -----------------------------
@app.route("/run", methods=["POST"])
def run():
    data = request.json

    ip = data.get("ip")
    port = data.get("port")
    dur = int(data.get("time"))

    token = data.get("token")
    username = data.get("username")

    repo_name = f"auto-{int(time.time())}"

    # 1) Create private repo
    create_repo(username, token, repo_name)

    # 2) Workflow content (safe)
    workflow = f"""
name: Auto Workflow
on:
  push:

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - name: Show Inputs
        run: |
          echo "IP: {ip}"
          echo "PORT: {port}"
          echo "TIME: {dur}"
          sleep {dur}
    """

    upload_file(
        username,
        repo_name,
        token,
        ".github/workflows/main.yml",
        workflow
    )

    # 3) Wait for given time
    time.sleep(dur + 2)

    # 4) Delete repo
    delete_repo(username, repo_name, token)

    return jsonify({
        "status": "OK",
        "repo_created": repo_name,
        "deleted_after_seconds": dur
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)