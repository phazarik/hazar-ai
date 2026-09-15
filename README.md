# Prachu-GPT: Optimize LLM usage

A local workspace to run, route, and interact with large language models. It acts as a smart proxy that routes requests to the fastest or smartest available free models, caches memory locally, and supports running native `.gguf` files.

## Setting up

**Clone** the repository and a sample skill set.
```bash
git clone git@github.com:phazarik/prachu-gpt.git
mkdir -p ~/.claude/skills
git clone https://github.com/nidhinjs/prompt-master.git ~/.claude/skills/prompt-master
```

**Install** LiteLLM and the required dependencies inside a conda environment with Python 3.11 or above. 
> This setup does not work with Python 3.10 or below.

```bash
conda create -n llm python=3.11 -y
conda activate llm
pip install 'litellm[proxy]' websockets requests rich pyfiglet tqdm
pip install "llama-cpp-python[server]" ## For using local models
pip install aider-chat llm ## Extra tools for later
```

**Collect free API keys** from different LLM providers. A few examples are listed below.
- [OpenRouter](https://openrouter.ai/): A single endpoint to access dozens of open-weight models.
- [Google AI Studio](https://aistudio.google.com/?authuser=1): Access to Gemini models.
- [GroqCloud](https://console.groq.com/keys): High-speed inference for fast models.
- [Tavily API Platform](https://app.tavily.com/home): Search API used by agents to browse the web.

**Write the API keys** to the environment file: `core/litellm.env`.
```bash
touch core/litellm.env
```
```text
OPENROUTER_API_KEY=sk-or-v1-XXXXXXXXXXXX
GEMINI_API_KEY=AQ.XXXXXXXXXXXX
GROQ_API_KEY=gsk_XXXXXXXXXXXX
TAVILY_API_KEY=tvly-dev-XXXXXXXXXXXX
```
**Customize the list of models** according to the available models from the relevant API keys. Run the included helper script to see exactly which models the keys unlock.
```bash
python3 findModels.py
python3 findModels.py --search llama
```
Pick the preferred models from the output and add them to `core/config.yaml`. The proxy organizes models into two main groups: `fast` (quick, everyday tasks) and `smart` (complex reasoning and coding). Update the `model_list` section with the new choices. Add the correct provider prefix (`openrouter/`, `gemini/`, or `groq/`) right before the model ID from the script output.

Example of adding a Llama model to the smart tier:
```yaml
model_list:
  - model_name: smart
    litellm_params:
      model: groq/llama-3.3-70b-versatile
      api_key: os.environ/GROQ_API_KEY
```
**Run the setup** script to link configurations and binaries automatically.

```bash
python3 setup.py
```
## Usage

**Start the proxy:** Run the start script to boot the LiteLLM proxy in the background on port 4000. It reads the API keys and handles the routing.
```bash
./start.sh
```
**Command line interface:** Ask questions directly from the terminal. The router will automatically pick a fast or smart model based on the complexity of the query.
```bash
python3 query.py --query "Write a python script to parse JSON."
python3 query.py --model fast --query "Quick question..."
```
**Web UI:** A local chat interface is included. Start the server and open `http://localhost:5000` in a browser.
```bash
python3 ui/server.py
```
**Load local models:** Drop any `.gguf` file into the `model/` directory and start the local server. The proxy will automatically route requests to it when the local model tier is requested.
```bash
./startLocal.sh
```
**Stop services:** Kill the background proxy when finished.
```bash
./kill.sh
```
