import subprocess

def run(cmd):
    print(f"Running: {cmd}")
    subprocess.run(cmd, shell=True)

# Step 1: Pip upgrade + package installations
run("pip install --upgrade pip")
run("pip install telebot")
run("pip install flask")
run("pip install aiogram")
run("pip install PyTelegramBotAPI")

# Step 2: Chmod for all files in folder
run("chmod +x *")

# Step 3: Tumhara main script lund.py run kar do
run("python3 lund.py")

print("\nSab process successfully complete ho gaya!\n")
