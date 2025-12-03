from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import requests, base64, os, threading, time
from config import TOKEN, USERNAME, FILE_PATH, UPLOAD_NAME, REPO_PREFIX, ENABLE_WORKFLOW, WORKFLOW_YAML, ENABLE_API_CALL, API_URL, API_METHOD, API_PAYLOAD, API_HEADERS

app = FastAPI(title="Dynamic Repo API with API-controlled delete")

HEADERS = {"Authorization": f"token {TOKEN}", "Accept": "application/vnd.github+json"}

# -----------------------------
# GitHub functions
# -----------------------------
def create_repo(repo_name):
    url = "https://api.github.com/user/repos"
    data = {"name": repo_name, "private": True}
    r = requests.post(url, json=data, headers=HEADERS)
    if r.status_code not in [201, 422]:
        raise HTTPException(status_code=400, detail=f"Repo creation failed: {r.text}")
    return r.json()

def upload_file(repo_name):
    if not os.path.exists(FILE_PATH):
        raise HTTPException(status_code=404, detail=f"{FILE_PATH} not found")
    with open(FILE_PATH, "rb") as f:
        content = f.read()
    url = f"https://api.github.com/repos/{USERNAME}/{repo_name}/contents/{UPLOAD_NAME}"
    data = {"message": f"Upload {UPLOAD_NAME}", "content": base64.b64encode(content).decode()}
    r = requests.put(url, json=data, headers=HEADERS)
    if r.status_code not in [200, 201]:
        raise HTTPException(status_code=400, detail=f"File upload failed: {r.text}")
    return r.json()

def upload_workflow(repo_name):
    url = f"https://api.github.com/repos/{USERNAME}/{repo_name}/contents/.github/workflows/main.yml"
    encoded = base64.b64encode(WORKFLOW_YAML.encode()).decode()
    data = {"message": "Upload workflow", "content": encoded}
    r = requests.put(url, json=data, headers=HEADERS)
    if r.status_code not in [200, 201]:
        raise HTTPException(status_code=400, detail=f"Workflow upload failed: {r.text}")

def delete_repo(repo_name):
    url = f"https://api.github.com/repos/{USERNAME}/{repo_name}"
    requests.delete(url, headers=HEADERS)
    print(f"[+] Repo deleted: {repo_name}")

def schedule_delete(repo_name, delay_seconds):
    print(f"[~] Delete scheduled in {delay_seconds} sec")
    time.sleep(delay_seconds)
    delete_repo(repo_name)

# -----------------------------
# API call function
# -----------------------------
def run_api_call():
    if not ENABLE_API_CALL or not API_URL:
        return
    method = API_METHOD.upper()
    try:
        if method == "POST":
            r = requests.post(API_URL, json=API_PAYLOAD, headers=API_HEADERS)
        else:
            r = requests.get(API_URL, params=API_PAYLOAD, headers=API_HEADERS)
        print(f"[+] API called: {API_URL}, status: {r.status_code}")
    except Exception as e:
        print(f"[!] API call failed: {e}")

# -----------------------------
# Main automation
# -----------------------------
def run_automation(delete_after: int):
    repo_name = f"{REPO_PREFIX}-{int(time.time())}"

    create_repo(repo_name)
    print(f"[+] Repo created: {repo_name}")

    upload_file(repo_name)
    print("[+] File uploaded")

    if ENABLE_WORKFLOW:
        upload_workflow(repo_name)
        print("[+] Workflow uploaded")

    # API call after upload
    run_api_call()

    # Schedule deletion using API-provided time
    threading.Thread(target=schedule_delete, args=(repo_name, delete_after), daemon=True).start()
    print(f"[✔] Repo `{repo_name}` will delete after {delete_after} seconds")

# -----------------------------
# FastAPI endpoint
# -----------------------------
@app.get("/api/run")
def api_run(time: int):
    """
    API call: provide `time` parameter in seconds
    Example: /api/run?time=120
    """
    run_automation(time)
    return JSONResponse(content={"status": "success", "delete_after": time})