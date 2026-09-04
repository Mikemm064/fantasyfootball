"""Dependency-free local server and browser launcher."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import os
import threading
import webbrowser

HOST, PORT = "127.0.0.1", 8765

def create_server(port=PORT):
    os.chdir(Path(__file__).resolve().parent)
    return ThreadingHTTPServer((HOST, port), SimpleHTTPRequestHandler)

if __name__ == "__main__":
    server = create_server()
    url = f"http://{HOST}:{PORT}"
    print(f"Fantasy Draft Assistant is running at {url}")
    print("Keep this window open. Press Ctrl+C to stop.")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: print("\nStopped.")
    finally: server.server_close()
