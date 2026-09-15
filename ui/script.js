// =============================================================================
// Frontend Logic Core
// Manages DOM interactions, markdown rendering, toolbars, file attachments, 
// skill fetching, and Server-Sent Events (SSE) streaming with the backend.
// =============================================================================

// Stores local files loaded via FileReader before they are sent to the proxy
let attachedFileContents = [];

// Toolbar State Variables
let selectedModel = "auto";
let optimizeTokens = false;
let memoryEnabled = true;

// Initialize standard event listeners once the DOM tree is fully constructed
document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("customLogo").addEventListener("change", loadLogo);
    document.getElementById("fileInput").addEventListener("change", attachFiles);
    
    // Proxy the visible button click to the hidden file input element
    document.getElementById("attachBtn").addEventListener("click", () => {
        document.getElementById("fileInput").click();
    });
    
    document.getElementById("sendBtn").addEventListener("click", sendQuery);
    
    // Trigger submission on Enter, while allowing Shift+Enter for newlines
    document.getElementById("queryInput").addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendQuery();
        }
    });

    // ---------------------------------------------------------
    // Toolbar Event Bindings
    // ---------------------------------------------------------

    // 1. Model Selector Buttons
    document.querySelectorAll(".tool-group button[data-model]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
            document.querySelectorAll(".tool-group button[data-model]").forEach(b => b.classList.remove("active"));
            e.currentTarget.classList.add("active");
            selectedModel = e.currentTarget.getAttribute("data-model");
        });
    });

    // 2. Token Optimization Toggle Button
    const optBtn = document.getElementById("optimizeTokensBtn");
    optBtn.addEventListener("click", () => {
        optimizeTokens = !optimizeTokens;
        optBtn.classList.toggle("active", optimizeTokens);
        optBtn.innerHTML = `<i class="bi bi-lightning-charge"></i> Optimize Tokens: ${optimizeTokens ? "ON" : "OFF"}`;
    });

    // 3. Memory Toggle Button
    const memBtn = document.getElementById("toggleMemoryBtn");
    memBtn.addEventListener("click", () => {
        memoryEnabled = !memoryEnabled;
        memBtn.classList.toggle("active", memoryEnabled);
        memBtn.innerHTML = `<i class="bi bi-cpu"></i> Memory: ${memoryEnabled ? "ON" : "OFF"}`;
    });

    // 4. Fetch and Populate Available Skills from Backend
    const skillSelector = document.getElementById("skillSelector");
    if (skillSelector) {
        fetch("/api/skills")
            .then(res => res.json())
            .then(data => {
                if (data.skills) {
                    data.skills.forEach(skill => {
                        const opt = document.createElement("option");
                        opt.value = skill;
                        opt.textContent = skill;
                        skillSelector.appendChild(opt);
                    });
                }
            })
            .catch(err => appendLog("Failed to load available system skills.", true));
    }
});

// Reads an uploaded image file and dynamically swaps the UI header logo
function loadLogo(event) {
    const file = event.target.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = (e) => {
            const img = document.getElementById("logoImg");
            img.src = e.target.result;
            img.style.display = "block";
            document.querySelector(".logo-label").style.display = "none";
        };
        reader.readAsDataURL(file);
    }
}

// Iterates through selected context files and loads their text contents into memory
function attachFiles(event) {
    const files = event.target.files;
    const list = document.getElementById("fileList");
    
    list.textContent = "";
    attachedFileContents = [];

    Array.from(files).forEach((file) => {
        const reader = new FileReader();
        reader.onload = (e) => {
            attachedFileContents.push({ name: file.name, content: e.target.result });
            list.textContent += `[${file.name} LOADED] `;
        };
        reader.readAsText(file);
    });
}

// Appends timestamped diagnostic messages to the right-hand log panel
function appendLog(text, isError = false) {
    const logs = document.getElementById("logs");
    const entry = document.createElement("div");
    entry.className = "log-entry";
    
    if (isError) entry.style.color = "red";
    
    const now = new Date().toLocaleTimeString('en-US', { hour12: false });
    entry.textContent = `[${now}] ${text}`;
    
    logs.appendChild(entry);
    logs.scrollTop = logs.scrollHeight;
}

// Creates the HTML structure for a new chat bubble in the history panel with a timestamp
function createMsgBox(role) {
    const history = document.getElementById("history");
    const div = document.createElement("div");
    div.className = `msg ${role}`;
    
    const label = document.createElement("div");
    label.className = "msg-label";
    
    // Generate the current time tag e.g. [23:15:14]
    const now = new Date().toLocaleTimeString('en-US', { hour12: false });
    
    // Structure with distinct label and time span
    label.innerHTML = `<span class="role-name">> ${role.toUpperCase()}</span> <span class="time-tag">[${now}]</span>`;
    
    const content = document.createElement("div");
    content.className = "msg-content";
    
    div.appendChild(label);
    div.appendChild(content);
    history.appendChild(div);
    history.scrollTop = history.scrollHeight;
    
    return content;
}

// =============================================================================
// Core Network Handler & SSE Stream Management
// =============================================================================
async function sendQuery() {
    const queryInput = document.getElementById("queryInput");
    const bufferIcon = document.getElementById("loadingBuffer");
    const skillSelector = document.getElementById("skillSelector");
    const query = queryInput.value.trim();
    
    if (!query) return;

    // 1. Render the user's prompt immediately
    const neoBox = createMsgBox("neo");
    neoBox.textContent = query;
    queryInput.value = "";
    
    if (bufferIcon) bufferIcon.style.display = "inline-block";
    
    // 2. Format the payload and apply optional token stripping
    let combinedQuery = query;
    if (attachedFileContents.length > 0) {
        combinedQuery += "\n\nContext files:\n";
        attachedFileContents.forEach((f) => {
            let content = f.content;
            if (optimizeTokens) {
                // Strips empty lines and trailing indentation to conserve tokens
                content = content.split("\n")
                    .map(line => line.trimEnd())
                    .filter(line => line.length > 0)
                    .join("\n");
            }
            combinedQuery += `\n--- FILE: {f.name} ---\n{content}\n--- END ---\n`;
        });
        attachedFileContents = [];
        document.getElementById("fileList").textContent = "NO FILES ATTACHED.";
    }

    const morpheusBox = createMsgBox("morpheus");

    // 3. Dispatch request via Server-Sent Events (SSE)
    try {
        const resp = await fetch("/api/query", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ 
                query: combinedQuery, 
                model: selectedModel, 
                noMemory: !memoryEnabled,
                skill: skillSelector ? skillSelector.value : ""
            })
        });
        
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let reply = "";
        let buffer = "";
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) {
                if (bufferIcon) bufferIcon.style.display = "none";
                break;
            }
            
            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split("\n\n");
            buffer = parts.pop();
            
            parts.exports = parts.forEach((part) => {
                const lines = part.split("\n");
                let eventType = "message";
                let data = "";
                
                lines.forEach((line) => {
                    if (line.startsWith("event: ")) eventType = line.slice(7).trim();
                    if (line.startsWith("data: ")) data = line.slice(6);
                });
                
                if (!data) return;

                if (eventType === "log") {
                    appendLog(data);
                }
		else if (eventType === "token") {
                    try {
                        reply += JSON.parse(data);
                    }
		    catch (e) {
                        reply += data; 
                    }
                    
                    morpheusBox.innerHTML = marked.parse(reply);
                    morpheusBox.querySelectorAll("pre code").forEach((block) => {
                        hljs.highlightElement(block);
                    });

                    document.getElementById("history").scrollTop = document.getElementById("history").scrollHeight;
                }
		else if (eventType === "done") {
                    if (bufferIcon) bufferIcon.style.display = "none";
                    try {
                        const stats = JSON.parse(data);
                        const pct = stats.maxTokens > 0 ? Math.min(100, (stats.totalTokens / stats.maxTokens) * 100).toFixed(1) : 0;
                        document.getElementById("statsText").textContent = `Model: ${stats.model} | Usage: ${stats.totalTokens}/${stats.maxTokens} (${pct}%)`;
                        document.getElementById("tokBarFill").style.width = `${pct}%`;
                    }
		    catch(err) {
                        appendLog("Failed to parse runtime stats", true);
                    }
                }
		else if (eventType === "error") {
                    if (bufferIcon) bufferIcon.style.display = "none";
                    appendLog(`ERROR: ${data}`, true);
                }
            });
        }
    }
    catch(e) {
        if (bufferIcon) bufferIcon.style.display = "none";
        appendLog("ERR: CONNECTION LOST.", true);
    }
}
