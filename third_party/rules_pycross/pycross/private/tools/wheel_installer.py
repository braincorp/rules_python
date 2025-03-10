# Copyright 2023 Jeremy Volkman. All rights reserved.
# Copyright 2023 The Bazel Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
A tool that invokes pypa/build to build the given sdist tarball.
"""

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from installer import install
from installer.destinations import SchemeDictionaryDestination
from installer.sources import WheelFile

from python.pip_install.tools.wheel_installer import namespace_pkgs


def setup_namespace_pkg_compatibility(wheel_dir: Path) -> None:
    """Converts native namespace packages to pkgutil-style packages

    Namespace packages can be created in one of three ways. They are detailed here:
    https://packaging.python.org/guides/packaging-namespace-packages/#creating-a-namespace-package

    'pkgutil-style namespace packages' (2) and 'pkg_resources-style namespace packages' (3) works in Bazel, but
    'native namespace packages' (1) do not.

    We ensure compatibility with Bazel of method 1 by converting them into method 2.

    Args:
        wheel_dir: the directory of the wheel to convert
    """

    namespace_pkg_dirs = namespace_pkgs.implicit_namespace_packages(
        str(wheel_dir),
        ignored_dirnames=["%s/bin" % wheel_dir],
    )

    for ns_pkg_dir in namespace_pkg_dirs:
        namespace_pkgs.add_pkgutil_style_namespace_pkg_init(ns_pkg_dir)


def main(args: Any) -> None:
    dest_dir = args.directory
    lib_dir = dest_dir / "site-packages"
    destination = SchemeDictionaryDestination(
        scheme_dict={
            "platlib": str(lib_dir),
            "purelib": str(lib_dir),
            "headers": str(dest_dir / "include"),
            "scripts": str(dest_dir / "bin"),
            "data": str(dest_dir / "data"),
        },
        interpreter="/usr/bin/env python3",  # Generic; it's not feasible to run these scripts directly.
        script_kind="posix",
        bytecode_optimization_levels=[0, 1],
    )

    link_dir = Path(tempfile.mkdtemp())
    if args.wheel_name_file:
        with open(args.wheel_name_file, "r") as f:
            wheel_name = f.read().strip()
    else:
        wheel_name = os.path.basename(args.wheel)

    link_path = link_dir / wheel_name
    os.symlink(os.path.join(os.getcwd(), args.wheel), link_path)

    try:
        with WheelFile.open(link_path) as source:
            install(
                source=source,
                destination=destination,
                # Additional metadata that is generated by the installation tool.
                additional_metadata={
                    "INSTALLER": b"https://github.com/bazelbuild/rules_python/tree/main/third_party/rules_pycross",
                },
            )
    finally:
        shutil.rmtree(link_dir, ignore_errors=True)

    setup_namespace_pkg_compatibility(lib_dir)


def parse_flags(argv) -> Any:
    parser = argparse.ArgumentParser(description="Extract a Python wheel.")

    parser.add_argument(
        "--wheel",
        type=Path,
        required=True,
        help="The wheel file path.",
    )

    parser.add_argument(
        "--wheel-name-file",
        type=Path,
        required=False,
        help="A file containing the canonical name of the wheel.",
    )

    parser.add_argument(
        "--enable-implicit-namespace-pkgs",
        action="store_true",
        help="If true, disables conversion of implicit namespace packages and will unzip as-is.",
    )

    parser.add_argument(
        "--directory",
        type=Path,
        help="The output path.",
    )

    return parser.parse_args(argv[1:])


if __name__ == "__main__":
    # When under `bazel run`, change to the actual working dir.
    if "BUILD_WORKING_DIRECTORY" in os.environ:
        os.chdir(os.environ["BUILD_WORKING_DIRECTORY"])

    main(parse_flags(sys.argv))
