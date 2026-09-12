# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from unittest import mock

from novelreader import main as entry


class TclTkPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dd_tcltk_test_")
        self.tcl_dir = os.path.join(self.tmp.name, "tcl", "tcl8.6")
        self.tk_dir = os.path.join(self.tmp.name, "tcl", "tk8.6")
        os.makedirs(self.tcl_dir)
        os.makedirs(self.tk_dir)
        open(os.path.join(self.tcl_dir, "init.tcl"), "w").close()
        open(os.path.join(self.tk_dir, "tk.tcl"), "w").close()
        self.old_tcl = os.environ.pop("TCL_LIBRARY", None)
        self.old_tk = os.environ.pop("TK_LIBRARY", None)

    def tearDown(self):
        os.environ.pop("TCL_LIBRARY", None)
        os.environ.pop("TK_LIBRARY", None)
        if self.old_tcl is not None:
            os.environ["TCL_LIBRARY"] = self.old_tcl
        if self.old_tk is not None:
            os.environ["TK_LIBRARY"] = self.old_tk
        self.tmp.cleanup()

    def _run_setup(self):
        with mock.patch.object(entry.sys, "base_prefix", self.tmp.name):
            entry._setup_tcltk()

    def test_discovers_base_python_tcltk_when_environment_is_empty(self):
        self._run_setup()
        self.assertEqual(os.environ["TCL_LIBRARY"], self.tcl_dir)
        self.assertEqual(os.environ["TK_LIBRARY"], self.tk_dir)

    def test_replaces_invalid_environment_paths(self):
        os.environ["TCL_LIBRARY"] = os.path.join(self.tmp.name, "missing-tcl")
        os.environ["TK_LIBRARY"] = os.path.join(self.tmp.name, "missing-tk")
        self._run_setup()
        self.assertEqual(os.environ["TCL_LIBRARY"], self.tcl_dir)
        self.assertEqual(os.environ["TK_LIBRARY"], self.tk_dir)


if __name__ == "__main__":
    unittest.main()
