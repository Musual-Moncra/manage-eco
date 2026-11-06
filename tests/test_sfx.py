import os
import tempfile
import unittest
import wave
from datetime import date
from unittest import mock

from manage_eco import api, sfx
from manage_eco.db import Store


class SfxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        patcher = mock.patch.object(sfx, "cache_dir", return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        sfx._last.clear()

    def test_every_event_synthesizes_short_valid_wav(self):
        for ev in sfx.EVENTS:
            with wave.open(sfx.sound_path(ev)) as w:
                self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, sfx.RATE))
                self.assertLess(w.getnframes() / sfx.RATE, 0.5)
                self.assertGreater(w.getnframes(), 0)

    def test_play_spawns_player_without_waiting(self):
        with mock.patch.object(sfx, "player", return_value=["true"]), \
                mock.patch.object(sfx.subprocess, "Popen") as popen:
            self.assertTrue(sfx.play("save"))
            args = popen.call_args[0][0]
            self.assertEqual(args[0], "true")
            self.assertTrue(args[1].endswith("save.wav"))
            self.assertFalse(sfx.play("save"))  # debounced

    def test_muted(self):
        with mock.patch.object(sfx.subprocess, "Popen") as popen:
            self.assertFalse(sfx.play("save", enabled=False))
            with mock.patch.dict(os.environ, {"ECO_SOUND": "0"}):
                self.assertFalse(sfx.play("done"))
            self.assertFalse(sfx.play("nope"))
            popen.assert_not_called()

    def test_no_player_only_error_rings_bell(self):
        with mock.patch.object(sfx, "player", return_value=None), \
                mock.patch.object(sfx.sys, "__stdout__") as out:
            self.assertFalse(sfx.play("save"))
            self.assertTrue(sfx.play("error"))
            out.write.assert_called_once_with("\a")

    def test_sound_setting_persists(self):
        store, today = Store(":memory:"), date(2026, 11, 6)
        self.assertEqual(api.execute("sound", {}, store, today), {"sound": True})
        self.assertEqual(api.execute("sound", {"state": "off"}, store, today), {"sound": False})
        self.assertEqual(api.execute("sound", {}, store, today), {"sound": False})
        with self.assertRaises(ValueError):
            api.execute("sound", {"state": "loud"}, store, today)


if __name__ == "__main__":
    unittest.main()
