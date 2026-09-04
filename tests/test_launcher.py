import os
import threading
import unittest
from urllib.request import urlopen
import launcher

class LauncherTest(unittest.TestCase):
    def test_serves_app(self):
        server = launcher.create_server(0)
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        body = urlopen(f"http://{launcher.HOST}:{server.server_port}/index.html").read().decode()
        thread.join(timeout=2); server.server_close()
        self.assertIn("Fantasy Draft Assistant", body)
        self.assertIn('id="csvFile"', body)

if __name__ == "__main__": unittest.main()
