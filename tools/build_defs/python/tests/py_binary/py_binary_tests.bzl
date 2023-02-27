# Copyright 2023 The Bazel Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for py_binary."""

load("//python:defs.bzl", "py_binary")
load(
    "//tools/build_defs/python/tests:py_executable_base_tests.bzl",
    "create_executable_tests",
)

def py_binary_test_suite(name):
    config = struct(rule = py_binary)

    native.test_suite(
        name = name,
        tests = create_executable_tests(config),
    )
