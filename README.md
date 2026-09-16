# Hazar-AI: optimize free LLM usage

![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg) ![Proxy](https://img.shields.io/badge/proxy-LiteLLM-orange.svg) ![Local Models](https://img.shields.io/badge/inference-llama.cpp-yellow.svg) ![UI](https://img.shields.io/badge/interface-CLI%20%7C%20Web-green.svg)

Running top-tier models gets expensive fast, and free tiers constantly hit rate limits. Hazar-ai fixes that without paid subscriptions. This setup lets queries run through _hazars_ of tokens across free models without hitting a wall.

Instead of manually juggling API keys, copying prompts across browser tabs, or losing chat history when a model fails, this tool provides a single local proxy that can:
- Route requests between fast and smart model groups;
- Automatically switch between providers when a deployment fails or hits a rate limit;
- Compress older conversation history to preserve context;
- Inject reusable skills into prompts;
- Expose the same backend through the CLI, Web UI, and VS Code.
- Run local models alongside cloud models.

## Repository structure

The repository is organized into four main parts:
* `core/` contains the LiteLLM configuration, routing logic, API keys, and service configuration.
* `lib/` contains the memory and skill-management components.
* `ui/` contains the browser interface.
* The top-level scripts handle installation, model discovery, starting/stopping services, and CLI queries.

```text
├── core
│   ├── apiKeys.sh
│   ├── config.yaml
│   ├── continueConfig.yaml
│   ├── litellm.env
│   ├── litellm.service
│   └── routerHook.py
├── lib
│   ├── memoryManager.py
│   └── skillLoader.py
├── findModels.py
├── setup.py
├── start.sh
├── query.py
├── kill.sh
└── ui
    ├── index.html
    ├── script.js
    ├── server.py
    └── style.css
```
The main services use fixed local ports:

| Service                |   Port | Purpose               |
|:---------------------- |:------ |:--------------------- |
| LiteLLM proxy          | `4000` | Central LLM gateway   |
| Local llama.cpp server | `8000` | Optional local models |
| Web UI                 | `5000` | Browser interface     |


## Setting up [one-time]

1. Clone the repository and install the starter skill set:
	```bash
	git clone git@github.com:phazarik/hazar-ai.git
	mkdir -p ~/.claude/skills
	git clone https://github.com/nidhinjs/prompt-master.git ~/.claude/skills/prompt-master
	```
	Here, `prompt-master` is a Claude Code skill repository that provides reusable prompt-engineering guidance and workflows.

2. Create a fresh conda environment with **Python 3.11 or higher**:
	```bash
	conda create -n llm python=3.11 -y
	conda activate llm
	pip install "litellm[proxy]" "llama-cpp-python[server]" websockets requests rich pyfiglet tqdm
	```
	> Python 3.10 and older are not supported because the LiteLLM proxy hooks require Python 3.11+.

3. Create an environment file to keep the required API keys.
	```bash
	touch core/litellm.env
	```
	This setup uses API keys from the following providers:
	-   [OpenRouter](https://openrouter.ai/) — access to multiple LLM providers through a single API.
	-   [Google AI Studio](https://aistudio.google.com/) — Gemini models.
	-   [Groq](https://console.groq.com/) — fast inference for supported open models.
	-   [Tavily](https://tavily.com/) — web search API.
	
	In this example, the `litellm.env` file looks like:
	```text
	OPENROUTER_API_KEY=sk-or-v1-XXXXXXXXXXXX
	GEMINI_API_KEY=AIzaSyXXXXXXXXXXXX
	GROQ_API_KEY=gsk_XXXXXXXXXXXX
	TAVILY_API_KEY=tvly-dev-XXXXXXXXXXXX
	LITELLM_MASTER_KEY=sk-anything
	```
	`LITELLM_MASTER_KEY` is the shared authentication key used by the local components to communicate with the LiteLLM proxy. The CLI, Web UI, memory manager, and Continue configuration use this key when connecting to the proxy.
	
4. Find out the models and set up the configurations (specify which models to use). The available models can change frequently as providers add, remove, or rate-limit free endpoints. Check the currently available models with:
	```bash
	python3 findModels.py
	```
	Update `core/config.yaml` to choose which models belong to the `fast` and `smart` groups. The two groups are intended for different workloads:
	- `fast`: quick questions, syntax checks, and simple completions.
	- `smart`: deeper reasoning, debugging, and multi-step tasks.

	LiteLLM can automatically move between deployments when a model fails or reaches a rate limit.
	
5. Run the setup script after configuring.
	```bash
	python3 setup.py
	```
	This performs the repository-specific setup required to initialize the environment. It checks that the required configuration files and dependencies are present, creates the necessary symbolic links, sets executable permissions on scripts, configures the background services, and generates the Continue configuration from the provided settings. It also prepares the required directories and local configuration so that the CLI, Web UI, memory manager, LiteLLM proxy, and other components can work together without further manual configuration.

## Usage

Start the proxy and associated services with:
```bash
bash start.sh          # or,
bash start.sh fresh    # start with a completely new conversation history
bash start.sh offline  # local .gguf models only — no cloud API calls
```
`start.sh` always kills any previously running proxy/UI/local-model processes first, so it's safe to re-run at any time.
### Command-line interface

The CLI sends requests through the local LiteLLM proxy. Some example usage are listed below.
```bash
python3 query.py --query "Write a python script to parse JSON."
python3 query.py --model fast --query "Quick syntax check..."
python3 query.py --skill prompt-master --query "Refactor this module."
```
When no model is specified, the router classifies the request and selects an appropriate model group automatically.

### Web UI

Open the following link on a web-browser.
```text
http://localhost:5000
```

The web UI provides:

* **Model control:** select `Auto`, `Fast`, `Smart`, or `Local`.
* **Skill injection:** select skills from `~/.claude/skills`.
* **Token optimization:** remove redundant whitespace and empty lines from attached context files.
* **Persistent memory:** enable or disable conversational memory for individual requests.

### Integration with VS Code

The `setup.py` script generates the Continue configuration at `~/.continue/config.yaml`. To use it, install the Continue extension in VS Code and select `local-router`. Coding prompts, inline edits, and completions are then routed through the local LiteLLM proxy on port `4000`.

Finally, to stop the proxy and background services:
```bash
bash kill.sh
```
## Customization

### Local models
This setup can run local `.gguf` models using `llama.cpp`. Place one or more `.gguf` models in:
```text
models/
```
Then start the local server(s):
```bash
bash start.sh local
```
`start.sh` scans `models/` for every `.gguf` file and starts one `llama.cpp` server per model, on sequential ports starting at `8000`. It also regenerates `core/config.local.generated.yaml`, registering each model under a `local:<filename-without-extension>` alias; the first model found is additionally kept under the plain `local` alias so existing `--model local` usage keeps working.

If you only have — or only want to use — local models (e.g. fully offline, no API keys needed), run:
```bash
bash start.sh offline
```
This starts only the local model server(s) and points the LiteLLM proxy at `core/config.local.generated.yaml`, so cloud providers are never contacted. Use `--model local` (or `--model local:<name>` for a specific model) from the CLI or Web UI.

### Skills
A skill is a directory containing instructions that can be injected into a conversation to give the model specialized behavior or knowledge. Skills are stored under:
```text
~/.claude/skills/<skill-name>/SKILL.md
```
The skill loader scans this directory and makes discovered skills available to both the CLI and web UI. Additional reference material can be placed in the skill's `references/` directory. `lib/skillLoader.py` limits oversized skill instructions to keep them from consuming excessive context.

### Personality
The Web UI defines the model persona in `ui/server.py`. The default configuration refers to the user as `Neo` and the assistant as `Morpheus`:
```python
system_msg = {
    "role": "system",
    "content": "You are Morpheus. The user is Neo. "
    "You have perfect memory of all previous turns provided in this context. "
    "Format your responses cleanly in Markdown. "
    "Do not start your response with a large header."
}
```
This can be changed to customize the default system prompt.

## How things work

A request passes through several components before the response reaches the user.

- **Automatic routing:** When `Auto` is selected, `core/routerHook.py` intercepts the request and classifies its difficulty. A lightweight model is first asked whether the task is simple or complex. Simple requests are sent to the `fast` group, while multi-step reasoning, debugging, and similar tasks are sent to the `smart` group. If the classification request fails, the router falls back to keyword-based classification.

- **Provider fallback:** The LiteLLM proxy manages multiple deployments within each model group. If a deployment returns a rate-limit or gateway error, it is temporarily cooled down, and the proxy continues with another available deployment according to the fallback configuration in `core/config.yaml`. This allows the system to continue operating even when individual free-tier endpoints become unavailable.

- **Skills and context:** `lib/skillLoader.py` discovers skills and loads their instructions and reference material. For CLI requests, `query.py` combines the user prompt with the selected skills, attached files, and previous conversation context. The resulting request is sent to the LiteLLM proxy on port `4000`.

- **Conversational memory:** `lib/memoryManager.py` keeps conversation context available across model changes. Conversation turns are stored in `memory/graph.json`.  Once a conversation becomes long, the most recent messages are kept intact while older messages are compressed into `memory/summary.txt`. The summary is then included in subsequent requests, reducing context usage while retaining important decisions, errors, and other information. The memory manager also fingerprints attached files so that identical files do not need to be repeatedly inserted into the context.

- **Web interface:** `ui/server.py` provides the browser interface and handles streaming responses. The frontend consists of one HTML, one CSS, and one JavaScript file. Completed conversations are passed to the memory manager so that the Web UI can maintain context in the same way as the CLI.

## Troubleshooting

### Model deprecations and 404 errors

Cloud providers regularly deprecate or rename model endpoints. A deprecated model may therefore produce a `404 Not Found` error in the proxy logs. First check the currently available models:
```bash
python3 findModels.py
```
Then update the model identifiers in:
```text
core/config.yaml
core/routerHook.py
```

### Provider overloads and 502 errors
Free-tier endpoints can temporarily return errors such as:
```text
Service temporarily overloaded
502 Bad Gateway
```
The fallback configuration in `core/config.yaml` allows LiteLLM to temporarily disable failing deployments and continue with other models. If failures persist, check which deployments are currently available with:
```bash
python3 findModels.py
```

### Skills are not appearing
Make sure the skill follows the expected structure:
```text
~/.claude/skills/<skill-name>/SKILL.md
```
The directory is scanned dynamically by `lib/skillLoader.py`. Restarting the Hazar-ai services after adding or modifying a skill ensures that the updated configuration is loaded.