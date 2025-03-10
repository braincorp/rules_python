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

"""Build and/or fetch a single wheel based on the requirement passed in"""

import argparse
import errno
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Dict, Iterable, List, Optional, Set, Tuple

from pip._vendor.packaging.utils import canonicalize_name

from python.pip_install.tools.wheel_installer import arguments, namespace_pkgs, wheel


def _configure_reproducible_wheels() -> None:
    """Modifies the environment to make wheel building reproducible.
    Wheels created from sdists are not reproducible by default. We can however workaround this by
    patching in some configuration with environment variables.
    """

    # wheel, by default, enables debug symbols in GCC. This incidentally captures the build path in the .so file
    # We can override this behavior by disabling debug symbols entirely.
    # https://github.com/pypa/pip/issues/6505
    if "CFLAGS" in os.environ:
        os.environ["CFLAGS"] += " -g0"
    else:
        os.environ["CFLAGS"] = "-g0"

    # set SOURCE_DATE_EPOCH to 1980 so that we can use python wheels
    # https://github.com/NixOS/nixpkgs/blob/master/doc/languages-frameworks/python.section.md#python-setuppy-bdist_wheel-cannot-create-whl
    if "SOURCE_DATE_EPOCH" not in os.environ:
        os.environ["SOURCE_DATE_EPOCH"] = "315532800"

    # Python wheel metadata files can be unstable.
    # See https://bitbucket.org/pypa/wheel/pull-requests/74/make-the-output-of-metadata-files/diff
    if "PYTHONHASHSEED" not in os.environ:
        os.environ["PYTHONHASHSEED"] = "0"


def _parse_requirement_for_extra(
    requirement: str,
) -> Tuple[Optional[str], Optional[Set[str]]]:
    """Given a requirement string, returns the requirement name and set of extras, if extras specified.
    Else, returns (None, None)
    """

    # https://www.python.org/dev/peps/pep-0508/#grammar
    extras_pattern = re.compile(
        r"^\s*([0-9A-Za-z][0-9A-Za-z_.\-]*)\s*\[\s*([0-9A-Za-z][0-9A-Za-z_.\-]*(?:\s*,\s*[0-9A-Za-z][0-9A-Za-z_.\-]*)*)\s*\]"
    )

    matches = extras_pattern.match(requirement)
    if matches:
        return (
            canonicalize_name(matches.group(1)),
            {extra.strip() for extra in matches.group(2).split(",")},
        )

    return None, None


def _setup_namespace_pkg_compatibility(wheel_dir: str) -> None:
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
        wheel_dir,
        ignored_dirnames=["%s/bin" % wheel_dir],
    )

    for ns_pkg_dir in namespace_pkg_dirs:
        namespace_pkgs.add_pkgutil_style_namespace_pkg_init(ns_pkg_dir)


def _extract_wheel(
    wheel_file: str,
    extras: Dict[str, Set[str]],
    enable_implicit_namespace_pkgs: bool,
    installation_dir: Path = Path("."),
) -> None:
    """Extracts wheel into given directory and creates py_library and filegroup targets.

    Args:
        wheel_file: the filepath of the .whl
        installation_dir: the destination directory for installation of the wheel.
        extras: a list of extras to add as dependencies for the installed wheel
        enable_implicit_namespace_pkgs: if true, disables conversion of implicit namespace packages and will unzip as-is
    """

    whl = wheel.Wheel(wheel_file)
    whl.unzip(installation_dir)

    if not enable_implicit_namespace_pkgs:
        _setup_namespace_pkg_compatibility(installation_dir)

    extras_requested = extras[whl.name] if whl.name in extras else set()
    # Packages may create dependency cycles when specifying optional-dependencies / 'extras'.
    # Example: github.com/google/etils/blob/a0b71032095db14acf6b33516bca6d885fe09e35/pyproject.toml#L32.
    self_edge_dep = set([whl.name])
    whl_deps = sorted(whl.dependencies(extras_requested) - self_edge_dep)

    with open(os.path.join(installation_dir, "metadata.json"), "w") as f:
        metadata = {
            "name": whl.name,
            "version": whl.version,
            "deps": whl_deps,
            "entry_points": [
                {
                    "name": name,
                    "module": module,
                    "attribute": attribute,
                }
                for name, (module, attribute) in sorted(whl.entry_points().items())
            ],
        }
        json.dump(metadata, f)


def main() -> None:
    args = arguments.parser(description=__doc__).parse_args()
    deserialized_args = dict(vars(args))
    arguments.deserialize_structured_args(deserialized_args)

    _configure_reproducible_wheels()

    base_pip_args = [sys.executable, "-m", "pip"]

    pip_args = (
        base_pip_args
        + (["--isolated"] if args.isolated else [])
        + (["download", "--only-binary=:all:"] if args.download_only else ["wheel"])
        + ["--no-deps"]
        + deserialized_args["extra_pip_args"]
    )

    requirement_file = NamedTemporaryFile(mode="wb", delete=False)
    try:
        requirement_file.write(args.requirement.encode("utf-8"))
        requirement_file.flush()
        # Close the file so pip is allowed to read it when running on Windows.
        # For more information, see: https://bugs.python.org/issue14243
        requirement_file.close()
        # Requirement specific args like --hash can only be passed in a requirements file,
        # so write our single requirement into a temp file in case it has any of those flags.
        requirement_file_args = ["-r", requirement_file.name]
        pip_args.extend(requirement_file_args)

        env = os.environ.copy()
        env.update(deserialized_args["environment"])
        # Assumes any errors are logged by pip so do nothing. This command will fail if pip fails
        check = not args.download_only
        res = subprocess.run(pip_args, check=check, env=env)
        # fallback for source distributable
        if res.returncode != 0:
            pip_cmd = base_pip_args + ["wheel", "--no-deps"] + requirement_file_args
            subprocess.run(pip_cmd, check=True, env=env)

    finally:
        try:
            os.unlink(requirement_file.name)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise

    name, extras_for_pkg = _parse_requirement_for_extra(args.requirement)
    extras = {name: extras_for_pkg} if extras_for_pkg and name else dict()

    whl = next(iter(glob.glob("*.whl")))
    _extract_wheel(
        wheel_file=whl,
        extras=extras,
        enable_implicit_namespace_pkgs=args.enable_implicit_namespace_pkgs,
    )


if __name__ == "__main__":
    main()
