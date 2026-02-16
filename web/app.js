let isProcessing = false;

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
        } else {
            document.getElementById('serverUrl').textContent = 'Server URL not available';
            document.getElementById('modelName').textContent = 'Model info not available';
            document.getElementById('toolsContainer').innerHTML = '<div class="error">Tools info not available</div>';
        }
    } catch (error) {
        console.error('Error loading server info:', error);
        document.getElementById('serverUrl').textContent = 'Error loading server info';
        document.getElementById('modelName').textContent = 'Error loading model info';
        document.getElementById('toolsContainer').innerHTML = '<div class="error">Error loading tools info</div>';
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

function formatSchema(schema) {
    if (!schema) return 'No schema available';
    
    try {
        // If it's already an object, stringify it with formatting
        if (typeof schema === 'object') {
            return JSON.stringify(schema, null, 2);
        }
        
        // If it's a string, try to parse and re-stringify for formatting
        if (typeof schema === 'string') {
            try {
                const parsed = JSON.parse(schema);
                return JSON.stringify(parsed, null, 2);
            } catch (e) {
                // If parsing fails, return as-is
                return schema;
            }
        }
        
        return String(schema);
    } catch (error) {
        console.error('Error formatting schema:', error);
        return 'Error formatting schema';
    }
}

document.getElementById('questionInput').addEventListener('keypress', function(e) {
    if (e.key === 'Enter' && !isProcessing) {
        askAgent();
    }
});

async function askAgent() {
    if (isProcessing) return;
    
    const question = document.getElementById('questionInput').value.trim();
    if (!question) {
        alert('Please enter a question');
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
        const response = await fetch('/ask', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ question: question })
        });

        const data = await response.json();

        if (data.success) {
            // Display thinking process if available
            if (data.thinking) {
                document.getElementById('thinkingArea').value = data.thinking;
                document.getElementById('thinkingStatus').textContent = 'Reasoning complete';
            } else {
                document.getElementById('thinkingArea').value = 'Agent reasoning not captured for this request.';
                document.getElementById('thinkingStatus').textContent = 'Reasoning not available';
            }
            
            // Display final response
            document.getElementById('responseArea').value = data.response;
            document.getElementById('responseStatus').textContent = 'Response ready';
        } else {
            document.getElementById('thinkingArea').value = '';
            document.getElementById('responseArea').value = 'Error: ' + (data.error || 'Unknown error occurred');
            document.getElementById('thinkingStatus').textContent = 'Error occurred';
            document.getElementById('responseStatus').textContent = 'Request failed';
        }
    } catch (error) {
        console.error('Error asking agent:', error);
        document.getElementById('thinkingArea').value = '';
        document.getElementById('responseArea').value = 'Connection error: ' + error.message + 
            '\n\nPlease check that the server is running and try again.';
        document.getElementById('thinkingStatus').textContent = 'Connection failed';
        document.getElementById('responseStatus').textContent = 'Network error';
    }

    // Reset UI
    isProcessing = false;
    document.getElementById('askButton').disabled = false;
    document.getElementById('spinner').style.display = 'none';
    document.getElementById('loadingText').style.display = 'none';
}