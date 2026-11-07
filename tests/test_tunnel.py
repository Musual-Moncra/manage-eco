import unittest
from manage_eco.tunnel import get_local_ip, generate_terminal_qr, CloudflareTunnel

class TunnelTest(unittest.TestCase):
    def test_local_ip_discovery(self):
        ip = get_local_ip()
        self.assertTrue(isinstance(ip, str) and len(ip) > 0)
        self.assertNotEqual(ip, "0.0.0.0")

    def test_qr_generation(self):
        lines = generate_terminal_qr("https://eco.local")
        self.assertTrue(len(lines) > 5)
        self.assertTrue(any("█" in l or "▀" in l or "▄" in l for l in lines))

    def test_tunnel_lifecycle_mocked(self):
        tunnel = CloudflareTunnel()
        self.assertFalse(tunnel.is_running())
        self.assertIsNone(tunnel.url)
        # Calling stop on an unstarted tunnel should not raise
        tunnel.stop()

    def test_tunnel_background_thread_reader(self):
        tunnel = CloudflareTunnel()
        # Mock proc with a fake stderr pipe
        import io, threading
        class FakeProc:
            def __init__(self):
                self.stderr = io.StringIO("2026-11-08 INF https://test-tunnel.trycloudflare.com registered\n")
            def poll(self): return None
            def terminate(self): pass
            def wait(self, timeout=None): pass
        tunnel.proc = FakeProc()
        tunnel._start_reader_thread()
        import time
        time.sleep(0.1)
        self.assertEqual(tunnel.url, "https://test-tunnel.trycloudflare.com")
