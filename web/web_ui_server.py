import asyncio
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
from threading import Thread
import webbrowser


def _msg_content(msg):
    """Return the content field from a message object or dict."""
    if hasattr(msg, "content"):
        return getattr(msg, "content", None)
    if isinstance(msg, dict):
        return msg.get("content")
    return None


def _format_stream_update(update_dict):
    """
    Format a single stream update (node name -> state update) for display.

    Converts LangGraph stream chunks (e.g. model/tools node updates) into
    readable lines for the Agent Reasoning UI (tool calls, tool results, model output).
    """
    lines = []
    for node_name, state in (update_dict.items() if isinstance(update_dict, dict) else []):
        if not isinstance(state, dict):
            continue
        messages = state.get("messages") or []
        for msg in messages:
            content = _msg_content(msg)
            if content:
                content = str(content).strip()
            if not content:
                if hasattr(msg, "tool_calls") and getattr(msg, "tool_calls", None):
                    for tc in msg.tool_calls or []:
                        name = tc.get("name", "?") if isinstance(tc, dict) else getattr(tc, "name", "?")
                        args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                        lines.append(f"[{node_name}] Calling tool: {name} with args: {args}")
                elif isinstance(msg, dict) and msg.get("tool_calls"):
                    for tc in msg["tool_calls"] or []:
                        name = tc.get("name", "?")
                        args = tc.get("args", {})
                        lines.append(f"[{node_name}] Calling tool: {name} with args: {args}")
                continue
            msg_type = getattr(msg, "type", "") if hasattr(msg, "type") else (msg.get("type") if isinstance(msg, dict) else "")
            if "tool" in str(msg_type).lower() or (hasattr(msg, "tool_call_id") and getattr(msg, "tool_call_id", None)) or (isinstance(msg, dict) and msg.get("tool_call_id")):
                lines.append(f"[{node_name}] Tool result: {content[:500]}{'...' if len(content) > 500 else ''}")
            else:
                lines.append(f"[{node_name}] {content[:500]}{'...' if len(content) > 500 else ''}")
    return "\n".join(lines) if lines else None


def _extract_final_response_and_thinking(state: dict):
    """
    Extract final response text and full thinking from graph state.

    state: Graph state dict with a "messages" list (e.g. from stream_mode="values").
    Returns: (final_response_str, thinking_str) for the UI.
    """
    if not state or not isinstance(state, dict):
        return None, ""
    messages = state.get("messages") or []
    all_content = []
    thinking_content = []
    for i, message in enumerate(messages):
        if hasattr(message, "content") and message.content:
            content_str = str(message.content).strip()
            if content_str:
                all_content.append(content_str)
                msg_type = getattr(message, "type", "")
                if msg_type in ("tool", "tool_use") or "tool" in content_str.lower():
                    thinking_content.append(f"Tool: {content_str}")
                elif i == 0:
                    thinking_content.append(f"User: {content_str}")
                elif i < len(messages) - 1:
                    thinking_content.append(f"Agent: {content_str}")
    thinking = "\n\n".join(thinking_content) if thinking_content else "Agent processed the request"
    final_response = None
    for content in (all_content or []):
        if "FINAL RESPONSE:" in content:
            final_response = content.split("FINAL RESPONSE:", 1)[1].strip()
            break
    if not final_response and all_content:
        for content in reversed(all_content):
            if not any(w in content.lower() for w in ("tool", "function", "action:", "observation:")):
                final_response = content
                break
    if not final_response and all_content:
        final_response = all_content[-1]
    return final_response or "Response received but content was empty", thinking


class WebUIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Parse the URL to get the path without query parameters
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        
        if path == '/callback':
            # Handle OAuth callback
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            
            query = parse_qs(parsed_url.query)
            if "code" in query:
                # Store captured code in the global callback function
                if hasattr(WebUIHandler, 'callback_handler'):
                    WebUIHandler.callback_handler(query["code"][0], query.get("state", [None])[0])
                self.wfile.write(b"<h1>Login Successful!</h1><p>Return to your terminal.</p>")
            else:
                self.wfile.write(b"<h1>Login Failed</h1><p>No code found.</p>")
        
        elif path == '/' or path == '/index.html':
            # Serve the web UI
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            
            try:
                # Get the directory where this script is located
                import os
                script_dir = os.path.dirname(os.path.abspath(__file__))
                html_path = os.path.join(script_dir, 'web_ui.html')
                with open(html_path, 'r', encoding='utf-8') as f:
                    self.wfile.write(f.read().encode('utf-8'))
            except FileNotFoundError:
                self.wfile.write(b"<h1>Error</h1><p>web_ui.html not found</p>")
        
        elif path == '/server-info':
            # Serve server info
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            server_url = "Server URL not available"
            model_name = "Model not available"
            tools_list = []
            prompts_list = []

            if hasattr(WebUIHandler, 'get_server_url'):
                server_url = WebUIHandler.get_server_url()
            if hasattr(WebUIHandler, 'get_model_name'):
                model_name = WebUIHandler.get_model_name()
            if hasattr(WebUIHandler, 'get_tools'):
                tools_list = WebUIHandler.get_tools()
            if hasattr(WebUIHandler, 'get_prompts'):
                prompts_list = WebUIHandler.get_prompts()

            response_data = {
                'success': True,
                'serverUrl': server_url,
                'modelName': model_name,
                'tools': tools_list,
                'prompts': prompts_list
            }
            self.wfile.write(json.dumps(response_data).encode('utf-8'))
        
        elif path == '/assets/logo.png' or path == '/styles.css' or path == '/app.js':
            import os
            script_dir = os.path.dirname(os.path.abspath(__file__))
            
            if path == '/assets/logo.png':
                asset_path = os.path.join(script_dir, 'assets', 'logo.png')
                content_type = 'image/png'
            elif path == '/styles.css':
                asset_path = os.path.join(script_dir, 'styles.css')
                content_type = 'text/css'
            elif path == '/app.js':
                asset_path = os.path.join(script_dir, 'app.js')
                content_type = 'application/javascript'
            
            try:
                with open(asset_path, 'rb') as f:
                    content = f.read()
                    
                self.send_response(200)
                self.send_header('Content-type', content_type)
                self.send_header('Cache-Control', 'public, max-age=3600')
                self.end_headers()
                self.wfile.write(content)
                
            except FileNotFoundError:
                self.send_response(404)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b"Asset not found")
        
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Not found")
    
    def do_POST(self):
        if self.path == '/get-prompt-content':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                prompt_name = data.get('prompt') or None
                prompt_arguments = data.get('promptArguments') or {}
                if not prompt_name:
                    self._send_json_response({'success': False, 'error': 'No prompt selected.'})
                    return
                if not hasattr(WebUIHandler, 'get_prompt_messages_async') or not callable(getattr(WebUIHandler, 'get_prompt_messages_async', None)):
                    self._send_json_response({'success': False, 'error': 'Prompt service not available.'})
                    return

                async def fetch_prompt():
                    messages = await WebUIHandler.get_prompt_messages_async(prompt_name, prompt_arguments)
                    parts = []
                    for m in messages:
                        content = str(m).strip()
                        if content:
                            parts.append(content)
                    return '\n\n'.join(parts) if parts else ''

                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_closed():
                        raise RuntimeError("Event loop is closed")
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                prompt_content = loop.run_until_complete(fetch_prompt())
                self._send_json_response({'success': True, 'promptContent': prompt_content})
            except Exception as e:
                self._send_json_response({'success': False, 'error': str(e)})
            return

        if self.path == '/ask':
            try:
                # Read request body
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                question = (data.get('question') or '').strip()
                if not question:
                    self._send_json_response({'success': False, 'error': 'No question provided.'})
                    return

                # Get the global agent
                if hasattr(WebUIHandler, 'get_agent'):
                    agent = WebUIHandler.get_agent()
                    if agent is None:
                        self._send_json_response({'success': False, 'error': 'Agent not ready yet - please wait for authentication to complete'})
                        return
                else:
                    self._send_json_response({'success': False, 'error': 'Agent service not available'})
                    return
                
                def send_sse(obj):
                    self.wfile.write(("data: " + json.dumps(obj) + "\n\n").encode("utf-8"))
                    self.wfile.flush()

                async def stream_agent():
                    last_values = None
                    try:
                        inputs = {"messages": [{"role": "user", "content": question}]}
                        stream = agent.astream(inputs, stream_mode=["updates", "values"])
                        async for chunk in stream:
                            if isinstance(chunk, tuple) and len(chunk) == 2:
                                mode, payload = chunk
                                if mode == "values":
                                    last_values = payload
                                elif mode == "updates":
                                    line = _format_stream_update(payload)
                                    if line:
                                        send_sse({"type": "thinking", "content": line})
                            elif isinstance(chunk, dict):
                                if "messages" in chunk and not any(k in chunk for k in ("model", "tools") if chunk.get(k) is not None):
                                    last_values = chunk
                                else:
                                    line = _format_stream_update(chunk)
                                    if line:
                                        send_sse({"type": "thinking", "content": line})
                            else:
                                last_values = chunk
                        response, thinking = _extract_final_response_and_thinking(last_values or {})
                        send_sse({"type": "done", "success": True, "response": response, "thinking": thinking})
                    except Exception as e:
                        import traceback
                        traceback.print_exc()
                        send_sse({"type": "done", "success": False, "error": str(e)})

                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_closed():
                        raise RuntimeError("Event loop is closed")
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                loop.run_until_complete(stream_agent())
                return
            except Exception as e:
                self._send_json_response({'success': False, 'error': str(e)})
        else:
            self.send_response(404)
            self.end_headers()
    
    def _send_json_response(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
    
    def log_message(self, format, *args):
        # Suppress default logging
        pass


class WebUIServer:
    def __init__(self, oauth_port=8000, ui_port=8001):
        self.oauth_port = oauth_port
        self.ui_port = ui_port
        
    def set_callbacks(
        self,
        callback_handler,
        get_agent_func,
        get_server_url_func=None,
        get_model_name_func=None,
        get_tools_func=None,
        get_prompts_func=None,
        get_prompt_messages_async=None,
    ):
        """Set the callback functions for OAuth, agent access, server URL, model name, tools, and prompt resolution."""
        WebUIHandler.callback_handler = callback_handler
        WebUIHandler.get_agent = get_agent_func
        if get_server_url_func:
            WebUIHandler.get_server_url = get_server_url_func
        if get_model_name_func:
            WebUIHandler.get_model_name = get_model_name_func
        if get_tools_func:
            WebUIHandler.get_tools = get_tools_func
        if get_prompts_func:
            WebUIHandler.get_prompts = get_prompts_func
        if get_prompt_messages_async is not None:
            WebUIHandler.get_prompt_messages_async = get_prompt_messages_async

    def start_oauth_server(self):
        """Start the OAuth callback server"""
        server = HTTPServer(('localhost', self.oauth_port), WebUIHandler)
        server.handle_request()
        
    def start_ui_server(self):
        """Start the web UI server"""
        server = HTTPServer(('localhost', self.ui_port), WebUIHandler)
        print(f"\nWeb UI available at: http://localhost:{self.ui_port}")
        server.serve_forever()
        
    def open_ui(self):
        """Open the UI in the browser"""
        ui_url = f"http://localhost:{self.ui_port}"
        webbrowser.open(ui_url)
        
    def start_ui_in_background(self):
        """Start the UI server in a background thread"""
        ui_thread = Thread(target=self.start_ui_server, daemon=True)
        ui_thread.start()
        return ui_thread