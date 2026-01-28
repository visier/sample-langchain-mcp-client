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
        
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
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
                        self._send_json_response({'success': False, 'error': 'Agent not initialized'})
                        return
                else:
                    self._send_json_response({'success': False, 'error': 'Agent not available'})
                    return
                
                # Run agent in background
                result = {'response': None, 'thinking': None, 'error': None}
                
                async def run_agent():
                    try:
                        response = await agent.ainvoke(
                            {"messages": [{"role": "user", "content": question}]}
                        )
                        
                        # Extract thinking and final response
                        thinking_parts = []
                        response_parts = []
                        
                        for i, message in enumerate(response["messages"]):
                            if hasattr(message, 'content') and message.content:
                                content = str(message.content)
                                
                                # Check message type to determine if it's thinking or final response
                                if hasattr(message, 'type'):
                                    if message.type == 'ai':
                                        # AI messages could be either thinking or final response
                                        # Check if this is the last AI message (likely final response)
                                        is_last_ai = True
                                        for j in range(i + 1, len(response["messages"])):
                                            if hasattr(response["messages"][j], 'type') and response["messages"][j].type == 'ai':
                                                is_last_ai = False
                                                break
                                        
                                        if is_last_ai:
                                            # This is likely the final response
                                            response_parts.append(content)
                                        else:
                                            # This is thinking/planning
                                            thinking_parts.append(f"Agent: {content}")
                                    
                                    elif message.type == 'tool':
                                        thinking_parts.append(f"Tool Response: {content}")
                                    
                                    else:
                                        # Human or other messages
                                        if i == 0:  # First message is usually the user question
                                            thinking_parts.append(f"User: {content}")
                                        else:
                                            response_parts.append(content)
                                else:
                                    # If we can't determine type, try to parse the content
                                    if isinstance(message.content, list):
                                        # Handle structured content (like tool calls)
                                        thinking_parts.append(f"Agent Planning: {content}")
                                    else:
                                        response_parts.append(content)
                        
                        # Clean up and format the results
                        if thinking_parts:
                            result['thinking'] = '\n\n'.join(thinking_parts)
                        else:
                            result['thinking'] = "Agent processed the question directly"
                            
                        if response_parts:
                            # Clean the final response - remove any remaining tool call syntax
                            final_response = '\n'.join(response_parts).strip()
                            # Remove any remaining structured content markers
                            import re
                            final_response = re.sub(r'\[{.*?}\]', '', final_response)
                            final_response = re.sub(r'tooluse_\w+', '', final_response)
                            result['response'] = final_response.strip() or "No specific response generated"
                        else:
                            result['response'] = "No response generated"
                        
                    except Exception as e:
                        result['error'] = str(e)

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