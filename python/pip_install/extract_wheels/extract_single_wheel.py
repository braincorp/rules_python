import argparse
import errno
import glob
import os
import subprocess
import sys
from tempfile import NamedTemporaryFile

from python.pip_install.extract_wheels import arguments, bazel, requirements
from python.pip_install.extract_wheels.annotation import annotation_from_str_path
from python.pip_install.extract_wheels.extract_wheels import (
    configure_reproducible_wheels,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build and/or fetch a single wheel based on the requirement passed in"
    )
    parser.add_argument(
        "--requirement",
        action="store",
        required=True,
        help="A single PEP508 requirement specifier string.",
    )
    parser.add_argument(
        "--annotation",
        type=annotation_from_str_path,
        help="A json encoded file containing annotations for rendered packages.",
    )
    parser.add_argument(
        "--pip_platform_definition",
        help="A pip platform definition in the form <platform>-<python_version>-<implementation>-<abi>",
    )
    arguments.parse_common_args(parser)
    args = parser.parse_args()
    deserialized_args = dict(vars(args))
    arguments.deserialize_structured_args(deserialized_args)

    configure_reproducible_wheels()

    base_pip_args = [sys.executable, "-m", "pip"]
    default_pip_args = [
        "wheel",
        "--no-deps",
        ] + deserialized_args["extra_pip_args"]
    if args.isolated:
        default_pip_args.append("--isolated")

    pip_platform_set = args.pip_platform_definition is not None

    if pip_platform_set:
        platform, python_version, implementation, abi = args.pip_platform_definition.split("-")
        platform_pip_args = [
            "download",
            "--no-deps",
            "--only-binary", ":all:",
            "--platform", platform,
            "--python-version", python_version,
            "--implementation", implementation,
            "--abi", abi
        ]

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
        pip_cmd = base_pip_args + default_pip_args + requirement_file_args
        if pip_platform_set:
            pip_cmd = base_pip_args + platform_pip_args + requirement_file_args

        env = os.environ.copy()
        env.update(deserialized_args["environment"])
        # Assumes any errors are logged by pip so do nothing. This command will fail if pip fails
        check = not pip_platform_set
        res = subprocess.run(pip_cmd, env=env, check=check)
        # fallback for pure python modules
        if pip_platform_set and res.returncode != 0:
            pip_cmd = base_pip_args + default_pip_args + requirement_file_args
            subprocess.run(pip_cmd, check=True, env=env)
    finally:
        try:
            os.unlink(requirement_file.name)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise

    name, extras_for_pkg = requirements._parse_requirement_for_extra(args.requirement)
    extras = {name: extras_for_pkg} if extras_for_pkg and name else dict()

    whl = next(iter(glob.glob("*.whl")))
    bazel.extract_wheel(
        wheel_file=whl,
        extras=extras,
        pip_data_exclude=deserialized_args["pip_data_exclude"],
        enable_implicit_namespace_pkgs=args.enable_implicit_namespace_pkgs,
        incremental=True,
        repo_prefix=args.repo_prefix,
        annotation=args.annotation,
    )


if __name__ == "__main__":
    main()
