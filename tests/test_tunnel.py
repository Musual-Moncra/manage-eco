import unittest
from unittest.mock import patch, MagicMock
from manage_eco.tunnel import get_local_ip, generate_terminal_qr, CloudflareTunnel, TailscaleTunnel, AutoTunnel, create_tunnel

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

    @patch("manage_eco.tunnel.subprocess.run")
    def test_tailscale_tunnel_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Available on the internet:\n\nhttps://musual.tail2cac77.ts.net/\n|-- proxy http://127.0.0.1:8080\n",
            stderr="",
        )
        tunnel = TailscaleTunnel()
        url = tunnel.start(8080)
        self.assertEqual(url, "https://musual.tail2cac77.ts.net")
        self.assertEqual(tunnel.url, "https://musual.tail2cac77.ts.net")
        self.assertTrue(tunnel.is_running())
        tunnel.stop()
        self.assertFalse(tunnel.is_running())

    @patch("manage_eco.tunnel.subprocess.run")
    def test_tailscale_tunnel_missing_or_failed(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        tunnel = TailscaleTunnel()
        url = tunnel.start(8080)
        self.assertIsNone(url)
        self.assertFalse(tunnel.is_running())

    @patch("manage_eco.tunnel.TailscaleTunnel.start")
    def test_auto_tunnel_prefers_tailscale(self, mock_ts_start):
        mock_ts_start.return_value = "https://ts.domain.ts.net"
        auto = AutoTunnel()
        url = auto.start(8080)
        self.assertEqual(url, "https://ts.domain.ts.net")
        self.assertEqual(auto.provider_name, "Tailscale Funnel")
        self.assertTrue(auto.is_running())

    @patch("manage_eco.tunnel.TailscaleTunnel.start")
    @patch("manage_eco.tunnel.CloudflareTunnel.start")
    def test_auto_tunnel_fallback_to_cloudflare(self, mock_cf_start, mock_ts_start):
        mock_ts_start.return_value = None
        mock_cf_start.return_value = "https://cf.trycloudflare.com"
        auto = AutoTunnel()
        url = auto.start(8080)
        self.assertEqual(url, "https://cf.trycloudflare.com")
        self.assertEqual(auto.provider_name, "Cloudflare")
        self.assertTrue(auto.is_running())
