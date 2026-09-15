# Prachu-GPT: LLM Workspace

A local workspace designed to run, route, and interact with large language models. It acts as a smart proxy that forwards requests to the fastest or most capable free models available, compresses memory locally to save tokens, and supports running native `.gguf` files.

## Setting up

First, pull the repository and a sample skill set to the local machine.
```bash
git clone git@github.com:phazarik/prachu-gpt.git
mkdir -p ~/.claude/skills
git clone [https://github.com/nidhinjs/prompt-master.git](https://github.com/nidhinjs/prompt-master.git) ~/.claude/skills/prompt-master
```
Install LiteLLM and the necessary network dependencies inside a conda environment using **Python 3.11 or higher**.
```bash
conda create -n llm python=3.11 -y
conda activate llm
pip install "litellm[proxy]" "llama-cpp-python[server]" websockets requests rich pyfiglet tqdm 
```
Gather API keys from standard LLM providers (e.g., OpenRouter, Google AI Studio, GroqCloud, Tavily). Write these API keys to the environment file located at `core/litellm.env`.
```
OPENROUTER_API_KEY=sk-or-v1-XXXXXXXXXXXX
GEMINI_API_KEY=AQ.XXXXXXXXXXXX
GROQ_API_KEY=gsk_XXXXXXXXXXXX
TAVILY_API_KEY=tvly-dev-XXXXXXXXXXXX
```
Run the included helper script to discover which models the provided keys unlock.
```bash
python3 findModels.py
```
Update the `model_list` section in `core/config.yaml` with the preferred models from the script output. The proxy organizes models into two primary tiers: `fast` (for everyday, lightweight tasks) and `smart` (for complex reasoning). Finally, execute the setup script to link configurations and binaries automatically.
```bash
python3 setup.py
```

## Usage

Start the proxy server and all associated background services:
```bash
bash start.sh          # or
bash start.sh fresh    # -> clears previous memory history and starts a completely new session
```

### Command line interface (CLI)

Interact directly via the terminal. The intelligent router automatically classifies your prompt complexity and routes it to the optimal tier:
```
python3 query.py --query "Write a python script to parse JSON."
python3 query.py --model fast --query "Quick syntax check..."
python3 query.py --skill prompt-master --query "Refactor this module."
```
### Web dashboard UI

Open your browser and navigate to `http://localhost:5000`. The web interface includes:
- **Model control panel**: Manually pin queries to `Auto`, `Fast`, `Smart`, or `Local` tiers.
- **Skill injector**: Select downloaded skills directly from `~/.claude/skills` via the dropdown menu.
- **Token optimization toggle**: Automatically strips redundant whitespace and empty lines from attached context files to protect your context window.
- **Persistent memory toggle**: Ephemerally toggle conversational memory on or off per request.

### Stopping services
Gracefully terminate background daemons and proxy servers:
```
./kill.sh
```

## Important nuances & troubleshooting

### Handling model deprecations & 404 errors
-   **The issue:** Cloud providers frequently deprecate model endpoints (e.g., Google phasing out older Gemini 2.5 checkpoints in favor of 3.x series).
-   **The solution:** If you encounter `404 Not Found` errors in your proxy logs, run `python3 findModels.py`, copy active model IDs, and update both `core/config.yaml` and `core/routerHook.py` to target active identifiers (e.g., `gemini/gemini-3.5-flash-lite`, `gemini/gemini-3.1-pro-preview`).

### Managing provider overloads & fallbacks (502 Errors)

-**The issue:** Free-tier endpoints (like OpenRouter open-weights or Nvidia acceleration nodes) frequently return `Service temporarily overloaded` or `502 Bad Gateway` errors.   
- **The solution:** Prachu-GPT handles this via `router_settings` in `core/config.yaml`. When a model throws an error or hits rate limits (`allowed_fails: 1`), the proxy places that specific deployment on a temporary cooldown and seamlessly cascades through the remaining models in the group, shifting down or up across tiers as specified by your `fallbacks` rules.

### Skill directory integration
- Custom skills must reside inside `~/.claude/skills/<skill-name>/SKILL.md`. The `lib/skillLoader.py` module automatically scans this directory to dynamically populate the CLI and Web UI select dropdowns.

## Explanations
Here is a breakdown of how the whole workspace operates from start to finish.
```text
.
├── core
│   ├── apiKeys.sh
│   ├── config.yaml
│   ├── continueConfig.yaml
│   ├── litellm.env
│   ├── litellm.service
│   └── routerHook.py
├── lib
│   ├── __init__.py
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

When a query is entered into the terminal or the web interface, it is not sent directly to OpenAI or Google. Instead, the request is intercepted by a local background service running on port 4000. This proxy manager acts as a central switchboard.

If the model is requested as `auto`, a lightweight classifier takes a preliminary pass over the query. It categorizes the text to determine if it is a simple structural task (FAST) or a complex logic puzzle requiring deeper reasoning (SMART). Once categorized, the proxy dynamically rewrites the model parameter and forwards the prompt to an available, load-balanced API key defined in the environment files.

Memory management occurs parallel to this. Sending massive conversation histories back and forth wastes tokens and slows down generation. Token bloat is avoided by pushing older messages through a background summarization routine. The system takes the older context, crushes it down into dense bullet points, and injects it back into the payload as a hidden system prompt. This keeps the AI fully aware of past instructions without burning through the contextual limits of the active models.
