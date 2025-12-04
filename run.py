import subprocess
import os

def run(cmd):
    print(f"Running: {cmd}")
    subprocess.run(cmd, shell=True)

# Packages install
run("pip install --upgrade pip")
run("pip install telebot")
run("pip install flask")
run("pip install aiogram")
run("pip install PyTelegramBotAPI")

# File permissions (current directory ke sabhi files)
run("chmod +x *")

print("\nSab commands successfully run ho gaye!\n")
