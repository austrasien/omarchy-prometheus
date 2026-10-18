import os
import tempfile
import unittest

from prometheus import procfs


def make(proc, pid, comm, ppid, pgrp, tty, tpgid, argv0=None, kids=()):
    d = os.path.join(proc, str(pid))
    os.makedirs(os.path.join(d, "task", str(pid)))
    with open(os.path.join(d, "stat"), "w") as f:
        f.write(f"{pid} ({comm}) S {ppid} {pgrp} {pgrp} {tty} {tpgid} 0 0\n")
    with open(os.path.join(d, "cmdline"), "wb") as f:
        f.write((argv0 or comm).encode() + b"\0")
    with open(os.path.join(d, "task", str(pid), "children"), "w") as f:
        f.write(" ".join(str(k) for k in kids))


class ProcfsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proc = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_foreground_program(self):
        make(self.proc, 100, "foot", 1, 100, 0, -1, "/usr/bin/foot", kids=[101])
        make(self.proc, 101, "bash", 100, 101, 34816, 150, "-bash", kids=[150])
        make(self.proc, 150, "nvim", 101, 150, 34816, 150, "/usr/bin/nvim")
        self.assertEqual(procfs.foreground(100, self.proc), "nvim")

    def test_bare_shell_is_none(self):
        make(self.proc, 100, "foot", 1, 100, 0, -1, kids=[101])
        make(self.proc, 101, "zsh", 100, 101, 34816, 101, "-zsh")
        self.assertIsNone(procfs.foreground(100, self.proc))

    def test_missing_process(self):
        self.assertIsNone(procfs.foreground(999, self.proc))

    def test_is_terminal(self):
        self.assertTrue(procfs.is_terminal("foot"))
        self.assertTrue(procfs.is_terminal("Alacritty"))
        self.assertFalse(procfs.is_terminal("org.omarchy.agent.claude"))
        self.assertFalse(procfs.is_terminal(None))


if __name__ == "__main__":
    unittest.main()
