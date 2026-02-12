import asyncio
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
from threading import Thread
import webbrowser


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
            
            if hasattr(WebUIHandler, 'get_server_url'):
                server_url = WebUIHandler.get_server_url()
            if hasattr(WebUIHandler, 'get_model_name'):
                model_name = WebUIHandler.get_model_name()
            if hasattr(WebUIHandler, 'get_tools'):
                tools_list = WebUIHandler.get_tools()
            
            response_data = {
                'success': True,
                'serverUrl': server_url,
                'modelName': model_name,
                'tools': tools_list
            }
            self.wfile.write(json.dumps(response_data).encode('utf-8'))
        
        elif path == '/assets/logo.png' or path == '/styles.css':
            import os
            script_dir = os.path.dirname(os.path.abspath(__file__))
            
            if path == '/assets/logo.png':
                asset_path = os.path.join(script_dir, 'assets', 'logo.png')
                content_type = 'image/png'
            elif path == '/styles.css':
                asset_path = os.path.join(script_dir, 'styles.css')
                content_type = 'text/css'
            
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
        if self.path == '/ask':
            try:
                # Read request body
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                question = data.get('question', '')
                if not question:
                    self._send_json_response({'success': False, 'error': 'No question provided'})
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
                
                # Run agent in background
                result = {'response': None, 'thinking': None, 'error': None}
                
                async def run_agent():
                    try:
                        response = await agent.ainvoke(
                            {"messages": [{"role": "user", "content": question}]}
                        )
                        
                        print(f"DEBUG: Agent response structure: {type(response)}")
                        print(f"DEBUG: Agent response keys: {response.keys() if isinstance(response, dict) else 'Not a dict'}")
                        
                        # Simple approach - just extract all content
                        all_content = []
                        thinking_content = []
                        
                        if isinstance(response, dict) and "messages" in response:
                            for i, message in enumerate(response["messages"]):
                                print(f"DEBUG: Message {i}: type={getattr(message, 'type', 'no type')}, content type={type(getattr(message, 'content', None))}")
                                
                                if hasattr(message, 'content') and message.content:
                                    content_str = str(message.content)
                                    
                                    # Add all non-empty content to all_content
                                    if content_str.strip():
                                        all_content.append(content_str.strip())
                                        
                                        # Categorize for thinking vs response
                                        msg_type = getattr(message, 'type', '')
                                        if msg_type in ['tool', 'tool_use'] or 'tool' in content_str.lower():
                                            thinking_content.append(f"Tool: {content_str}")
                                        elif i == 0:  # First message is user
                                            thinking_content.append(f"User: {content_str}")
                                        elif i < len(response["messages"]) - 1:  # Not the last message
                                            thinking_content.append(f"Agent: {content_str}")
                        
                        # Set thinking
                        if thinking_content:
                            result['thinking'] = '\n\n'.join(thinking_content)
                        else:
                            result['thinking'] = "Agent processed the request"
                        
                        # Set response - look for FINAL RESPONSE: marker first, then fallback to previous logic
                        if all_content:
                            final_response = None
                            
                            # First, try to find content with "FINAL RESPONSE:" marker
                            for content in all_content:
                                if "FINAL RESPONSE:" in content:
                                    # Extract everything after "FINAL RESPONSE:"
                                    final_response = content.split("FINAL RESPONSE:", 1)[1].strip()
                                    break
                            
                            # Fallback: Try to find the final response (usually the last message that's not a tool)
                            if not final_response:
                                for content in reversed(all_content):
                                    if not any(word in content.lower() for word in ['tool', 'function', 'action:', 'observation:']):
                                        final_response = content
                                        break
                            
                            # Additional fallback - if still no response, use the last content item
                            if not final_response and all_content:
                                final_response = all_content[-1]
                            
                            result['response'] = final_response or "Response received but content was empty"
                            
                            # Debug logging
                            print(f"DEBUG: Final response found: {bool(final_response)}")
                            print(f"DEBUG: All content count: {len(all_content)}")
                            if final_response:
                                print(f"DEBUG: Final response preview: {final_response[:100]}...")
                        else:
                            result['response'] = f"No content found in response. Response structure: {response}"
                        
                    except Exception as e:
                        result['error'] = str(e)
                        print(f"DEBUG: Exception in run_agent: {e}")
                        import traceback
                        traceback.print_exc()

                # Try to get existing event loop, create new one if needed
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_closed():
                        raise RuntimeError("Event loop is closed")
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                # Run the agent without closing the loop
                loop.run_until_complete(run_agent())
                
                if result['error']:
                    self._send_json_response({'success': False, 'error': result['error']})
                else:
                    self._send_json_response({
                        'success': True, 
                        'thinking': result['thinking'],
                        'response': result['response']
                    })
                
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
        
    def set_callbacks(self, callback_handler, get_agent_func, get_server_url_func=None, get_model_name_func=None, get_tools_func=None):
        """Set the callback functions for OAuth, agent access, server URL, model name, and tools"""
        WebUIHandler.callback_handler = callback_handler
        WebUIHandler.get_agent = get_agent_func
        if get_server_url_func:
            WebUIHandler.get_server_url = get_server_url_func
        if get_model_name_func:
            WebUIHandler.get_model_name = get_model_name_func
        if get_tools_func:
            WebUIHandler.get_tools = get_tools_func
        
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