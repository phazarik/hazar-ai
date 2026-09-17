# Hazar-AI

![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg) [![LiteLLM proxy](https://img.shields.io/badge/LiteLLM-proxy-orange)](https://github.com/BerriAI/litellm) [![Requests](https://img.shields.io/badge/Requests-HTTP-blue)](https://pypi.org/project/requests/) [![Rich](https://img.shields.io/badge/Rich-terminal-purple)](https://pypi.org/project/rich/) [![Pyfiglet](https://img.shields.io/badge/Pyfiglet-ASCII%20text-green)](https://pypi.org/project/pyfiglet/) [![PyYAML](https://img.shields.io/badge/PyYAML-config-red)](https://pypi.org/project/PyYAML/) [![llama-cpp-python server](https://img.shields.io/badge/llama--cpp--python-server-yellow)](https://pypi.org/project/llama-cpp-python/)
[![Marked](https://img.shields.io/badge/Marked-9.1.6-blue)](https://github.com/markedjs/marked) [![Highlight.js](https://img.shields.io/badge/Highlight.js-11.9.0-orange)](https://github.com/highlightjs/highlight.js) [![Bootstrap Icons](https://img.shields.io/badge/Bootstrap%20Icons-1.11.3-purple)](https://github.com/twbs/icons) [![KaTeX](https://img.shields.io/badge/KaTeX-0.16.9-green)](https://github.com/KaTeX/KaTeX) [![marked-katex-extension](https://img.shields.io/badge/marked--katex--extension-5.0.0-blue)](https://github.com/UziTech/marked-katex-extension) [![DOMPurify](https://img.shields.io/badge/DOMPurify-3.0.6-red)](https://github.com/cure53/DOMPurify) [![Google Fonts](https://img.shields.io/badge/Google%20Fonts-Fira%20Code-gray)](https://fonts.google.com/specimen/Fira+Code)

[Quick start](#first-time-setup) · [How it works](#how-it-works) · [CLI examples](#cli-examples) · [Offline use](#local-models-and-offline-use) · [Compare tools](#how-it-compares) · [Troubleshooting](#when-something-goes-wrong)

Running cloud models can get expensive, and free tiers have limits. Hazar-AI brings your configured providers and local models into one place, with routing and retries to help keep a chat moving when a route is temporarily unavailable.

This is a local chat setup for cloud and local language models, with a terminal interface, a browser interface, and a VS Code connection through the Continue extension.

It puts model choices, file attachments, optional skills, and saved conversations in one setup. If a configured model is temporarily unavailable, the app can try another route before a reply starts. It does not remove provider limits or make paid models free. Costs and access still depend on the selected providers and accounts.

## What is included

- Automatic model selection, plus quick, detailed, and local options.
- Streaming replies in the terminal and browser.
- Shared conversation memory for the CLI and web interface.
- Optional skills stored outside this repository.
- Text-file attachments and optional file optimization.
- Download links for larger generated files, without a download of every chat reply.
- A shared personality file for the CLI, web interface, and generated Continue settings.
- A resizable browser layout with font settings grouped at the top of the stylesheet.

This setup sends prompts and receives replies. It does not automatically run generated code, edit the source files mentioned in a prompt, or provide a built-in web search tool. A configured Tavily key alone does not enable browsing.

## Why this tool?

- **One setup, a few ways to chat.** Use a terminal, a browser, or the gateway from Continue in VS Code.
- **Keep everyday tasks simple.** Start with `auto`, or pick `fast`, `smart`, or an installed local model yourself.
- **Bring your own context.** Add text files and a task-specific skill without setting up a coding agent.
- **Keep useful output.** Download larger generated text files from the browser and reuse saved conversation context.
- **Choose where inference runs.** Use configured cloud providers or GGUF models on your own device.

It suits a personal development setup. You still manage model availability, provider keys, hardware, and the quality of generated answers.

### How it compares against existing tools

Hazar-AI and OmniRoute overlap as ways to reach models. Ponytail is a coding skill/plugin that can complement either setup. This is a feature comparison from the supplied Hazar-AI snapshot and the linked upstream READMEs, reviewed on September 17, 2026; it is not a performance benchmark.

<table>
<thead><tr><th>Tool</th><th>Advantages</th><th>Disadvantages / tradeoffs</th><th>Good fit</th></tr></thead>
<tbody>
<tr><td><strong>This setup</strong></td><td><p>Combines CLI and browser chat, shared memory, text attachments, optional skills, and generated-text downloads. Its scripts also start local GGUF servers.</p></td><td><p>You maintain provider routes and the Python/Linux setup. Startup modes replace existing services, browser chats share history, and the UI has no separate user login. It does not execute generated code or include web search.</p></td><td><p>A personal chat workspace where you want cloud and local models plus a few useful context tools.</p></td></tr>
<tr><td><strong>OmniRoute</strong></td><td><p>Its README documents a broad provider catalog, dashboard, quota telemetry, automatic model scoring, configurable routing strategies, and CLI/MCP integration.</p></td><td><p>Its wider routing surface gives you more concepts to understand and configure. Its documented gateway features do not establish that it shares Hazar-AI's exact memory, skill-selection, or file-capture workflow. Provider access and quotas still matter.</p></td><td><p>A gateway-focused setup where provider choice, routing control, and quota visibility are the main priorities.</p></td></tr>
<tr><td><strong>Ponytail</strong></td><td><p>Encourages smaller changes, reuse, and native or existing features before new code. Its upstream integrations offer coding review and audit skills, with hooks in supported hosts.</p></td><td><p>It supplies coding guidance rather than a model gateway or chat service. Results depend on the model and host. Hazar-AI loads selected skill text only, with a character limit; it does not run Ponytail's hooks or plugin commands.</p></td><td><p>Extra guidance when you want an AI coding assistant to avoid unnecessary code. It can also be used as a text skill in Hazar-AI.</p></td></tr>
</tbody>
</table>

Choose this tool for its chat workflow, OmniRoute for its gateway controls, and Ponytail for coding guidance. You can point this tool at another compatible gateway, but matching aliases and endpoint settings need configuration. See [alternate gateways](#another-gateway-including-omniroute). Upstream features are described in the [OmniRoute README](https://github.com/diegosouzapw/OmniRoute#readme) and [Ponytail README](https://github.com/DietrichGebert/ponytail#readme).

## How it works

The repository is structured as follows.
```text
hazar-ai/
├── README.md                    # Start here: setup, usage, and troubleshooting
├── requirements.txt             # Direct Python dependencies
├── setup.py                     # Prepare keys, folders, Continue, and optional service
├── start.sh                     # Start the selected services; default is all
├── kill.sh                      # Stop matching running services
├── query.py                     # CLI chat, attachments, skills, and memory commands
├── core/                        # Gateway configuration and integration
│   ├── config.yaml              # Persistent cloud deployments and routing settings
│   ├── routerHook.py            # Choose fast/smart for automatic requests
│   ├── generateLocalConfig.py   # Generate cloud+local and local-only route files
│   ├── litellm.env.example      # Public template for provider and gateway keys
│   ├── litellm.env              # Private keys; created locally, not committed
│   ├── apiKeys.sh               # Load provider environment settings
│   ├── continueConfig.yaml      # Reference Continue configuration
│   └── litellm.service          # Gateway service template
├── lib/                         # Shared chat helpers
│   ├── proxyClient.py           # Authenticated gateway streaming and bounded retries
│   ├── memoryManager.py         # Save history, summaries, and file metadata
│   ├── skillLoader.py           # Discover, inspect, and expand local skills
│   ├── tokenOptimizer.py        # Compact valid JSON and deduplicate file context
│   ├── outputManager.py         # Capture larger fenced text files safely
│   ├── systemPrompt.py          # Shared personality and response rules
│   └── __init__.py              # Python package marker
├── ui/                          # Browser chat interface
│   ├── server.py                # HTTP backend, chat streaming, and downloads
│   ├── index.html               # Page structure, controls, and CDN libraries
│   ├── script.js                # Browser interactions and streamed replies
│   └── style.css                # Theme, fonts, and resizable layout
├── models/                      # Your GGUF files; created during setup
├── findModels.py                # Discover provider model names
└── cleanup.py                   # Remove temporary files; --all also removes chats/output
```

![Hazar-AI request pipeline, model routes, reply flow, and service ports](.image/structure.png)

1. **Choose an interface.** The CLI runs through `query.py`. The browser talks to `ui/server.py` on port **5000**. Both use the same chat helpers and conversation store.
2. **Build the context.** The app combines your prompt with its personality rules, saved history when memory is enabled, a selected skill, and any UTF-8 text attachments. Optional optimization compacts valid JSON and avoids repeating identical file blocks; it keeps ordinary source formatting and comments intact.
3. **Send the request.** `lib/proxyClient.py` sends an authenticated request to the LiteLLM gateway on port **4000**. It can retry temporary failures and switch between configured tier aliases before output starts. Once content, reasoning, or tool output starts, it does not automatically replay the request.
4. **Pick a model route.** In the normal configuration, `auto` uses local keyword and length checks to choose `fast` or `smart`. An optional model-based classifier makes a separate provider request. Explicit aliases keep the requested route. Cloud deployments come from `core/config.yaml`; local GGUF models run through llama.cpp on ports **8000**, **8001**, and so on. Startup generates matching local aliases.
5. **Bring the answer back.** The selected cloud or local LLM returns its response to LiteLLM. The gateway streams it back through the client to the CLI or web backend, which displays it in the browser. Solid arrows show outgoing requests; dashed arrows show replies returning to the user.
6. **Save completed results.** With memory enabled, a successful completed chat is saved to the shared conversation store. Separately, `lib/outputManager.py` captures eligible complete fenced text blocks of at least **1,000 characters** into `output/<chat-ID>/<request-ID>/`. The browser offers download links; the CLI prints the saved folder. Failed, stopped, or incomplete replies do not create new captured files.

**Continue takes a direct path.** The VS Code extension sends its own context to LiteLLM and receives replies directly. It shares the gateway routes and generated personality settings, but manages its own context and tools; it does not use Hazar-AI's memory, skill selector, or file capture.

**Offline mode keeps inference local.** `bash start.sh offline` starts the web backend, gateway, and GGUF servers with local-only routes. Choose `local` or `local:<model-name>`; `auto`, `fast`, and `smart` are absent. The browser still uses CDN assets, so local inference and a fully offline web page are separate concerns.

Ports in the image are the default local service ports. `8000+` means one consecutive port per GGUF model, not a separate gateway. The memory shown here is saved conversation context, not a knowledge graph.

## First-time setup

Run the following commands in Linux, WSL, or the development container. The startup scripts need Bash and Linux process tools. On Windows, use a WSL terminal rather than PowerShell. **Python 3.11 or newer is required.** Git is needed to download the project and skills. Local model performance depends on available memory and hardware.

### 1. Download the project

```bash
git clone https://github.com/phazarik/hazar-ai.git
cd hazar-ai
```

For an existing checkout, open its folder instead. Run the examples below from the project root.

### 2. Install dependencies

Using Conda:

```bash
conda create -n llm python=3.11 -y
conda activate llm
python3 -m pip install -r requirements.txt
```

Or, with Python 3.11 already installed:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Use one environment, and activate it again in every terminal that runs the Python tools. `requirements.txt` includes LiteLLM, CLI libraries, and the optional llama.cpp server.

If `llama-cpp-python` needs a source build, install compiler tools first. On Ubuntu or Debian:

```bash
sudo apt update
sudo apt install build-essential cmake
```

GPU support needs an appropriate llama.cpp build; the default installation does not guarantee GPU acceleration.

### 3. Create the key file

Copy the template only if the private file does not exist:

```bash
[ -f core/litellm.env ] || cp core/litellm.env.example core/litellm.env
nano core/litellm.env
```

Fill in the providers as follows. These will be used by  `core/config.yaml`.

```bash
OPENROUTER_API_KEY="replace-with-openrouter-key"
GEMINI_API_KEY="replace-with-gemini-key"
GROQ_API_KEY="replace-with-groq-key"
TAVILY_API_KEY="" ## Keep it empty
LITELLM_MASTER_KEY="" ## important! Keep it empty
```

Unused keys can stay empty. Obtain provider keys from the following.

- [OpenRouter](https://openrouter.ai/workspaces/default/keys): an API gateway for models from different providers. Hazar-AI uses your key for configured OpenRouter deployments.
- [Google AI Studio](https://aistudio.google.com/app/api-keys): the place to create a Gemini API key for configured Google model deployments.
- [Groq](https://console.groq.com/keys): a hosted inference provider. Create a key in its console for configured Groq deployments.

Leave `LITELLM_MASTER_KEY` empty on a new installation. Setup generates a private gateway key and connects the local clients to it. An existing usable key is retained; the old `sk-anything` placeholder is replaced. Keep the private key file out of Git. For an offline installation, provider keys can all stay empty.

### 4. Check the configured models

```bash
python3 findModels.py
python3 findModels.py --search llama
```

The script lists models from providers with configured keys. Model names and availability change, so review `core/config.yaml` before starting cloud requests. Remove deployments for unused providers or update their keys and model names. A listed model is not necessarily free or available to every account.

Keep the client aliases `auto`, `fast`, `smart`, and `local`. These are the names used by the CLI and GUI; provider model identifiers belong inside their deployments.

### 5. Run setup

```bash
python3 setup.py
```

Setup checks required files, prepares the environment file, makes scripts executable, creates `models/`, and writes:

- Continue settings to `~/.continue/config.yaml`.
- The Continue gateway secret to `~/.continue/.env`.
- An optional user service to `~/.config/systemd/user/litellm.service`.

Setup does not start the services. It preserves existing provider keys, but **overwrites the generated Continue configuration**. Back up manual Continue changes before rerunning it.

### 6. Start and try a message

```bash
bash start.sh all
```

Open **http://localhost:5000** in a browser. In another terminal, activate the same Python environment and try:

```bash
python3 query.py --query "Reply with a short greeting." --no-memory
```

Startup opens a gateway log view. **Ctrl+C closes that view; background services keep running.** Stop them with:

```bash
bash kill.sh
```

## Startup options

```bash
bash start.sh
bash start.sh all      # Gateway, browser backend, and available GGUF servers
bash start.sh fresh    # Clear shared memory, then start the complete setup
bash start.sh offline  # GGUF servers + local-only gateway + browser; no cloud routes
bash start.sh proxy    # LiteLLM API only; no browser backend or GGUF servers
bash start.sh local    # GGUF servers and generated route files only; no gateway/UI
bash start.sh ui       # Browser backend only; needs an independently running gateway
```

**Every startup mode first stops matching existing services.** Running `start.sh proxy` followed by `start.sh ui` does not combine them: the second command stops the first service. Use `all` for the complete setup. Shutdown patterns can also match another Hazar-AI installation in the same Linux environment.

| Service | Port |
| --- | --- |
| LiteLLM gateway | `4000` |
| Web interface | `5000` |
| First local model | `8000` |
| Additional local models | `8001`, `8002`, and so on |

The web backend binds on all interfaces and has no separate user login. Keep it in a trusted local environment; it is not a public multi-user service.

## Install and manage skills

A skill is a text file with extra instructions for a task. Hazar-AI reads only this layout:

```text
~/.claude/skills/<skill-name>/SKILL.md
```
Keep this exact layout for every skill; a nested upstream skill needs a root file or link.
Use the home directory of the account running the backend. Under WSL, this normally means the Linux home directory, not the Windows home directory. Keep all skills here. Following are some examples:

- **Prompt Master:** a skill for turning a task, context, and constraints into a clearer prompt for another AI tool. See its [upstream README](https://github.com/nidhinjs/prompt-master). Hazar-AI uses the selected text, not the upstream host integration.
	```bash
	mkdir -p ~/.claude/skills
	git clone https://github.com/nidhinjs/prompt-master.git ~/.claude/skills/prompt-master
	```
	
- **Ponytail:** coding guidance that favors reuse and small, complete solutions while preserving validation, error handling, security, and accessibility. See its [upstream README](https://github.com/DietrichGebert/ponytail). Its main skill is nested, so add a link after cloning: 
	```bash
	git clone https://github.com/DietrichGebert/ponytail.git ~/.claude/skills/ponytail
	ln -s skills/ponytail/SKILL.md ~/.claude/skills/ponytail/SKILL.md
	```
- **Create your own:** Here is an example. `ponytail-lite` is a local skill name, not a separate upstream repository. An existing folder with that name can stay in place. To create a short version from scratch:
	```bash
	mkdir -p ~/.claude/skills/ponytail-lite
	cat > ~/.claude/skills/ponytail-lite/SKILL.md <<'EOF'
	# Small, complete changes
	Read the relevant code before choosing a solution.
	Make the smallest complete change that satisfies the request.
	Reuse existing helpers and standard-library features first.
	Avoid unnecessary dependencies, abstractions, and unrelated edits.
	Keep code readable; do not compress it into long one-line expressions.
	Preserve comments, validation, error handling, security, and accessibility.
	Follow the active task when it asks for more detail or a fuller solution.
	Explain the result briefly and report only checks actually performed.
	EOF
	```

### Check, update, or remove a skill

```bash
python3 query.py --list-skills
python3 query.py --skill-inspect prompt-master
python3 query.py --skill-inspect ponytail
```

Refresh the browser after adding or removing a skill. Changes to a selected skill's text are read on the next request. To stop using a skill, select **None**; to remove it from the list, move its folder outside `~/.claude/skills/`.

Only **3,000 characters** of expanded skill text are included in a request. To change the limit, edit `SKILL_CHAR_LIMIT = 3000` in `lib/skillLoader.py`. Restart the web backend; the next CLI process reads the new value. A larger limit uses more context and may increase provider usage. Full inspection is not limited. Longer upstream skills may therefore be incomplete in the prompt; keep important rules early or use a short local version. Local Markdown files referenced under `references/` can be expanded but share the same overall character limit.

## CLI examples

### Ask a question or choose a model

```bash
python3 query.py --query "Explain this Python error."
python3 query.py --model auto --query "Help design a small task tracker."
python3 query.py --model fast --query "Show a Python dictionary example."
python3 query.py --model smart --query "Review this design for edge cases."
```

`auto` is the default. Its first choice uses local keyword and length checks, without an extra provider classification request. Configured alternatives may be tried if a route fails before output begins.

An exact model alias registered in the gateway can also be used with `--model`. Such a name bypasses automatic classification and client tier switching.

### Attach files and optimize their context

```bash
python3 query.py --query "Find bugs in this file." --file app.py
python3 query.py --query "Check how these files work together." --file app.py config.json
python3 query.py --query "Review the configuration." --file config.json --optimize-tokens
```

Attachments are read as UTF-8 text. Optimization shortens valid JSON without changing its values and avoids repeating identical file blocks already present in the request. It does not strip comments or indentation from ordinary source files. Actual savings depend on the content and model.

### Use a skill

```bash
python3 query.py --skill prompt-master --query "Write a prompt for an AI coding assistant to review a Python API."
python3 query.py --skill ponytail --query "Simplify this module without changing its behavior." --file app.py
python3 query.py --skill ponytail-lite --query "Fix the bug with a small, readable change." --file app.py
```

Leaving out `--skill` adds no skill instructions.

### Adjust reply length or skip memory

```bash
python3 query.py --query "Give a short explanation." --max-tokens 300
python3 query.py --query "Write the complete module." --max-tokens 3000
python3 query.py --query "One-off question: explain a generator." --no-memory
```

The default reply limit is **900 tokens**. Tokens are pieces of text, not an exact word count. A larger limit allows more output but cannot guarantee a complete reply. A reply cut short by the limit is treated as incomplete and is not saved to memory or captured as files.

`--no-memory` skips both reading and saving conversation memory for that request. Existing memory is retained. The CLI has no dedicated switch to remove the reply-length limit.

### Combine options

```bash
python3 query.py \
    --model smart \
    --query "Find the bug and return a complete corrected file." \
    --file app.py config.json \
    --skill ponytail-lite \
    --optimize-tokens \
    --max-tokens 3000 \
    --no-memory
```

### Inspect or clear saved memory

```bash
python3 query.py --memory-status
python3 query.py --clear-memory
python3 query.py --help
```

The status command shows saved chat count, summary length, and cached files. Clearing memory deletes the CLI/web conversation context, not generated files or installed skills. These utility commands do not need a completion request.

## Browser controls

Open **http://localhost:5000** after starting the full setup

 ![Browser chat with model choices, skills, attachments, and diagnostics](.images/ui.png) 

<table>
<thead><tr><th><p>Control</p></th><th><p>What happens</p></th></tr></thead>
<tbody>
<tr><td><p><strong>Automatic</strong></p></td><td><p>The app chooses a quick or detailed route for the request.</p></td></tr>
<tr><td><p><strong>Quick</strong></p></td><td><p>Requests the <code>fast</code> route for everyday questions.</p></td></tr>
<tr><td><p><strong>Detailed</strong></p></td><td><p>Requests the <code>smart</code> route for harder tasks.</p></td></tr>
<tr><td><p><strong>On this device</strong></p></td><td><p>Requests the default installed local model. Its server must be running.</p></td></tr>
<tr><td><p><strong>Skill</strong></p></td><td><p>Adds the selected skill&#39;s instructions to the next request. <strong>None</strong> adds no skill.</p></td></tr>
<tr><td><p><strong>View skill</strong></p></td><td><p>Opens the selected skill&#39;s full expanded text without sending a chat message.</p></td></tr>
<tr><td><p><strong>Max Tokens</strong></p></td><td><p>Sets the maximum reply length. Unchecking it omits the app&#39;s explicit limit; the gateway and model still have their own limits.</p></td></tr>
<tr><td><p><strong>Help</strong></p></td><td><p>Opens the control guide.</p></td></tr>
<tr><td><p><strong>Status</strong></p></td><td><p>Prints saved-memory information in the log panel.</p></td></tr>
<tr><td><p><strong>Optimize</strong></p></td><td><p>Toggles file-context optimization for the next request.</p></td></tr>
<tr><td><p><strong>Memory</strong></p></td><td><p>Toggles whether the next request uses and saves conversation memory. Turning it off does not delete existing memory.</p></td></tr>
<tr><td><p><strong>Clear Chat</strong></p></td><td><p>Hides displayed messages without deleting memory. Saved messages may return after a refresh.</p></td></tr>
<tr><td><p><strong>Clear Memory</strong></p></td><td><p>Asks for confirmation, deletes shared conversation memory, and clears the displayed chat.</p></td></tr>
<tr><td><p><strong>Attach file</strong></p></td><td><p>Opens the file picker. Files can also be dropped onto the page and removed before sending.</p></td></tr>
<tr><td><p><strong>Send</strong></p></td><td><p>Sends the prompt and queued attachments.</p></td></tr>
<tr><td><p><strong>Stop</strong></p></td><td><p>Cancels the active reply, restores the prompt and attachments, and leaves partial output visible.</p></td></tr>
</tbody>
</table>

Press **Enter** for a new line. Press **Ctrl+Enter** or **Shift+Enter** to send. Drag the divider above the input to change its height. Drag the diagnostics divider to change the side-panel width on desktop or its height on mobile.

The usage display estimates how much model conversation space the request used. It is not an account quota, a remaining balance, or a guarantee that all earlier messages are available.

## Generated-file downloads

Ordinary replies stay in the chat. The app does not automatically save the whole reply as `response.md` or offer a full-response download.

Complete fenced code or text blocks become downloadable files only when each block contains at least **1,000 characters**, excluding surrounding whitespace. Named blocks keep their safe relative filenames; unnamed blocks get names such as `snippet-1.py`.

For example, ask:

```text
Write a complete Python module for the task. Return it as a fenced block
with filename="report.py", preserving the comments.
```

Eligible files are stored under:

```text
output/<chat-ID>/<request-ID>/
```

The browser shows a link for each saved file. Downloading requires clicking the link; files are not downloaded automatically. The CLI prints the output folder when files were saved. Replies without eligible files create no new output folder.

Change `MIN_FILE_CHARACTERS` in `lib/outputManager.py` to adjust the cutoff. The current capture handles text blocks, not binary files or links to files on a remote model service. Failed, stopped, or incomplete replies do not create new captured files.

## Local models and offline use

Place `.gguf` files directly inside `models/`, then run:

```bash
bash start.sh all
```

Each file gets a llama.cpp server on a consecutive port, starting at `8000`. The first model also receives the plain `local` alias. Specific models use their filenames without `.gguf`:

```bash
python3 query.py --model local --query "Explain a Python list comprehension."
python3 query.py --model "local:my-model" --query "Review this function." --file app.py
```

For local-only inference:

```bash
bash start.sh offline
python3 query.py --model local --query "Hello." --no-memory
```

Select **On this device** in the browser. Offline configuration contains no cloud routes or cloud routing callback. It needs at least one GGUF file; `auto`, `fast`, and `smart` are not registered in that generated configuration.

Memory summarization currently requests the `fast` alias. In offline mode that request can fail, leaving full history intact. Long offline chats may therefore outgrow the local model's context; use `--no-memory`, turn memory off, or clear it when starting a separate task.

Local inference does not require provider access, but the web page still loads rendering libraries and icons from external sites. A browser with no internet access may have reduced rendering support.

Generated gateway configurations are rebuilt by startup. Edit `core/config.yaml` for lasting cloud changes rather than editing generated files.

## VS Code and Continue

Install the Continue extension in the VS Code environment that runs the project. In WSL or a container, use that environment's home directory for the generated configuration and secrets.

1. Run `python3 setup.py`.
2. Start the gateway with `bash start.sh all` or `bash start.sh proxy`.
3. Load the generated local configuration in Continue and select **local-router**.

`core/continueConfig.yaml` is a reference file. The active file written by setup is `~/.continue/config.yaml`; its key comes from `~/.continue/.env`.

Continue connects directly to the gateway. It shares the configured routing and generated personality rules, but **does not use Hazar-AI's saved conversation memory, skill selector, file-capture logic, or browser controls**. Continue manages its own chat context and tools.

Personality rules apply to Continue's Chat, Agent, and Edit requests. Rules do not apply to autocomplete or Apply, and Agent mode also depends on the selected model and gateway supporting tools. See [Continue's rule guide](https://docs.continue.dev/customize/deep-dives/rules).

For offline Continue use, change the generated model setting from `auto` to `local` or a registered `local:<name>` alias. Rerunning setup restores the generated `auto` setting.

## Customize the setup

### Personality

Edit `SYSTEM_PROMPT` in `lib/systemPrompt.py`. The current prompt uses Morpheus/Neo, asks for practical Markdown replies, avoids a large opening heading, and disables emojis. It relies on supplied history rather than claiming perfect memory.

Restart the web backend after a change. The next CLI invocation reads it automatically. Rerun setup to copy the updated personality into Continue, preserving any manual Continue configuration changes first.

### Font and theme

Edit the `:root` section at the top of `ui/style.css`. Font family, base size, relative sizes, weights, line spacing, and theme colors live there.

Consolas is preferred when installed, with monospace fallbacks. The base size is `13px`. Change `--font-weight-emphasis` to `700` for bold labels and headings, or `400` for regular weight. Refresh with **Ctrl+F5** after changing frontend files.

### Memory

The CLI and web interface share one memory store for the installation. Separate browser tabs do not have isolated conversation histories, even though generated files use chat IDs.

`memory/graph.json` stores messages, `memory/summary.txt` stores older context, and `memory/files.json` stores attachment metadata. This is conversation storage, not a knowledge graph.

By default, after more than 20 chat pairs, the app attempts to summarize older messages and keep the latest 10 pairs intact. Summarization is a separate model request and can use provider quota. If it fails or returns unusable content, full history stays in place. Summaries can lose detail.

### Automatic selection

Local classification is the default. To enable a separate model request for classification, add this to `core/litellm.env` and restart:

```bash
HAZAR_LLM_CLASSIFIER="1"
```

This uses provider quota and falls back to local checks if classification fails. Classifier deployments are configured in `core/routerHook.py`.

### Another gateway, including OmniRoute

The clients can use another compatible chat-completions endpoint. Set these server-side values in `core/litellm.env`:

```bash
HAZAR_PROXY_URL="http://127.0.0.1:PORT/v1/chat/completions"
HAZAR_PROXY_KEY="replace-with-gateway-key"
```

Replace `PORT`, the path, and the key with the gateway's actual settings. Configure compatible model aliases in that gateway too. Restart the web backend; new CLI processes read the new values. Rerun setup if Continue should use the same endpoint.

These settings redirect client requests; they do not install or configure OmniRoute. `start.sh all` still starts the bundled LiteLLM service. Provider credentials stay on the server, outside browser JavaScript.

### Optional systemd service

On a Linux environment with user systemd support:

```bash
systemctl --user daemon-reload
systemctl --user enable --now litellm.service
systemctl --user status litellm.service
```

The generated service starts only the gateway with `core/config.yaml`. It does not start the UI or GGUF servers. Avoid running it alongside startup-script management of the same gateway. Stop and disable it before returning to the regular startup flow:

```bash
systemctl --user disable --now litellm.service
```

## Cleanup

```bash
python3 cleanup.py
```

Normal cleanup removes logs, editor backups, Python caches, and the generated `codebase.md` file. Memory, output files, models, and external skills remain.

```bash
python3 cleanup.py --all
```

**`--all` also deletes `memory/` and `output/`.** Save any generated files needed later, and stop services before cleanup. For memory alone, use `python3 query.py --clear-memory`.

## When something goes wrong

### The browser says localhost refused to connect

First check the UI log:

```bash
tail -n 80 core/ui.log
```

A “started” line only means the process was launched; it can still exit immediately. After stopping services, run the backend directly to see its error:

```bash
bash kill.sh
python3 ui/server.py
```

This tests UI startup; chat replies still need a running gateway. Close the foreground server, then use `bash start.sh all` once the problem is fixed. For a remote container or Codespace, open its forwarded port `5000` rather than the host's unrelated localhost address.

### A model returns 404, 401, or repeated errors

Check `core/litellm.log`, verify the provider key, and run `python3 findModels.py`. Update model identifiers and remove unavailable deployments from `core/config.yaml`, then restart. Retries can help temporary failures; they cannot fix invalid credentials or permanently unavailable models.

If a reply has already started, the app does not silently replay it on another model. Partial output stays visible and the prompt is restored for another attempt.

### No skill appears

Check the exact path and capitalization: `~/.claude/skills/<name>/SKILL.md`. Folder names must use letters, numbers, underscores, or hyphens. Run `--list-skills`, check which Linux account runs the backend, and refresh the browser. For Ponytail, check the root link to the nested skill file.

### No download link appears

A greeting, a small block, an unfinished fence, an unsafe filename, or a failed reply will not produce a download. A block must meet `MIN_FILE_CHARACTERS`; a long prose response alone does not count as a generated file.

### Fonts or styles look unchanged

Use **Ctrl+F5** (refresh) to bypass the browser cache. Consolas must be installed on the machine displaying the page; otherwise the next available font is used.

## Start small

Begin with one working cloud provider or one local model, a short greeting, and no skill. Add attachments, memory, and task-specific skills once that basic path works. Keep prompts clear, save useful generated files, and check important code before running it. Morpheus can help with the work; the final decisions still belong to the person building it.
