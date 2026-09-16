// =============================================================================
// Frontend Logic Core
// =============================================================================

// Configure Markdown parser to render LaTeX math equations natively
marked.use(window.markedKatex({
    throwOnError: false, // Prevents a single missing bracket from breaking the whole chat rendering
    output: 'html'
}));

// Global variables to hold the state of the application.
// 'let' for variables that will change, and 'const' for constants.
let attachedFileContents = [];
let selectedModel = "auto";
let optimizeTokens = false;
let memoryEnabled = true;

// State variables specifically for managing the LLM text generation
let currentAbortController = null; // Allows us to cancel an ongoing network request
let isGenerating = false;          // Acts as a lock so we don't send multiple requests at once
let isManuallyResized = false;     // Tracks if the user dragged the text box to a custom size

// -----------------------------------------------------------------------------
// DOMContentLoaded Event
// Think of this like 'if __name__ == "__main__":' in Python. 
// It ensures the browser has fully read the HTML file and built the webpage 
// structure (the DOM) before we try to attach scripts or find elements.
// -----------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
    
    // --- File Attachment Logic ---
    // 'document.getElementById' grabs an HTML element by its ID.
    // 'addEventListener' tells the browser to run a function when a specific action happens.
    document.getElementById("fileInput").addEventListener("change", attachFiles);
    
    // We hide the actual ugly HTML <input type="file"> and use a nice styled button instead.
    // When the nice button is clicked, we use JavaScript to silently click the hidden input.
    document.getElementById("attachBtn").addEventListener("click", () => {
        document.getElementById("fileInput").click();
    });

    // --- Drag & Drop Logic ---
    // This allows users to drag files from their desktop onto the app.
    const dropZone = document.querySelector(".app");
    let dragCounter = 0; // Helps track if we drag over nested elements

    // 'e.preventDefault()' stops the browser's default behavior. 
    // By default, a browser tries to open a dropped file (like a PDF or image) in a new tab.
    // We prevent that so we can read it into our chat instead.
    dropZone.addEventListener("dragenter", (e) => {
        e.preventDefault();
        dragCounter++;
        dropZone.classList.add("drag-active"); // Adds a CSS class to visually highlight the screen
    });
    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault(); // Necessary to allow dropping
    });
    dropZone.addEventListener("dragleave", (e) => {
        e.preventDefault();
        dragCounter--;
        if (dragCounter <= 0) {
            dragCounter = 0;
            dropZone.classList.remove("drag-active"); // Removes the visual highlight
        }
    });
    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dragCounter = 0;
        dropZone.classList.remove("drag-active");
        
        // If files were dropped, pass them to our processing function
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            addFiles(e.dataTransfer.files);
        }
    });

    // --- Sending Queries ---
    document.getElementById("sendBtn").addEventListener("click", () => {
        if (isGenerating) {
            // If the bot is currently typing, the button acts as a "Stop" button.
            if (currentAbortController) currentAbortController.abort();
        } else {
            // Otherwise, it acts as a "Send" button.
            sendQuery();
        }
    });
    
    // Allow pressing "Enter" to send, but "Shift+Enter" to just make a new line.
    const queryInput = document.getElementById("queryInput");
    queryInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault(); // Prevents adding a rogue newline character before sending
            if (!isGenerating) sendQuery();
        }
    });

    // --- Auto-growing Text Box ---
    // Expands the text box vertically as the user types a long paragraph.
    const TEXTAREA_MAX_HEIGHT = 260;
    const autoGrowInput = () => {
        if (isManuallyResized) return; // Ignore auto-grow if the user manually dragged the box height
        
        // Temporarily reset height to calculate the true required height (scrollHeight)
        queryInput.style.height = "auto"; 
        const next = Math.min(queryInput.scrollHeight, TEXTAREA_MAX_HEIGHT);
        queryInput.style.height = `${next}px`;
        
        // Add a scrollbar only if the text exceeds our maximum height
        queryInput.style.overflowY = queryInput.scrollHeight > TEXTAREA_MAX_HEIGHT ? "auto" : "hidden";
    };
    queryInput.addEventListener("input", autoGrowInput);
    queryInput.addEventListener("paste", () => setTimeout(autoGrowInput, 0));

    // --- Manual Resize Handle ---
    // Allows the user to click and drag the divider to make the text input larger.
    const resizeHandle = document.getElementById("chatResizeHandle");

    if (resizeHandle && queryInput) {
        let dragging = false;
        let startY = 0;
        let startHeight = 0;

        const onPointerMove = (e) => {
            if (!dragging) return;
            // The browser screen coordinates put Y=0 at the top. 
            // Dragging upwards means a smaller Y value.
            const delta = startY - e.clientY; 
            const newHeight = Math.max(80, startHeight + delta); // Enforce minimum height
            
            queryInput.style.height = `${newHeight}px`;
            isManuallyResized = true; // Lock out the auto-grow feature
        };
        const stopDragging = () => {
            dragging = false;
            document.body.classList.remove("resizing-chat"); // Restores normal text selection
        };

        // When the user clicks down on the handle, initialize the dragging state
        resizeHandle.addEventListener("mousedown", (e) => {
            dragging = true;
            startY = e.clientY;
            startHeight = queryInput.getBoundingClientRect().height;
            document.body.classList.add("resizing-chat"); // Prevents text selection while dragging
            e.preventDefault();
        });
        
        // Attach these to the whole 'document' so the drag doesn't break if the mouse moves off the handle
        document.addEventListener("mousemove", onPointerMove);
        document.addEventListener("mouseup", stopDragging);
    }

    // --- Toolbar Buttons ---
    
    // Model Selector: Loop through all buttons with a 'data-model' attribute
    document.querySelectorAll(".tool-group button[data-model]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
            // Remove 'active' class from all buttons, then add it to the clicked one
            document.querySelectorAll(".tool-group button[data-model]").forEach(b => b.classList.remove("active"));
            e.currentTarget.classList.add("active");
            selectedModel = e.currentTarget.getAttribute("data-model");
        });
    });

    // Token Optimization Toggle
    const optBtn = document.getElementById("optimizeTokensBtn");
    optBtn.addEventListener("click", () => {
        optimizeTokens = !optimizeTokens; // Flip the boolean state
        optBtn.classList.toggle("active", optimizeTokens); // Update UI
        optBtn.innerHTML = `<i class="bi bi-lightning-charge"></i> Optimize Tokens: ${optimizeTokens ? "ON" : "OFF"}`;
    });

    // Memory Toggle
    const memBtn = document.getElementById("toggleMemoryBtn");
    memBtn.addEventListener("click", () => {
        memoryEnabled = !memoryEnabled;
        memBtn.classList.toggle("active", memoryEnabled);
        memBtn.innerHTML = `<i class="bi bi-cpu"></i> Memory: ${memoryEnabled ? "ON" : "OFF"}`;
    });

    // Clear Memory Button ---
    const clearBtn = document.getElementById("clearMemoryBtn");
    if (clearBtn) {
        clearBtn.addEventListener("click", () => {
            // Ask for confirmation before wiping everything
            if (confirm("Are you sure you want to delete all chat history?")) {
                
                // Send a POST request to the existing backend endpoint
                fetch("/api/clear", { method: "POST" })
                    .then(res => res.json())
                    .then(data => {
                        if (data.ok) {
                            // Wipe the visual chat bubbles from the screen
                            document.getElementById("history").innerHTML = "";
                            appendLog("Memory wiped successfully.");
                        }
                    })
                    .catch(err => appendLog("Failed to clear backend memory.", true));
            }
        });
    }

    // Fetch available skills dynamically from the Python server API
    const DEFAULT_SKILL = "prompt-master";
    const skillSelector = document.getElementById("skillSelector");
    if (skillSelector) {
        // 'fetch' makes an HTTP request. '.then()' handles the asynchronous response.
        fetch("/api/skills")
            .then(res => res.json()) // Parse the raw response into a JSON object
            .then(data => {
                if (data.skills) {
                    data.skills.forEach(skill => {
                        // Create a new dropdown option for each skill found
                        const opt = document.createElement("option");
                        opt.value = skill;
                        opt.textContent = skill;
                        skillSelector.appendChild(opt);
                    });
                    // Set default if it exists in the list
                    if (data.skills.includes(DEFAULT_SKILL)) {
                        skillSelector.value = DEFAULT_SKILL;
                    }
                }
            })
            .catch(err => appendLog("Failed to load available system skills.", true));
    }

    // --- Restore visual chat history ---
    // Make a GET request to our new Python endpoint
    fetch("/api/history")
        .then(res => res.json())
        .then(data => {
            if (data.history && data.history.length > 0) {
                data.history.forEach(msg => {
                    // Skip 'system' messages (like the memory summaries or Morpheus instructions)
                    if (msg.role === "system") return;
                    
                    // The backend saves roles as 'user' and 'assistant'
                    // The frontend CSS expects 'neo' and 'morpheus'
                    const displayRole = msg.role === "assistant" ? "morpheus" : "neo";
                    const msgBox = createMsgBox(displayRole);
                    
                    if (displayRole === "morpheus") {
                        // If it's the AI, parse the markdown and sanitize it
                        const parsedHTML = marked.parse(msg.content);
                        msgBox.innerHTML = window.DOMPurify ? DOMPurify.sanitize(parsedHTML) : parsedHTML;
                        
                        // Apply syntax highlighting to code blocks
                        msgBox.querySelectorAll("pre code").forEach((block) => {
                            hljs.highlightElement(block);
                        });
                    } else {
                        // If it's the user, just insert plain text
                        msgBox.textContent = msg.content;
                    }
                });
                
                // Jump to the bottom of the chat after everything loads
                const historyContainer = document.getElementById("history");
                historyContainer.scrollTop = historyContainer.scrollHeight;
            }
        })
        .catch(err => console.log("No previous history found or error loading."));
});


// -----------------------------------------------------------------------------
// File Processing Functions
// -----------------------------------------------------------------------------

// A set of allowed file extensions to prevent reading heavy binary files (like .png or .zip) as text.
const TEXT_FILE_EXTENSIONS = new Set([
    "txt", "md", "markdown", "json", "yaml", "yml", "toml", "ini", "cfg", "conf",
    "py", "js", "jsx", "ts", "tsx", "html", "htm", "css", "scss", "sass",
    "sh", "bash", "zsh", "ps1", "bat",
    "c", "h", "cpp", "hpp", "cc", "cs", "java", "kt", "go", "rs", "rb", "php",
    "sql", "xml", "csv", "tsv", "log", "env", "gitignore", "dockerfile",
    "vue", "svelte", "r", "swift", "scala", "lua", "pl", "gradle", "makefile"
]);

function isLikelyTextFile(file) {
    if (file.type && file.type.startsWith("text/")) return true;
    if (file.type === "application/json" || file.type === "application/javascript" || file.type === "application/xml") return true;
    const ext = file.name.includes(".") ? file.name.split(".").pop().toLowerCase() : "";
    return TEXT_FILE_EXTENSIONS.has(ext);
}

// Updates the little list of attached files shown above the text box
function renderFileList() {
    const list = document.getElementById("fileList");
    list.textContent = ""; 
    
    if (attachedFileContents.length === 0) {
        list.textContent = "NO FILES ATTACHED.";
        return;
    }
    
    attachedFileContents.forEach((f, idx) => {
        // Create a visual "chip" for each file
        const chip = document.createElement("span");
        chip.className = "file-chip";
        chip.textContent = `[${f.name}] `;

        // Create the 'x' button to remove the file
        const remove = document.createElement("a");
        remove.href = "#";
        remove.className = "file-chip-remove";
        remove.textContent = "x";
        remove.addEventListener("click", (e) => {
            e.preventDefault();
            attachedFileContents.splice(idx, 1); // Remove the file from the array
            renderFileList(); // Re-draw the list
        });

        chip.appendChild(remove);
        list.appendChild(chip);
    });
}

// Reads files sequentially from the user's hard drive into browser memory
function addFiles(fileList) {
    const incoming = Array.from(fileList);
    const rejected = [];

    incoming.forEach((file) => {
        if (!isLikelyTextFile(file)) {
            rejected.push(file.name);
            return;
        }
        
        // FileReader is a built-in API to read local files.
        // It operates asynchronously so it doesn't freeze the UI on huge files.
        const reader = new FileReader();
        reader.onload = (e) => {
            // This runs when the file finishes loading
            attachedFileContents.push({ name: file.name, content: e.target.result });
            renderFileList();
        };
        reader.onerror = () => appendLog(`Failed to read file: ${file.name}`, true);
        reader.readAsText(file);
    });

    if (rejected.length > 0) {
        appendLog(`Skipped non-text file(s): ${rejected.join(", ")}`, true);
    }
}

function attachFiles(event) {
    addFiles(event.target.files);
    // Reset the input value so selecting the exact same file twice in a row still fires the 'change' event
    event.target.value = ""; 
}


// -----------------------------------------------------------------------------
// UI Utilities
// -----------------------------------------------------------------------------

// Adds a timestamped message to the log panel on the right side of the screen.
function appendLog(text, isError = false) {
    const logs = document.getElementById("logs");
    const entry = document.createElement("div");
    entry.className = "log-entry";
    
    if (isError) entry.style.color = "red";
    
    const now = new Date().toLocaleTimeString('en-US', { hour12: false });
    entry.textContent = `[${now}] ${text}`;
    
    logs.appendChild(entry);
    logs.scrollTop = logs.scrollHeight; // Auto-scroll logs to bottom
}

// Builds the HTML structure for a new message bubble (either user or AI) in the main chat history.
function createMsgBox(role) {
    const history = document.getElementById("history");
    const div = document.createElement("div");
    div.className = `msg ${role}`;
    
    const label = document.createElement("div");
    label.className = "msg-label";
    
    const now = new Date().toLocaleTimeString('en-US', { hour12: false });
    label.innerHTML = `<span class="role-name">> ${role.toUpperCase()}</span> <span class="time-tag">[${now}]</span>`;
    
    const content = document.createElement("div");
    content.className = "msg-content";
    
    div.appendChild(label);
    div.appendChild(content);
    history.appendChild(div);
    
    history.scrollTop = history.scrollHeight;
    
    return content; // Return the empty content div so we can inject text into it later
}


// -----------------------------------------------------------------------------
// Core Network Handler & SSE Stream Management
// -----------------------------------------------------------------------------

// We use 'async' so we can use 'await' inside. This allows us to pause execution 
// waiting for the network without freezing the browser tab.
async function sendQuery() {
    const queryInput = document.getElementById("queryInput");
    const sendBtn = document.getElementById("sendBtn");
    const attachBtn = document.getElementById("attachBtn");
    const bufferIcon = document.getElementById("loadingBuffer");
    const skillSelector = document.getElementById("skillSelector");
    const historyContainer = document.getElementById("history");
    
    const query = queryInput.value.trim();
    
    // Do nothing if there's no text and no files attached
    if (!query && attachedFileContents.length === 0) return;

    // --- UI Setup for Generation ---
    // Render the user's text on screen immediately
    const neoBox = createMsgBox("neo");
    neoBox.textContent = query;
    queryInput.value = "";
    
    // Reset the text box size to normal
    isManuallyResized = false; 
    queryInput.style.height = "50px"; 
    
    // Lock the UI so the user can't send overlapping requests
    isGenerating = true;
    currentAbortController = new AbortController(); // Used to cancel the fetch request if "Stop" is clicked
    queryInput.disabled = true;
    attachBtn.disabled = true;
    sendBtn.innerHTML = `<i class="bi bi-stop-circle"></i> Stop`;
    if (bufferIcon) bufferIcon.style.display = "inline-block";
    
    // Prep the files to be sent to Python
    const filesPayload = attachedFileContents.map((f) => {
        let content = f.content;
        if (optimizeTokens) {
            // Clean out empty lines to save context limits
            content = content.split("\n")
                .map(line => line.trimEnd())
                .filter(line => line.length > 0)
                .join("\n");
        }
        return { name: f.name, content };
    });
    
    attachedFileContents = []; // Clear attachments now that they are queued for sending
    renderFileList();

    const morpheusBox = createMsgBox("morpheus");

    // --- Network Request ---
    try {
        // We use fetch to hit our Python server. 
        // We pass the AbortController's signal so we can kill the request mid-flight.
        const resp = await fetch("/api/query", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            signal: currentAbortController.signal, 
            body: JSON.stringify({ 
                query: query, 
                files: filesPayload,
                model: selectedModel, 
                noMemory: !memoryEnabled,
                skill: skillSelector ? skillSelector.value : ""
            })
        });
        
        // --- Server-Sent Events (SSE) Parsing ---
        // Instead of waiting for one giant response block, we read the response as a stream of chunks.
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let reply = "";
        let buffer = "";
        
        // This loop runs continuously as long as the server is sending chunks of text
        while (true) {
            const { done, value } = await reader.read();
            if (done) break; // Exit loop when stream is finished
            
            // Decode the raw bytes into text and add it to our buffer
            buffer += decoder.decode(value, { stream: true });
            
            // SSE chunks are separated by double newlines (\n\n)
            const parts = buffer.split("\n\n");
            buffer = parts.pop(); // Keep the last incomplete chunk in the buffer for the next loop
            
            parts.forEach((part) => {
                const lines = part.split("\n");
                let eventType = "message";
                let data = "";
                
                // Parse standard SSE format: "event: [type]\ndata: [content]"
                lines.forEach((line) => {
                    if (line.startsWith("event: ")) eventType = line.slice(7).trim();
                    if (line.startsWith("data: ")) data = line.slice(6);
                });
                
                if (!data) return;

                // --- Handle Event Types ---
                
                if (eventType === "log") {
                    appendLog(data); // Route backend logs straight to the UI log panel
                }
                else if (eventType === "token") {
                    try {
                        reply += JSON.parse(data);
                    }
                    catch (e) {
                        reply += data; 
                    }
                    
                    // Smart Auto-Scroll: Only force the scrollbar down if the user is already at the bottom.
                    // If they scrolled up to read history, don't interrupt them.
                    const isAtBottom = historyContainer.scrollHeight - historyContainer.scrollTop <= historyContainer.clientHeight + 50;
                    
                    // Convert Markdown to HTML
                    const parsedHTML = marked.parse(reply);
                    
                    // Clean the HTML using DOMPurify to prevent malicious script injection.
                    // The fallback you requested to remove is gone; this assumes DOMPurify is loaded.
                    morpheusBox.innerHTML = DOMPurify.sanitize(parsedHTML);
                    
                    if (isAtBottom) {
                        historyContainer.scrollTop = historyContainer.scrollHeight;
                    }
                }
		else if (eventType === "done") {
                    // Apply syntax highlighting to code blocks only once at the very end
                    morpheusBox.querySelectorAll("pre code").forEach((block) => {
                        hljs.highlightElement(block);
                    });

                    // Update token usage bar to show FREE tokens based on true context limits
                    try {
                        const stats = JSON.parse(data);
                        const limit = stats.contextLimit || 8192;
                        const used = stats.totalTokens || 0; // Tracks both prompt and completion tokens
                        
                        const free = Math.max(0, limit - used);
                        const pct = limit > 0 ? Math.min(100, (used / limit) * 100).toFixed(1) : 0;
                        
                        // Update the text and the progress bar fill
                        document.getElementById("statsText").textContent = `Model: ${stats.model} | Free Tokens: ${free.toLocaleString()} (${pct}% used)`;
                        document.getElementById("tokBarFill").style.width = `${pct}%`;
                    }
                    catch(err) {
                        appendLog("Failed to parse runtime stats", true);
                    }
                }
                else if (eventType === "error") {
                    appendLog(`ERROR: ${data}`, true);
                }
            });
        }
    }
    catch(e) {
        // Catch network errors or user-initiated aborts
        if (e.name === 'AbortError') {
            appendLog("Generation stopped by user.", false);
        } else {
            appendLog("ERR: CONNECTION LOST.", true);
        }
    }
    finally {
        // 'finally' runs no matter how the try/catch block exits.
        // This is where we safely unlock the UI and return to a neutral state.
        isGenerating = false;
        currentAbortController = null;
        queryInput.disabled = false;
        attachBtn.disabled = false;
        sendBtn.innerHTML = `<i class="bi bi-send"></i> Send`;
        if (bufferIcon) bufferIcon.style.display = "none";
        
        queryInput.focus(); // Automatically put the cursor back in the text box
    }
}
