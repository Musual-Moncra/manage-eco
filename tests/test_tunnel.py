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
