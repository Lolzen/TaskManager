"""The distribution recipes must stay in step with the package."""

import os
import re

import pytest

import taskmanager

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# distribution builds run the tests without the packaging/ directory next to them
pytestmark = pytest.mark.skipif(not os.path.isdir(os.path.join(ROOT, "packaging")),
                                reason="needs a source checkout")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_versions_match():
    version = taskmanager.__version__
    assert re.search(r"^pkgver={}$".format(re.escape(version)), read("packaging", "arch", "PKGBUILD"), re.M)
    assert re.search(r"^version={}$".format(re.escape(version)),
                     read("packaging", "void", "srcpkgs", "taskmanager", "template"), re.M)
    assert read("packaging", "debian", "changelog").startswith("taskmanager ({}-".format(version))
    assert '"taskmanager {}"'.format(version) in read("data", "taskmanager.1")


def test_recipes_install_the_same_files():
    for recipe in (read("packaging", "arch", "PKGBUILD"),
                   read("packaging", "void", "srcpkgs", "taskmanager", "template")):
        assert "taskmanager.desktop" in recipe and "taskmanager.1" in recipe and "LICENSE" in recipe
        assert "taskmanager.svg" in recipe
    install = read("packaging", "debian", "taskmanager.install")
    assert "taskmanager.desktop" in install and "taskmanager.svg" in install
    assert "taskmanager.1" in read("packaging", "debian", "taskmanager.manpages")


def test_qt_dependencies_name_the_widgets_module():
    # Void and Debian split PySide6 per Qt module; QtCore alone is not enough
    assert "python3-pyside6-widgets" in read("packaging", "void", "srcpkgs", "taskmanager", "template")
    assert "python3-pyside6.qtwidgets" in read("packaging", "debian", "control")
