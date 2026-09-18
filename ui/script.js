// ----------------------------------------------------------------------------
// Browser interface logic
//
// This connects page controls to Python and renders streaming replies.
// Handles attachments, model/skill choices, memory controls, and resizing.
// Markdown is cleaned before insertion; skill inspection stays plain text.
// Failed or stopped requests restore the prompt and queued attachments.
// ----------------------------------------------------------------------------

// Configure Markdown parser safely (render LaTeX math equations natively)
if (typeof marked !== "undefined" && typeof window.markedKatex === "function") {
    marked.use(
        window.markedKatex({
            throwOnError: false,
            output: "html",
        }),
    );
}

// Global variables to hold the state of the application.
// 'let' for variables that will change, and 'const' for constants.
let attachedFileContents = [];
let selectedModel = "auto";
let optimizeTokens = false;
let memoryEnabled = true;
let visualHistoryCleared = false;
let currentChatId = crypto.randomUUID();

// State variables specifically for managing the LLM text generation
let currentAbortController = null; // Cancels the active network request
let isGenerating = false; // Prevents simultaneous submissions
let isManuallyResized = false; // Tracks if the user dragged the text box to a custom size

// -----------------------------------------------------------------------------
// DOMContentLoaded Event
// Register event handlers after the document is ready.
// It ensures the browser has fully read the HTML file and built the webpage
// structure (the DOM) before event handlers access its elements.
// -----------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
    // --- File Attachment Logic ---
    // 'document.getElementById' grabs an HTML element by its ID.
    // 'addEventListener' tells the browser to run a function when a specific action happens.
    document.getElementById("fileInput").addEventListener("change", attachFiles);

    // The attachment button opens the hidden file input.

    document.getElementById("attachBtn").addEventListener("click", () => {
        document.getElementById("fileInput").click();
    });

    // --- Drag & Drop Logic ---
    // This allows users to drag files from their desktop onto the app.
    const dropZone = document.querySelector(".app");
    let dragCounter = 0; // Tracks nested drag targets

    // 'e.preventDefault()' stops the browser's default behavior.
    // By default, a browser tries to open a dropped file (like a PDF or image) in a new tab.

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

        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            addFiles(e.dataTransfer.files);
        }
    });

    // --- Send and Stop actions ---
    document.getElementById("sendBtn").addEventListener("click", () => {
        if (isGenerating) {
            // If the bot is currently typing, the button acts as a "Stop" button.
            if (currentAbortController) currentAbortController.abort();
        } else {
            // Otherwise, it acts as a "Send" button.
            sendQuery();
        }
    });

    // Allow pressing "Shift+Enter" or "Ctrl+Enter" to send, but regular "Enter" to just make a new line.
    const queryInput = document.getElementById("queryInput");
    queryInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && (e.shiftKey || e.ctrlKey)) {
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

        queryInput.style.overflowY =
            queryInput.scrollHeight > TEXTAREA_MAX_HEIGHT ? "auto" : "hidden";
    };
    queryInput.addEventListener("input", autoGrowInput);
    queryInput.addEventListener("paste", () => setTimeout(autoGrowInput, 0));

    // --- Resize Handles (Mouse & Touch Helpers) ---
    // Extracts coordinates seamlessly whether via standard mouse or touchscreen
    // Pointer events can come from a mouse or touchscreen.
    // Read touch coordinates when available, otherwise use mouse coordinates.
    // Both resize handlers can then share the same position calculations.
    const getClientY = (e) => (e.touches ? e.touches[0].clientY : e.clientY);
    const getClientX = (e) => (e.touches ? e.touches[0].clientX : e.clientX);

    // --- Manual Resize Handle (Text Box) ---
    // Allows the user to click and drag the divider to make the text input larger.
    const chatResizeHandle = document.getElementById("chatResizeHandle");

    if (chatResizeHandle && queryInput) {
        let draggingChat = false;
        let startY = 0;
        let startHeight = 0;

        // Measure movement from the initial drag point, not the last event.
        // Clamp the input height so the prompt box cannot collapse completely.
        const onChatPointerMove = (e) => {
            if (!draggingChat) return;
            const delta = startY - getClientY(e);
            const newHeight = Math.max(50, startHeight + delta); // Enforce minimum height

            queryInput.style.height = `${newHeight}px`;
            isManuallyResized = true; // Lock out the auto-grow feature
        };
        const stopChatDragging = () => {
            draggingChat = false;
            document.body.classList.remove("resizing-chat");
        };

        const startChatDrag = (e) => {
            draggingChat = true;
            startY = getClientY(e);
            startHeight = queryInput.getBoundingClientRect().height;
            document.body.classList.add("resizing-chat"); // Prevents text selection while dragging
            if (!e.touches) e.preventDefault(); // Don't prevent default on touch to avoid passive listener warnings
        };

        chatResizeHandle.addEventListener("mousedown", startChatDrag);
        chatResizeHandle.addEventListener("touchstart", startChatDrag, {
            passive: true,
        });

        document.addEventListener("mousemove", onChatPointerMove);
        document.addEventListener("touchmove", onChatPointerMove, {
            passive: true,
        });

        document.addEventListener("mouseup", stopChatDragging);
        document.addEventListener("touchend", stopChatDragging);
    }

    // --- Manual Resize Handle (Side Panel) ---
    // Resizes the right diagnostic panel horizontally on desktop, or vertically on mobile
    const panelResizeHandle = document.getElementById("panelResizeHandle");
    const rightPanel = document.querySelector(".right-panel");

    if (panelResizeHandle && rightPanel) {
        let draggingPanel = false;
        let startX = 0;
        let startY = 0;
        let startWidth = 0;
        let startHeight = 0;

        // Desktop dragging changes width; mobile dragging changes height.
        // Use the matching axis after the layout switches to stacked panels.
        // Size limits keep both chat and diagnostics usable.
        const onPanelPointerMove = (e) => {
            if (!draggingPanel) return;

            // Check if the CSS media query condition applies (mobile breakpoint)
            const isMobile = window.innerWidth <= 768;

            if (isMobile) {
                // Stacked vertically: dragging UP means larger right panel
                const delta = startY - getClientY(e);
                const newHeight = Math.max(100, startHeight + delta);
                rightPanel.style.height = `${newHeight}px`;
                rightPanel.style.width = ""; // Reset width override
            } else {
                // Side-by-side: dragging LEFT means larger right panel
                const delta = startX - getClientX(e);
                const newWidth = Math.max(200, startWidth + delta);
                rightPanel.style.width = `${newWidth}px`;
                rightPanel.style.height = ""; // Reset height override
            }
        };

        const stopPanelDragging = () => {
            draggingPanel = false;
            document.body.classList.remove("resizing-panel");
        };

        const startPanelDrag = (e) => {
            draggingPanel = true;
            startX = getClientX(e);
            startY = getClientY(e);
            const rect = rightPanel.getBoundingClientRect();
            startWidth = rect.width;
            startHeight = rect.height;
            document.body.classList.add("resizing-panel");
            if (!e.touches) e.preventDefault();
        };

        panelResizeHandle.addEventListener("mousedown", startPanelDrag);
        panelResizeHandle.addEventListener("touchstart", startPanelDrag, {
            passive: true,
        });

        document.addEventListener("mousemove", onPanelPointerMove);
        document.addEventListener("touchmove", onPanelPointerMove, {
            passive: true,
        });

        document.addEventListener("mouseup", stopPanelDragging);
        document.addEventListener("touchend", stopPanelDragging);
    }

    // --- Toolbar Buttons ---

    // Model Selector: Loop through all buttons with a 'data-model' attribute
    document.querySelectorAll(".tool-group button[data-model]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
            // Remove 'active' class from all buttons, then add it to the clicked one
            document
                .querySelectorAll(".tool-group button[data-model]")
                .forEach((b) => b.classList.remove("active"));
            e.currentTarget.classList.add("active");
            selectedModel = e.currentTarget.getAttribute("data-model");
        });
    });

    // Max Tokens Toggle UX
    const limitToggle = document.getElementById("limitTokensToggle");
    const maxTokensInput = document.getElementById("maxTokensInput");
    if (limitToggle && maxTokensInput) {
        limitToggle.addEventListener("change", (e) => {
            maxTokensInput.disabled = !e.target.checked;
            // Optionally dim the input when disabled
            maxTokensInput.style.opacity = e.target.checked ? "1" : "0.5";
        });
    }

    // Welcome Modal Logic
    const welcomeModal = document.getElementById("welcomeModal");
    const closeWelcomeBtn = document.getElementById("closeWelcomeBtn");
    const helpBtn = document.getElementById("helpBtn"); // Reference the new Help button

    if (welcomeModal && closeWelcomeBtn) {
        // Automatically show the modal every time the UI reloads
        welcomeModal.classList.remove("hidden");

        closeWelcomeBtn.addEventListener("click", () => {
            welcomeModal.classList.add("hidden");
        });
    }

    // Help button logic to display the modal whenever the user wants
    if (helpBtn && welcomeModal) {
        helpBtn.addEventListener("click", () => {
            welcomeModal.classList.remove("hidden");
        });
    }

    // Token Optimization Toggle
    const optBtn = document.getElementById("optimizeTokensBtn");
    optBtn.addEventListener("click", () => {
        optimizeTokens = !optimizeTokens; // Flip the boolean state
        optBtn.classList.toggle("active", optimizeTokens); // Update UI
        const optimizationLabel = optimizeTokens ? "ON" : "OFF";
        optBtn.innerHTML =
            '<i class="bi bi-lightning-charge"></i> ' +
            `<span class="btn-text">Optimize: ${optimizationLabel}</span>`;
    });

    // Memory Toggle
    const memBtn = document.getElementById("toggleMemoryBtn");
    memBtn.addEventListener("click", () => {
        memoryEnabled = !memoryEnabled;
        memBtn.classList.toggle("active", memoryEnabled);
        memBtn.innerHTML = `<i class="bi bi-cpu"></i> <span class="btn-text">Memory: ${memoryEnabled ? "ON" : "OFF"}</span>`;
    });

    // Memory Status Check
    const memStatusBtn = document.getElementById("memStatusBtn");
    if (memStatusBtn) {
        memStatusBtn.addEventListener("click", () => {
            fetch("/api/status")
                .then((res) => res.json())
                .then((data) => {
                    appendLog(
                        `Status | Chats: ${data.chats}, Summary: ${data.summaryChars} chars, Cached Files: ${data.cachedFiles}`,
                    );
                })
                .catch((err) => appendLog("Failed to fetch memory status.", true));
        });
    }

    // Clear Chat affects the displayed bubbles only; persistent memory stays intact.
    document.getElementById("clearChatBtn").addEventListener("click", () => {
        visualHistoryCleared = true;
        document.getElementById("history").replaceChildren();
        appendLog("Displayed chat cleared. Memory retained.");
    });

    // Clear Memory Button ---
    const clearBtn = document.getElementById("clearMemoryBtn");
    if (clearBtn) {
        clearBtn.addEventListener("click", () => {
            if (isGenerating) return;
            // Ask for confirmation before wiping everything
            if (confirm("Are you sure you want to delete all chat history?")) {
                // Send a POST request to the existing backend endpoint
                fetch("/api/clear", {
                    method: "POST",
                })
                    .then((res) => res.json())
                    .then((data) => {
                        if (data.ok) {
                            visualHistoryCleared = true;
                            // Wipe the visual chat bubbles from the screen
                            document.getElementById("history").innerHTML = "";
                            appendLog("Memory wiped successfully.");
                        }
                    })
                    .catch((err) => appendLog("Failed to clear backend memory.", true));
            }
        });
    }

    // Fetch available skills dynamically from the Python server API
    const DEFAULT_SKILL = "";
    const skillSelector = document.getElementById("skillSelector");
    // Inspection reads the complete expanded skill and displays it as plain text.
    document.getElementById("viewSkillBtn").addEventListener("click", async () => {
        const name = document.getElementById("skillSelector").value;
        if (!name) {
            appendLog("Select a skill before inspection.");
            return;
        }
        try {
            const response = await fetch(`/api/skill?name=${encodeURIComponent(name)}`);
            const skill = await response.json();
            if (!response.ok) throw new Error(skill.error || "Skill inspection failed");
            document.getElementById("skillDialogTitle").textContent = skill.name;
            document.getElementById("skillDialogText").textContent = skill.content;
            document.getElementById("skillDialog").showModal();
        } catch (error) {
            appendLog(error.message, true);
        }
    });

    if (skillSelector) {
        // 'fetch' makes an HTTP request. '.then()' handles the asynchronous response.
        fetch("/api/skills")
            .then((res) => res.json()) // Parse the raw response into a JSON object
            .then((data) => {
                if (data.skills) {
                    data.skills.forEach((skill) => {
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
            .catch((err) => appendLog("Failed to load available system skills.", true));
    }

    // --- Restore visual chat history ---
    // Read saved history from the backend.
    fetch("/api/history")
        .then((res) => res.json())
        .then((data) => {
            if (!visualHistoryCleared && data.history && data.history.length > 0) {
                data.history.forEach((msg) => {
                    // Skip 'system' messages (like the memory summaries or Morpheus instructions)
                    if (msg.role === "system") return;

                    // The backend saves roles as 'user' and 'assistant'
                    // The frontend CSS expects 'neo' and 'morpheus'
                    const displayRole = msg.role === "assistant" ? "morpheus" : "neo";
                    const msgBox = createMsgBox(displayRole);

                    if (displayRole === "morpheus") {
                        // If it's the AI, parse the markdown and sanitize it
                        // Markdown can contain HTML, so never insert the parser result directly.
                        // DOMPurify removes unsafe markup before it reaches the message box.
                        const parsedHTML = marked.parse(msg.content);
                        if (window.DOMPurify) msgBox.innerHTML = DOMPurify.sanitize(parsedHTML);
                        else msgBox.textContent = msg.content;
                        addReplyCopyButtons(msgBox, msg.content);

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
        .catch((err) => console.log("No previous history found or error loading."));
});

// -----------------------------------------------------------------------------
// File Processing Functions
// -----------------------------------------------------------------------------

// A set of allowed file extensions to prevent reading heavy binary files (like .png or .zip) as text.
const TEXT_FILE_EXTENSIONS = new Set([
    "txt",
    "md",
    "markdown",
    "json",
    "yaml",
    "yml",
    "toml",
    "ini",
    "cfg",
    "conf",
    "py",
    "js",
    "jsx",
    "ts",
    "tsx",
    "html",
    "htm",
    "css",
    "scss",
    "sass",
    "sh",
    "bash",
    "zsh",
    "ps1",
    "bat",
    "c",
    "h",
    "cpp",
    "hpp",
    "cc",
    "cs",
    "java",
    "kt",
    "go",
    "rs",
    "rb",
    "php",
    "sql",
    "xml",
    "csv",
    "tsv",
    "log",
    "env",
    "gitignore",
    "dockerfile",
    "vue",
    "svelte",
    "r",
    "swift",
    "scala",
    "lua",
    "pl",
    "gradle",
    "makefile",
]);

// Check text MIME types first, then known source-file extensions.
function isLikelyTextFile(file) {
    if (file.type && file.type.startsWith("text/")) return true;
    if (
        file.type === "application/json" ||
        file.type === "application/javascript" ||
        file.type === "application/xml"
    )
        return true;
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
// Read likely text files and keep each name with its decoded contents.
// FileReader finishes asynchronously, so update chips after each read.
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
            attachedFileContents.push({
                name: file.name,
                content: e.target.result,
            });
            renderFileList();
        };
        reader.onerror = () => appendLog(`Failed to read file: ${file.name}`, true);
        reader.readAsText(file);
    });

    if (rejected.length > 0) {
        appendLog(`Skipped non-text file(s): ${rejected.join(", ")}`, true);
    }
}

// Pass the native input selection to the shared attachment reader.
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

    const now = new Date().toLocaleTimeString("en-US", {
        hour12: false,
    });
    entry.textContent = `[${now}] ${text}`;

    logs.appendChild(entry);
    logs.scrollTop = logs.scrollHeight; // Auto-scroll logs to bottom
}

// Copy plain source text, with a fallback for browsers without Clipboard API access.
async function copyReplyText(text) {
    if (window.isSecureContext && navigator.clipboard && navigator.clipboard.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return;
        } catch (error) {
            // Try the selection-based fallback if clipboard permission is unavailable.
        }
    }
    const activeElement = document.activeElement;
    const selection = window.getSelection();
    const ranges = [];
    if (selection) {
        for (let index = 0; index < selection.rangeCount; index++) {
            ranges.push(selection.getRangeAt(index).cloneRange());
        }
    }
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.className = "clipboard-fallback";
    textarea.setAttribute("readonly", "");
    document.body.appendChild(textarea);
    try {
        textarea.focus({ preventScroll: true });
        textarea.select();
        textarea.setSelectionRange(0, textarea.value.length);
        if (!document.execCommand("copy")) throw new Error("Clipboard copy failed");
    } finally {
        textarea.remove();
        if (activeElement && activeElement.focus) activeElement.focus({ preventScroll: true });
        if (selection) {
            selection.removeAllRanges();
            ranges.forEach((range) => selection.addRange(range));
        }
    }
}

// Keep copy controls outside the source text and provide accessible icon-only feedback.
function createReplyCopyButton(getText, label) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "reply-copy-btn";
    button.title = label;
    button.setAttribute("aria-label", label);
    const icon = document.createElement("i");
    icon.className = "bi bi-copy";
    icon.setAttribute("aria-hidden", "true");
    button.appendChild(icon);
    button.addEventListener("click", async () => {
        button.disabled = true;
        try {
            await copyReplyText(getText());
            icon.className = "bi bi-check2";
            button.title = "Copied";
            button.setAttribute("aria-label", "Copied");
        } catch (error) {
            icon.className = "bi bi-exclamation-triangle";
            button.title = "Copy failed; try again";
            button.setAttribute("aria-label", "Copy failed; try again");
            appendLog("Could not copy to clipboard. Please try again.", true);
        } finally {
            button.disabled = false;
            setTimeout(() => {
                icon.className = "bi bi-copy";
                button.title = label;
                button.setAttribute("aria-label", label);
            }, 1500);
        }
    });
    return button;
}

// Add one control for the original Markdown reply and one for each displayed code block.
function addReplyCopyButtons(msgBox, markdown) {
    msgBox.dataset.markdownSource = markdown;
    const label = msgBox.parentElement.querySelector(".msg-label");
    if (!label.querySelector(".reply-copy-btn")) {
        label.appendChild(createReplyCopyButton(
            () => msgBox.dataset.markdownSource, "Copy Markdown reply",
        ));
    }
    msgBox.querySelectorAll("pre").forEach((pre) => {
        if (pre.parentElement.classList.contains("reply-code-block")) return;
        const wrapper = document.createElement("div");
        wrapper.className = "reply-code-block";
        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(pre);
        wrapper.appendChild(createReplyCopyButton(
            () => (pre.querySelector("code") || pre).textContent, "Copy block",
        ));
    });
}

// Builds the HTML structure for a new message bubble (either user or AI) in the main chat history.
// Create one message container and return its content element for rendering.
function createMsgBox(role) {
    const history = document.getElementById("history");
    const div = document.createElement("div");
    div.className = `msg ${role}`;

    const label = document.createElement("div");
    label.className = "msg-label";

    const now = new Date().toLocaleTimeString("en-US", {
        hour12: false,
    });
    label.innerHTML = `<span class="role-name">> ${role.toUpperCase()}</span> <span class="time-tag">[${now}]</span>`;

    const content = document.createElement("div");
    content.className = "msg-content";

    div.appendChild(label);
    div.appendChild(content);
    history.appendChild(div);

    history.scrollTop = history.scrollHeight;

    return content; // Return the content element for later streamed text
}

// -----------------------------------------------------------------------------
// Core Network Handler & SSE Stream Management
// -----------------------------------------------------------------------------

// Send the request and read its stream without blocking page interaction.
async function sendQuery() {
    const queryInput = document.getElementById("queryInput");
    if (isGenerating) return;
    const sendBtn = document.getElementById("sendBtn");
    const attachBtn = document.getElementById("attachBtn");
    const bufferIcon = document.getElementById("loadingBuffer");
    const skillSelector = document.getElementById("skillSelector");
    const historyContainer = document.getElementById("history");
    const limitTokensToggle = document.getElementById("limitTokensToggle");
    const maxTokensInput = document.getElementById("maxTokensInput");

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
    queryInput.style.height = "120px";

    // Lock the UI so the user can't send overlapping requests
    isGenerating = true;
    currentAbortController = new AbortController(); // Used to cancel the fetch request if "Stop" is clicked
    queryInput.disabled = true;
    attachBtn.disabled = true;
    sendBtn.innerHTML = `<i class="bi bi-stop-circle"></i> <span class="btn-text">Stop</span>`;
    if (bufferIcon) bufferIcon.style.display = "inline-block";

    // Prep the files to be sent to Python
    const filesPayload = attachedFileContents.map((f) => {
        let content = f.content;
        // Keep attachment text unchanged here.
        // Safe JSON shortening and deduplication run on the Python backend.
        return {
            name: f.name,
            content,
        };
    });

    // Keep a separate attachment copy while the request runs.
    // Error paths restore it so retrying does not lose attached files.
    const queuedFiles = attachedFileContents.slice();
    attachedFileContents = []; // Clear attachments now that they are queued for sending
    renderFileList();

    const morpheusBox = createMsgBox("morpheus");

    // --- Network Request ---
    try {
        const resp = await fetch("/api/query", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            signal: currentAbortController.signal,
            body: JSON.stringify({
                query: query || "Analyze the attached files.",
                chatId: currentChatId,
                optimizeTokens: optimizeTokens,
                files: filesPayload,
                model: selectedModel,
                noMemory: !memoryEnabled,
                skill: skillSelector ? skillSelector.value : "",
                maxTokens:
                    limitTokensToggle && limitTokensToggle.checked
                        ? parseInt(maxTokensInput.value)
                        : null,
            }),
        });

        // --- Server-Sent Events (SSE) Parsing ---

        if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);
        const reader = resp.body.getReader();
        let terminalEvent = false;
        // HTTP chunks do not always line up with SSE event boundaries.
        // The decoder preserves split UTF-8 characters; buffer keeps partial events.
        // Only frames ending in a blank line are parsed during the read loop.
        const decoder = new TextDecoder();
        let reply = "";
        let buffer = "";

        // This loop runs continuously as long as the server is sending chunks of text
        while (true) {
            const { done, value } = await reader.read();
            if (done) break; // Exit loop when stream is finished

            // Decode the raw bytes into text and append it to the event buffer
            buffer += decoder.decode(value, {
                stream: true,
            });

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

                if (eventType === "meta") currentChatId = JSON.parse(data).chatId;
                else if (eventType === "artifacts") {
                    const manifest = JSON.parse(data);
                    const links = manifest.artifacts || [];
                    if (links.length === 0) return;
                    const downloads = document.createElement("div");
                    downloads.className = "output-downloads";
                    links.forEach((file) => {
                        const link = document.createElement("a");
                        link.href = file.url;
                        link.download = file.name.split("/").pop();
                        link.textContent = `Download ${file.name}`;
                        downloads.appendChild(link);
                    });
                    morpheusBox.parentElement.appendChild(downloads);
                    appendLog(`Outputs: output/${manifest.chatId}/${manifest.requestId}`);
                } else if (eventType === "log") {
                    appendLog(data); // Route backend logs straight to the UI log panel
                } else if (eventType === "token") {
                    try {
                        reply += JSON.parse(data);
                    } catch (e) {
                        reply += data;
                    }

                    // Follow new text only while history is already near the bottom.
                    // Reading an older message should not force a jump back down.
                    const isAtBottom =
                        historyContainer.scrollHeight - historyContainer.scrollTop <=
                        historyContainer.clientHeight + 50;

                    // Convert Markdown to HTML
                    const parsedHTML = marked.parse(reply);

                    // Clean the HTML using DOMPurify to prevent malicious script injection.
                    morpheusBox.innerHTML = DOMPurify.sanitize(parsedHTML);
                    addReplyCopyButtons(morpheusBox, reply);

                    if (isAtBottom) {
                        historyContainer.scrollTop = historyContainer.scrollHeight;
                    }
                } else if (eventType === "done") {
                    terminalEvent = true;
                    // Apply syntax highlighting to code blocks only once at the very end
                    morpheusBox.querySelectorAll("pre code").forEach((block) => {
                        hljs.highlightElement(block);
                    });

                    // Update token usage bar to show remaining tokens based on the reported or estimated context limit
                    try {
                        const stats = JSON.parse(data);
                        const limit = stats.contextLimit || 8192;
                        const used = stats.totalTokens || 0; // Tracks both prompt and completion tokens

                        const free = Math.max(0, limit - used);
                        const pct = limit > 0 ? Math.min(100, (used / limit) * 100).toFixed(1) : 0;

                        // Update the text and the progress bar fill
                        document.getElementById("statsText").textContent =
                            `Model: ${stats.model} | Free Tokens: ${free.toLocaleString()} (${pct}% used)`;
                        document.getElementById("tokBarFill").style.width = `${pct}%`;
                    } catch (err) {
                        appendLog("Failed to parse runtime stats", true);
                    }
                } else if (eventType === "error") {
                    terminalEvent = true;
                    appendLog(`ERROR: ${data}`, true);
                    if (!reply) morpheusBox.textContent = `Generation failed: ${data}`;
                    queryInput.value = query;
                    attachedFileContents = queuedFiles;
                    renderFileList();
                }
            });
        }
        // A stream without done/error is incomplete even if some text arrived.
        if (!terminalEvent) throw new Error("Stream ended before completion.");
    } catch (e) {
        queryInput.value = query;
        attachedFileContents = queuedFiles;
        renderFileList();
        if (!morpheusBox.textContent)
            morpheusBox.textContent = "Generation incomplete. Request restored for retry.";
        // Catch network errors or user-initiated aborts
        if (e.name === "AbortError") {
            appendLog("Generation stopped by user.", false);
        } else {
            appendLog("ERR: CONNECTION LOST.", true);
        }
    // Always release the generation lock and restore controls.
    // This runs after success, a network error, or Stop-button cancellation.
    } finally {
        // 'finally' runs no matter how the try/catch block exits.
        // Restore controls after success, failure, or cancellation.
        isGenerating = false;
        currentAbortController = null;
        queryInput.disabled = false;
        attachBtn.disabled = false;
        sendBtn.innerHTML = `<i class="bi bi-send"></i> <span class="btn-text">Send</span>`;
        if (bufferIcon) bufferIcon.style.display = "none";

        queryInput.focus(); // Automatically put the cursor back in the text box
    }
}
