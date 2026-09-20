#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# One-time setup
#
# Checks the Linux or WSL installation before creating configuration files.
# Creates the provider-key file and a private key for the local gateway.
# Writes Continue settings and an optional systemd user service.
# The service is only written here; starting or enabling it is a separate step.
# ----------------------------------------------------------------------------

import json
import os
import secrets
import shlex
import shutil
import stat
import sys
from lib.systemPrompt import SYSTEM_PROMPT

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REQUIRED_FILES = [
    "core/config.yaml",
    "core/routerHook.py",
    "core/apiKeys.sh",
    "core/localServer.py",
    "core/localWorker.py",
    "start.sh",
    "kill.sh",
    "query.py",
    "ui/server.py",
    "ui/index.html",
    "ui/style.css",
    "ui/script.js",
    "lib/memoryManager.py",
    "lib/skillLoader.py",
    "lib/proxyClient.py",
    "lib/tokenOptimizer.py",
    "lib/outputManager.py",
    "lib/localModels.py",
    ".image/logo.png",
]

def main():
    ## Startup scripts use Bash and Linux process tools, so setup runs inside Linux/WSL.
    if os.name != "posix": sys.exit("Run setup.py inside Linux, WSL, or the development container.")
    if sys.version_info < (3, 11): sys.exit("Python 3.11 or newer is required.")
    for relative in REQUIRED_FILES:
        if not os.path.isfile(os.path.join(BASE_DIR, relative)):
            sys.exit(f"Missing required file: {relative}")

    ## Find the gateway in the active environment before creating config files.
    executable = shutil.which("litellm")
    if not executable: sys.exit("Install dependencies first: python3 -m pip install -r requirements.txt")

    prepareEnvironment()
    for name in ("start.sh", "kill.sh", "query.py", "core/apiKeys.sh"):
        path = os.path.join(BASE_DIR, name)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    os.makedirs(os.path.join(BASE_DIR, "models"), exist_ok=True)

    ## Import after creating the environment file so the client reads the new key.
    from lib.proxyClient import PROXY_HEADERS, PROXY_URL
    gatewayKey = PROXY_HEADERS["Authorization"].removeprefix("Bearer ")

    ## Generate integrations after the client has read the newly created gateway key.
    configureContinue(PROXY_URL, gatewayKey)
    configureService(executable)
    print(">> Setup complete. Add provider keys to core/litellm.env, then run bash start.sh.")
    print(">> For optional systemd use: systemctl --user daemon-reload")

# ----------------
#    Utilities
# ----------------

def writeText(path, content, private=False):
    ## Create parent folders and write text; protect private credential files.
    ## Private files use owner-only permissions; normal config files remain readable.
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.islink(path) and not os.path.exists(path): os.unlink(path)
    with open(path, "w", encoding="utf-8") as outputFile: outputFile.write(content)
    os.chmod(path, 0o600 if private else 0o644)

def prepareEnvironment():
    # ---------------------------------------------------------------------------
    # Create an editable provider-key file and a private gateway key.
    # Provider keys remain empty until configured. The gateway key authenticates
    # local clients and is generated only when no usable key is already present.
    # Existing provider settings and comments remain in the environment file.
    # ---------------------------------------------------------------------------
    envPath = os.path.join(BASE_DIR, "core", "litellm.env")

    ## Copy the blank template only once; keep existing provider keys on reruns.
    if not os.path.isfile(envPath): shutil.copyfile(envPath + ".example", envPath)
    with open(envPath, encoding="utf-8") as envFile: lines = envFile.read().splitlines()

    ## A process-level gateway key takes precedence over the env file value.
    key = os.environ.get("LITELLM_MASTER_KEY", "")
    for line in lines:
        name, separator, value = line.strip().removeprefix("export ").partition("=")
        if separator and name.strip() == "LITELLM_MASTER_KEY" and not key:
            parsed = shlex.split(value, comments=True)
            key = parsed[0] if parsed else ""

    ## Replace missing keys and the old shared placeholder with a random private key.
    if not key or key == "sk-anything": key = "sk-" + secrets.token_hex(32)

    ## Drop only the old master-key assignment, keeping provider settings and comments.
    retained = []
    for line in lines:
        name = line.strip().removeprefix("export ").partition("=")[0].strip()
        if name != "LITELLM_MASTER_KEY": retained.append(line)

    retained.append("LITELLM_MASTER_KEY=" + shlex.quote(key))
    writeText(envPath, "\n".join(retained) + "\n", private=True)
    os.environ["LITELLM_MASTER_KEY"] = key

def configureContinue(proxyUrl, gatewayKey):
    ## Write Continue configuration and copy only the gateway credential.
    directory = os.path.expanduser("~/.continue")

    ## Replace a broken Continue-directory symlink and ensure the directory exists.
    if os.path.islink(directory) and not os.path.exists(directory): os.unlink(directory)
    os.makedirs(directory, exist_ok=True)

    secretPath = os.path.join(directory, ".env")
    destination = os.path.join(directory, "config.yaml")

    ## Keep unrelated Continue secrets and replace only the local gateway credential.
    secretLines = []
    if os.path.isfile(secretPath):
        with open(secretPath, encoding="utf-8") as secretFile:
            for line in secretFile.read().splitlines():
                if not line.startswith("LITELLM_MASTER_KEY="):
                    secretLines.append(line)
    secretLines.append("LITELLM_MASTER_KEY=" + shlex.quote(gatewayKey))
    writeText(secretPath, "\n".join(secretLines) + "\n", private=True)

    ## Continue needs the API base URL rather than the completion endpoint itself.
    apiBase = proxyUrl.rsplit("/chat/completions", 1)[0]
    config = (
        "# Generated by setup.py for the configured gateway.\n"
        "name: hazar-ai\nversion: 1.0.0\nschema: v1\n\n"
        "models:\n  - name: local-router\n    provider: openai\n"
        "    model: auto\n"
        f"    apiBase: {json.dumps(apiBase)}\n"
        "    apiKey: ${{ secrets.LITELLM_MASTER_KEY }}\n"
    )
    ## Include the shared personality alongside Continue's own instructions.
    config += "\nrules:\n"
    config += "  - " + json.dumps(SYSTEM_PROMPT) + "\n"

    writeText(destination, config)
    print(f">> Continue configuration: {destination}")

def configureService(executable):
    # ----------------------------------------------------------------------------
    # Generate an optional user service with paths for this installation.
    # Setup writes the unit but does not start or enable it. The executable
    # points directly to the active environment, avoiding a symlink that could
    # replace its own target. systemd is optional for manual startup.
    # 'unit' points directly at this environment; no executable symlink is needed.
    # ----------------------------------------------------------------------------
    unit = (
        "# Generated by setup.py; manual startup uses start.sh.\n"
        "[Unit]\nDescription=LiteLLM proxy\nAfter=network.target\n\n"
        "[Service]\n"
        f'WorkingDirectory="{BASE_DIR}"\n'
        f'Environment="PYTHONPATH={BASE_DIR}/core:{BASE_DIR}"\n'
        f'EnvironmentFile="{BASE_DIR}/core/litellm.env"\n'
        f'ExecStart="{executable}" --config "{BASE_DIR}/core/config.yaml" --port 4000\n'
        "Restart=on-failure\n\n[Install]\nWantedBy=default.target\n"
    )
    path = os.path.expanduser("~/.config/systemd/user/litellm.service")
    writeText(path, unit)
    print(f">> Optional systemd service: {path}")

if __name__ == "__main__": main()
