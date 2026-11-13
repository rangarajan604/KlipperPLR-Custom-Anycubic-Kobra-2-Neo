# Run a shell command via gcode
#
# Copyright (C) 2019  Eric Callahan <arksine.code@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
import os
import shlex
import subprocess


class ShellCommand:
    def __init__(self, config):
        self.name = config.get_name().split()[-1]
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        command = os.path.expanduser(config.get("command"))
        self.command = shlex.split(command)
        self.timeout = config.getfloat("timeout", 2.0, above=0.0)
        self.verbose = config.getboolean("verbose", True)
        self.proc_fd = None
        self.partial_output = ""
        self.gcode.register_mux_command(
            "RUN_SHELL_COMMAND",
            "CMD",
            self.name,
            self.cmd_RUN_SHELL_COMMAND,
            desc=self.cmd_RUN_SHELL_COMMAND_help,
        )

    def _process_output(self, eventtime):
        if self.proc_fd is None:
            return
        try:
            data = os.read(self.proc_fd, 4096)
        except OSError:
            return
        data = self.partial_output + data.decode(errors="replace")
        if "\n" not in data:
            self.partial_output = data
            return
        if data[-1] != "\n":
            split = data.rfind("\n") + 1
            self.partial_output = data[split:]
            data = data[:split]
        else:
            self.partial_output = ""
        self.gcode.respond_info(data)

    cmd_RUN_SHELL_COMMAND_help = "Run a configured Linux shell command"

    def cmd_RUN_SHELL_COMMAND(self, params):
        gcode_params = shlex.split(params.get("PARAMS", ""))
        reactor = self.printer.get_reactor()
        try:
            proc = subprocess.Popen(
                self.command + gcode_params,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except OSError as exc:
            logging.exception("shell_command: Command {%s} failed", self.name)
            raise self.gcode.error(f"Error running command {{{self.name}}}: {exc}")

        hdl = None
        if self.verbose:
            self.proc_fd = proc.stdout.fileno()
            self.gcode.respond_info(f"Running Command {{{self.name}}}...:")
            hdl = reactor.register_fd(self.proc_fd, self._process_output)
        eventtime = reactor.monotonic()
        endtime = eventtime + self.timeout
        while eventtime < endtime and proc.poll() is None:
            eventtime = reactor.pause(eventtime + 0.05)

        completed = proc.poll() is not None
        if not completed:
            proc.terminate()
            proc.wait(timeout=2.0)
        if self.verbose:
            if self.partial_output:
                self.gcode.respond_info(self.partial_output)
                self.partial_output = ""
            message = (
                f"Command {{{self.name}}} finished\n"
                if completed and proc.returncode == 0
                else f"Command {{{self.name}}} failed (exit={proc.returncode})\n"
                if completed
                else f"Command {{{self.name}}} timed out\n"
            )
            self.gcode.respond_info(message)
            reactor.unregister_fd(hdl)
            self.proc_fd = None
        if not completed:
            raise self.gcode.error(f"Command {{{self.name}}} timed out")
        if proc.returncode:
            raise self.gcode.error(
                f"Command {{{self.name}}} failed with exit code {proc.returncode}"
            )


def load_config_prefix(config):
    return ShellCommand(config)
