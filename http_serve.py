#!/usr/bin/env python3
import http.server
import socketserver
import subprocess
import threading # For running commands in a non-blocking way if needed

# --- Configuration ---
PORT = 8000
HOST = "localhost" # Listen on localhost only by default. Change to "0.0.0.0" to listen on all interfaces.

# Dictionary mapping URL paths to mpremote commands
# The placeholder {action_code} will be replaced by the specific IR code
MPREMOTE_COMMAND_TEMPLATE = "mpremote exec \"import ir_send; ir_send.send_ir('{action_code}', 0)\""

ACTIONS = {
    "/play":   "768910EF",
    "/pause":  "7689D02F",
    "/rewind": "768940BF",
    "/stop":   "7689807F",
}

# --- HTTP Request Handler ---
class MPremoteControlHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        """Handles GET requests."""
        print(f"Received GET request for path: {self.path}")

        if self.path in ACTIONS:
            action_code = ACTIONS[self.path]
            command_to_run = MPREMOTE_COMMAND_TEMPLATE.format(action_code=action_code)
            
            print(f"Executing command: {command_to_run}")

            try:
                # Execute the mpremote command
                # Using subprocess.run() for simplicity.
                # For production, consider error handling, timeouts, and security.
                result = subprocess.run(command_to_run, shell=True, check=True, capture_output=True, text=True)
                
                # If the command was successful
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                response_message = f"Successfully executed: {self.path}\nCommand: {command_to_run}\nOutput:\n{result.stdout}"
                self.wfile.write(response_message.encode('utf-8'))
                print(f"Successfully executed {self.path}. Output: {result.stdout}")

            except subprocess.CalledProcessError as e:
                # If the command failed
                self.send_response(500) # Internal Server Error
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                error_message = f"Error executing command for {self.path}:\n{command_to_run}\nError:\n{e.stderr}"
                self.wfile.write(error_message.encode('utf-8'))
                print(f"Error executing {self.path}. Error: {e.stderr}")
            except FileNotFoundError:
                # If mpremote command is not found
                self.send_response(500)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                error_message = f"Error: 'mpremote' command not found. Make sure it's installed and in your PATH."
                self.wfile.write(error_message.encode('utf-8'))
                print(error_message)
            except Exception as e:
                # Catch any other unexpected errors
                self.send_response(500)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                error_message = f"An unexpected error occurred for {self.path}:\n{str(e)}"
                self.wfile.write(error_message.encode('utf-8'))
                print(error_message)
        else:
            # If the path is not one of the defined actions
            self.send_response(404) # Not Found
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Unknown action: {self.path}\n".encode('utf-8'))
            self.wfile.write(b"Available actions: /play, /pause, /rewind, /stop\n")
            print(f"Unknown action: {self.path}")

# --- Main Server Logic ---
def run_server():
    """Starts the HTTP server."""
    with socketserver.TCPServer((HOST, PORT), MPremoteControlHandler) as httpd:
        print(f"Serving HTTP on {HOST} port {PORT}...")
        print("You can send commands using curl, e.g.:")
        print(f"  curl http://{HOST}:{PORT}/play")
        print(f"  curl http://{HOST}:{PORT}/pause")
        print(f"  curl http://{HOST}:{PORT}/rewind")
        print(f"  curl http://{HOST}:{PORT}/stop")
        print("\nPress Ctrl+C to stop the server.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer shutting down.")
        finally:
            httpd.server_close()

if __name__ == "__main__":
    # Ensure ir_send.py is available to mpremote on the device.
    # You might need to copy it to the device first, e.g., using:
    # mpremote cp ir_send.py :ir_send.py
    # (Assuming ir_send.py is in the same directory as this server script or accessible)
    
    print("-----------------------------------------------------")
    print("Python HTTP Server for mpremote IR Control")
    print("-----------------------------------------------------")
    print("IMPORTANT: Ensure 'mpremote' is installed and in your system's PATH.")
    print("Ensure your MicroPython device is connected and accessible via mpremote.")
    print("Ensure 'ir_send.py' (or your equivalent IR sending module) is on the MicroPython device.")
    print("-----------------------------------------------------")
    
    run_server()
