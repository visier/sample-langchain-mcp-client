let isProcessing = false;
let availablePromptsList = [];

// Load server info when page loads
document.addEventListener('DOMContentLoaded', function() {
    loadServerInfo();
});

async function loadServerInfo() {
    try {
        const response = await fetch('/server-info');
        const data = await response.json();
        if (data.success) {
            document.getElementById('serverUrl').textContent = data.serverUrl;
            document.getElementById('modelName').textContent = data.modelName;
            renderToolsList(data.tools);
            availablePromptsList = data.prompts || [];
            renderPromptsList(availablePromptsList);
            populatePromptSelect(availablePromptsList);
            updateAskButtonState();
        } else {
            document.getElementById('serverUrl').textContent = 'Server URL not available';
            document.getElementById('modelName').textContent = 'Model info not available';
            document.getElementById('toolsContainer').innerHTML = '<div class="error">Tools info not available</div>';
            document.getElementById('promptsContainer').innerHTML = '<div class="error">Prompts info not available</div>';
        }
    } catch (error) {
        console.error('Error loading server info:', error);
        document.getElementById('serverUrl').textContent = 'Error loading server info';
        document.getElementById('modelName').textContent = 'Error loading model info';
        document.getElementById('toolsContainer').innerHTML = '<div class="error">Error loading tools info</div>';
        document.getElementById('promptsContainer').innerHTML = '<div class="error">Error loading prompts info</div>';
    }
}

function renderPromptsList(prompts) {
    const container = document.getElementById('promptsContainer');

    if (!prompts || prompts.length === 0) {
        container.innerHTML = '<div class="no-tools">No prompts available</div>';
        return;
    }

    let html = '';
    prompts.forEach((prompt, index) => {
        const promptId = `prompt-${index}`;
        const description = (prompt.description || 'No description available').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const argsHtml = formatPromptArgumentsForDisplay(prompt.arguments);
        html += `
            <div class="prompt-item">
                <div class="prompt-header" onclick="togglePrompt('${promptId}')">
                    <span class="prompt-name">${(prompt.name || 'Unnamed Prompt').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</span>
                    <span class="prompt-expand-icon" id="${promptId}-icon">▶</span>
                </div>
                <div class="prompt-details" id="${promptId}-details">
                    <div class="prompt-details-content">
                        <div class="prompt-description">${description}</div>
                        ${argsHtml}
                    </div>
                </div>
            </div>
        `;
    });

    container.innerHTML = html;
}

function formatPromptArgumentsForDisplay(argumentsList) {
    if (!argumentsList || argumentsList.length === 0) {
        return '<div class="prompt-schema"><div class="prompt-schema-title">Parameters</div><div class="prompt-schema-content">No parameters</div></div>';
    }
    const rows = argumentsList.map(arg => {
        const name = (arg.name || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const desc = (arg.description || '—').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const required = arg.required === true ? 'Yes' : (arg.required === false ? 'No' : '—');
        return `<tr><td class="prompt-arg-name">${name}</td><td>${desc}</td><td class="prompt-arg-required">${required}</td></tr>`;
    }).join('');
    return `
        <div class="prompt-schema">
            <div class="prompt-schema-title">Parameters</div>
            <div class="prompt-schema-content">
                <table class="prompt-args-table">
                    <thead><tr><th>Name</th><th>Description</th><th>Required</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        </div>
    `;
}

/** Fill the "Use prompt" dropdown with options from the server prompts list. */
function populatePromptSelect(prompts) {
    const select = document.getElementById('promptSelect');
    if (!select) return;
    select.innerHTML = '<option value="">None</option>';
    if (prompts && prompts.length > 0) {
        prompts.forEach((prompt, index) => {
            const opt = document.createElement('option');
            opt.value = prompt.name || '';
            opt.textContent = prompt.name || 'Unnamed Prompt';
            select.appendChild(opt);
        });
    }
    select.addEventListener('change', onPromptSelectChange);
    onPromptSelectChange();
}

/** Show or hide prompt parameter inputs when the selected prompt changes. */
function onPromptSelectChange() {
    const select = document.getElementById('promptSelect');
    const paramsSection = document.getElementById('promptParamsSection');
    const paramsContainer = document.getElementById('promptParamsContainer');
    if (!select || !paramsSection || !paramsContainer) return;

    const promptName = select.value;
    paramsSection.style.display = 'none';
    paramsContainer.innerHTML = '';

    if (!promptName) return;

    const prompt = availablePromptsList.find(p => (p.name || '') === promptName);
    if (!prompt || !prompt.arguments || prompt.arguments.length === 0) return;

    paramsSection.style.display = 'block';
    prompt.arguments.forEach(arg => {
        const name = arg.name || '';
        const desc = arg.description || '';
        const required = arg.required === true;
        const id = 'promptParam_' + name.replace(/\s+/g, '_');
        const label = document.createElement('label');
        label.className = 'prompt-param-label';
        label.htmlFor = id;
        label.textContent = name + (required ? ' *' : '');
        if (desc) label.title = desc;
        const input = document.createElement('input');
        input.type = 'text';
        input.id = id;
        input.className = 'form-input prompt-param-input';
        input.placeholder = desc || name;
        input.dataset.paramName = name;
        input.dataset.required = required ? '1' : '0';
        const wrap = document.createElement('div');
        wrap.className = 'prompt-param-row';
        wrap.appendChild(label);
        wrap.appendChild(input);
        paramsContainer.appendChild(wrap);
    });
}

/** Read current prompt parameter values from the form. Returns { paramName: value } or {}. */
function getPromptArgumentsFromInputs() {
    const promptName = document.getElementById('promptSelect').value;
    if (!promptName) return null;
    const prompt = availablePromptsList.find(p => (p.name || '') === promptName);
    if (!prompt || !prompt.arguments || prompt.arguments.length === 0) return {};
    const out = {};
    prompt.arguments.forEach(arg => {
        const name = arg.name || '';
        const el = document.querySelector('.prompt-param-input[data-param-name="' + name.replace(/"/g, '\\"') + '"]');
        if (el) out[name] = (el.value || '').trim();
    });
    return out;
}

/** Return true if the selected prompt has no required params or all required params have a value. */
function areRequiredPromptParamsFilled() {
    const promptName = document.getElementById('promptSelect').value;
    if (!promptName) return true;
    const prompt = availablePromptsList.find(p => (p.name || '') === promptName);
    if (!prompt || !prompt.arguments) return true;
    return prompt.arguments.filter(a => a.required === true).every(a => {
        const el = document.querySelector('.prompt-param-input[data-param-name="' + (a.name || '').replace(/"/g, '\\"') + '"]');
        return el && (el.value || '').trim() !== '';
    });
}

/** Enable or disable the Send question button based on question content and processing state. */
function updateAskButtonState() {
    const question = (document.getElementById('questionInput').value || '').trim();
    const btn = document.getElementById('askButton');
    if (btn) btn.disabled = isProcessing || question === '';
}

/** Fetch the selected prompt (with params) from the server and put its content into the question box. */
async function loadPromptIntoQuestion() {
    const promptName = document.getElementById('promptSelect').value || '';
    if (!promptName) {
        alert('Please select a prompt first.');
        return;
    }
    if (!areRequiredPromptParamsFilled()) {
        alert('Please fill in all required prompt parameters.');
        return;
    }
    const loadBtn = document.getElementById('loadPromptButton');
    if (loadBtn) {
        loadBtn.disabled = true;
        loadBtn.textContent = 'Loading…';
    }
    try {
        const promptArguments = getPromptArgumentsFromInputs();
        const response = await fetch('/get-prompt-content', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: promptName, promptArguments: promptArguments || {} })
        });
        const data = await response.json();
        if (data.success && data.promptContent != null) {
            document.getElementById('questionInput').value = data.promptContent;
            updateAskButtonState();
        } else {
            alert(data.error || 'Failed to load prompt.');
        }
    } catch (e) {
        alert('Failed to load prompt: ' + e.message);
    } finally {
        if (loadBtn) {
            loadBtn.disabled = false;
            loadBtn.textContent = 'Load prompt into question';
        }
    }
}

function togglePrompt(promptId) {
    const details = document.getElementById(`${promptId}-details`);
    const icon = document.getElementById(`${promptId}-icon`);

    if (details) {
        if (details.classList.contains('expanded')) {
            details.classList.remove('expanded');
            if (icon) icon.textContent = '\u25B6';
        } else {
            details.classList.add('expanded');
            if (icon) icon.textContent = '\u25BC';
        }
    }
}

function renderToolsList(tools) {
    const container = document.getElementById('toolsContainer');
    
    if (!tools || tools.length === 0) {
        container.innerHTML = '<div class="no-tools">No tools available</div>';
        return;
    }

    let html = '';
    tools.forEach((tool, index) => {
        const toolId = `tool-${index}`;
        html += `
            <div class="tool-item">
                <div class="tool-header" onclick="toggleTool('${toolId}')">
                    <span class="tool-name">${tool.name || 'Unnamed Tool'}</span>
                    <span class="tool-expand-icon" id="${toolId}-icon">▶</span>
                </div>
                <div class="tool-details" id="${toolId}-details">
                    <div class="tool-details-content">
                        <div class="tool-description-section">
                            <div class="tool-description-title">Description</div>
                            <div class="tool-description">
                                ${tool.description || 'No description available'}
                            </div>
                        </div>
                        <div class="tool-schema">
                            <div class="tool-schema-title">Parameters Schema</div>
                            <div class="tool-schema-content"><pre>${formatSchemaForDisplay(tool.args_schema)}</pre></div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    });

    container.innerHTML = html;
}

function toggleTool(toolId) {
    const details = document.getElementById(`${toolId}-details`);
    const icon = document.getElementById(`${toolId}-icon`);
    
    if (details) {
        if (details.classList.contains('expanded')) {
            details.classList.remove('expanded');
            if (icon) icon.textContent = '\u25B6'; // Right-pointing triangle
        } else {
            details.classList.add('expanded');
            if (icon) icon.textContent = '\u25BC'; // Down-pointing triangle
        }
    } else {
        console.error('Could not find details element for:', toolId);
    }
}

function formatSchemaForDisplay(schema) {
    if (!schema) return 'No schema available';
    try {
        if (typeof schema === 'string') {
            // If it's a string representation of a Python dict, convert it to JSON
            if (schema.startsWith("{") && schema.includes("'properties'")) {
                // Replace Python dict syntax with JSON syntax
                let jsonString = schema
                    .replace(/'/g, '"')  // Replace single quotes with double quotes
                    .replace(/None/g, 'null')  // Replace Python None with null
                    .replace(/True/g, 'true')  // Replace Python True with true
                    .replace(/False/g, 'false');  // Replace Python False with false
                
                try {
                    const parsed = JSON.parse(jsonString);
                    const formatted = JSON.stringify(parsed, null, 2);
                    return formatted.trim();  // Remove extra whitespace
                } catch (e) {
                    console.error('Error parsing converted JSON:', e);
                    return schema.trim(); // Return original if conversion fails
                }
            } else {
                // Try to parse as regular JSON
                try {
                    const parsed = JSON.parse(schema);
                    return JSON.stringify(parsed, null, 2).trim();
                } catch (e) {
                    return schema.trim();
                }
            }
        } else {
            // It's already an object, just stringify it
            const formatted = JSON.stringify(schema, null, 2);
            return formatted.trim();  // Remove extra whitespace
        }
    } catch (error) {
        console.error('Error formatting schema for display:', error);
        return 'Error formatting schema';
    }
}

document.getElementById('questionInput').addEventListener('input', updateAskButtonState);
document.getElementById('questionInput').addEventListener('keydown', function(e) {
    // Submit on Ctrl+Enter or Cmd+Enter; allow Enter for new lines otherwise
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !isProcessing) {
        e.preventDefault();
        askAgent();
    }
});

async function askAgent() {
    if (isProcessing) return;

    const question = (document.getElementById('questionInput').value || '').trim();
    if (!question) {
        alert('Please enter a question or load a prompt into the question box first.');
        return;
    }

    // Update UI to show processing state
    isProcessing = true;
    document.getElementById('askButton').disabled = true;
    document.getElementById('spinner').style.display = 'block';
    document.getElementById('loadingText').style.display = 'block';
    document.getElementById('thinkingStatus').textContent = 'Agent is analyzing your request...';
    document.getElementById('responseStatus').textContent = 'Processing...';
    document.getElementById('thinkingArea').value = '';
    document.getElementById('responseArea').value = '';

    try {
        // POST question to /ask and get response (streaming or JSON)
        const response = await fetch('/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: question })
        });

        if (!response.ok || !response.body) {
            const err = await response.text();
            throw new Error(err || 'Request failed');
        }

        const contentType = response.headers.get('Content-Type') || '';
        if (contentType.includes('text/event-stream')) {
            // --- Streaming path: read SSE and update UI as chunks arrive ---
            const thinkingEl = document.getElementById('thinkingArea');
            const thinkingStatusEl = document.getElementById('thinkingStatus');
            const responseAreaEl = document.getElementById('responseArea');
            const responseStatusEl = document.getElementById('responseStatus');
            let thinkingParts = [];
            const decoder = new TextDecoderStream();
            const reader = response.body.pipeThrough(decoder).getReader();
            let buffer = '';
            try {
                // Read stream until done
                while (true) {
                    const { value, done } = await reader.read();
                    if (done) break;
                    buffer += value || '';
                    const lines = buffer.split('\n\n');
                    buffer = lines.pop() || '';
                    for (const chunk of lines) {
                        const match = chunk.match(/^data:\s*(.+)$/m);
                        if (!match) continue;
                        try {
                            const data = JSON.parse(match[1].trim());
                            if (data.type === 'thinking' && data.content) {
                                // Append reasoning step and scroll into view
                                thinkingParts.push(data.content);
                                thinkingEl.value = thinkingParts.join('\n\n');
                                thinkingStatusEl.textContent = 'Reasoning in progress...';
                                thinkingEl.scrollTop = thinkingEl.scrollHeight;
                            } else if (data.type === 'done') {
                                // Final event: set thinking, response, and stop spinner
                                if (data.thinking) thinkingEl.value = data.thinking;
                                thinkingStatusEl.textContent = data.success ? 'Reasoning complete' : 'Error occurred';
                                responseAreaEl.value = data.success ? (data.response || '') : ('Error: ' + (data.error || 'Unknown error'));
                                responseStatusEl.textContent = data.success ? 'Response ready' : 'Request failed';
                                isProcessing = false;
                                document.getElementById('spinner').style.display = 'none';
                                document.getElementById('loadingText').style.display = 'none';
                                updateAskButtonState();
                            }
                        } catch (e) {
                            console.warn('SSE parse:', e);
                        }
                    }
                }
                // Handle any final event left in the buffer
                if (buffer) {
                    const match = buffer.match(/^data:\s*(.+)$/m);
                    if (match) {
                        try {
                            const data = JSON.parse(match[1].trim());
                            if (data.type === 'done') {
                                if (data.thinking) thinkingEl.value = data.thinking;
                                thinkingStatusEl.textContent = data.success ? 'Reasoning complete' : 'Error occurred';
                                responseAreaEl.value = data.success ? (data.response || '') : ('Error: ' + (data.error || ''));
                                responseStatusEl.textContent = data.success ? 'Response ready' : 'Request failed';
                            }
                        } catch (e) { /* ignore */ }
                    }
                }
            } finally {
                // Always stop spinner when stream ends (or errors) so next request can run
                isProcessing = false;
                document.getElementById('spinner').style.display = 'none';
                document.getElementById('loadingText').style.display = 'none';
                updateAskButtonState();
            }
        } else {
            throw new Error('Expecting streaming response, got: ' + contentType);
        }
    } catch (error) {
        // Network or server error: show message and reset UI
        console.error('Error asking agent:', error);
        document.getElementById('thinkingArea').value = '';
        document.getElementById('responseArea').value = 'Connection error: ' + error.message +
            '\n\nPlease check that the server is running and try again.';
        document.getElementById('thinkingStatus').textContent = 'Connection failed';
        document.getElementById('responseStatus').textContent = 'Network error';
    }

    // Reset UI (spinner, loading text, button state)
    isProcessing = false;
    document.getElementById('spinner').style.display = 'none';
    document.getElementById('loadingText').style.display = 'none';
    updateAskButtonState();
}