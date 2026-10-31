import os
import sys
from setuptools import setup, find_packages

try:
    from pybind11.setup_helpers import Pybind11Extension, build_ext
    has_pybind11 = True
except ImportError:
    has_pybind11 = False

ext_modules = []
cmdclass = {}

if has_pybind11:
    ext_modules = [
        Pybind11Extension(
            "core_engine",
            ["src/core_engine.cpp"],
            cxx_std=17,
        ),
    ]
    cmdclass = {"build_ext": build_ext}

setup(
    name="grand_mobile_core",
    version="1.0.0",
    author="Grand Mobile Copilot Team",
    description="High-performance C++ Core Extension for Grand Mobile Support Copilot",
    packages=find_packages(),
    ext_modules=ext_modules,
    cmdclass=cmdclass,
    python_requires=">=3.10",
)

