#!/usr/bin/env python
# encoding: utf-8

"""
btoolcheck.py - Custom search command wrapping 'splunk btool check'

Identifies typos and invalid keys in Splunk .conf files.
Usage: | btoolcheck [conf=<conf-file>] [app=<app-name>]
"""

import os
import re
import sys
import time
import subprocess

# Add lib/ to path for splunklib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from splunklib.searchcommands import (
    dispatch,
    GeneratingCommand,
    Configuration,
    Option,
    validators,
)

# Constants
SPLUNK_HOME = os.environ.get("SPLUNK_HOME", "/opt/splunk")
SPLUNK_BIN = os.path.join(SPLUNK_HOME, "bin", "splunk")
SUBPROCESS_TIMEOUT = 120  # seconds

# Best-effort extraction patterns — used to enrich events with structured
# fields when lines happen to match, but every line of output is emitted
# regardless of whether these match.

# Extract app name from file path
APP_FROM_PATH_PATTERN = re.compile(
    r"/etc/(?:apps|slave-apps|deployment-apps|manager-apps|peer-apps)/([^/]+)/|"
    r"/etc/users/[^/]+/([^/]+)/"
)

# Extract conf file name from path: /path/to/savedsearches.conf -> savedsearches
CONF_NAME_FROM_PATH_PATTERN = re.compile(r"/([^/]+)\.conf")

# Extract stanza name: [stanza_name]
STANZA_PATTERN = re.compile(r"\[([^\]]*)\]")

# Extract file path containing .conf
CONF_PATH_PATTERN = re.compile(r"(/\S+\.conf|[A-Z]:\\\S+\.conf)")

# Extract line number after "line <N>"
LINE_NUMBER_PATTERN = re.compile(r"line\s+(\d+)")

# Extract message type from start of line
MESSAGE_TYPE_PATTERN = re.compile(r"^(Invalid key|Possible typo|No spec file)")

# Extract key_name and value from "key_name (value: some_value)."
KEY_VALUE_PATTERN = re.compile(r":\s*(\S+)\s+\(value:\s*(.*?)\)\.")


@Configuration()
class BtoolCheckCommand(GeneratingCommand):
    """
    | btoolcheck [conf=<conf-file>] [app=<app-name>]

    Runs 'splunk btool check' and returns structured results identifying
    invalid keys and possible typos in .conf files.
    """

    conf = Option(
        doc="Filter results to a specific conf file (without .conf extension). "
            "Example: conf=inputs. If omitted, shows all results.",
        require=False,
        default=None,
    )

    app = Option(
        doc="Filter results to a specific Splunk app. "
            "Example: app=Splunk_TA_windows. If omitted, shows all results.",
        require=False,
        default=None,
    )

    def generate(self):
        """Run btool check and yield one event per line of output."""

        # btool check is a global-only operation — it does not support
        # --app or conf-file prefixes. Both conf= and app= work by
        # filtering the global output after the fact.
        conf_filter = None
        if self.conf:
            conf_filter = self.conf.replace(".conf", "")

        app_filter = None
        if self.app:
            app_filter = self.app.strip()

        # Run btool check (always global)
        try:
            stdout, stderr, returncode = self._run_btool_check()
        except FileNotFoundError:
            yield self._make_event(
                "ERROR: Splunk binary not found at {}. "
                "Verify SPLUNK_HOME is set correctly.".format(SPLUNK_BIN)
            )
            return
        except subprocess.TimeoutExpired:
            yield self._make_event(
                "ERROR: btool check timed out ({}s limit).".format(
                    SUBPROCESS_TIMEOUT
                )
            )
            return
        except Exception as e:
            yield self._make_event(
                "ERROR: running btool check: {}".format(str(e))
            )
            return

        # Emit every non-empty line from stdout and stderr as an event.
        # btool may write findings to either stream.
        total_lines = 0
        for source in [stdout, stderr]:
            if not source:
                continue
            for line in source.splitlines():
                line = line.strip()
                if line:
                    event = self._make_event(line)
                    # Apply conf= filter if specified
                    if conf_filter and event["conf_file_name"] != conf_filter:
                        continue
                    # Apply app= filter if specified
                    if app_filter and event["app_name"] != app_filter:
                        continue
                    total_lines += 1
                    yield event

        # Summary event
        filters = []
        if conf_filter:
            filters.append("conf={}".format(conf_filter))
        if app_filter:
            filters.append("app={}".format(app_filter))
        mode = ", ".join(filters) if filters else "all"
        yield self._make_event(
            "btool check complete ({}): {} line(s) of output.".format(
                mode, total_lines
            )
        )

    def _run_btool_check(self):
        """
        Execute: splunk cmd btool check
        btool check is a global operation — it does not accept --app or
        a conf file prefix. Filtering is done on the output in generate().
        Returns (stdout_str, stderr_str, returncode)
        """
        cmd = [SPLUNK_BIN, "cmd", "btool", "check"]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
        )
        stdout, stderr = proc.communicate(timeout=SUBPROCESS_TIMEOUT)

        stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""

        return stdout_str, stderr_str, proc.returncode

    def _make_event(self, raw_line):
        """
        Create an event from a raw btool output line.
        Every line becomes an event. Structured fields are extracted
        best-effort — if a pattern doesn't match, that field is empty.
        """
        event = {
            "_time": time.time(),
            "_raw": raw_line,
            "message_type": "",
            "file_path": "",
            "conf_file_name": "",
            "app_name": "",
            "stanza": "",
            "line_number": 0,
            "key_name": "",
            "value": "",
        }

        # Best-effort: extract message type
        msg_match = MESSAGE_TYPE_PATTERN.search(raw_line)
        if msg_match:
            event["message_type"] = msg_match.group(1)

        # Best-effort: extract file path
        path_match = CONF_PATH_PATTERN.search(raw_line)
        if path_match:
            file_path = path_match.group(1)
            event["file_path"] = file_path

            # Extract conf file name from the path
            conf_match = CONF_NAME_FROM_PATH_PATTERN.search(file_path)
            if conf_match:
                event["conf_file_name"] = conf_match.group(1)

            # Extract app name from the path
            app_match = APP_FROM_PATH_PATTERN.search(file_path)
            if app_match:
                event["app_name"] = app_match.group(1) or app_match.group(2) or ""
            elif "/etc/system/" in file_path:
                event["app_name"] = "_system"

        # Best-effort: extract stanza
        stanza_match = STANZA_PATTERN.search(raw_line)
        if stanza_match:
            event["stanza"] = stanza_match.group(1)

        # Best-effort: extract line number
        line_match = LINE_NUMBER_PATTERN.search(raw_line)
        if line_match:
            event["line_number"] = int(line_match.group(1))

        # Best-effort: extract key_name and value
        kv_match = KEY_VALUE_PATTERN.search(raw_line)
        if kv_match:
            event["key_name"] = kv_match.group(1)
            event["value"] = kv_match.group(2)

        return event


dispatch(BtoolCheckCommand, sys.argv, sys.stdin, sys.stdout, __name__)
