from __future__ import annotations

import asyncio
import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable


@dataclass
class RobotTool:
    name: str
    description: str
    parameters: dict[str, Any]
    command: str
    executor: RobotExecutor

    def to_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.parameters,
                "required": [
                    k for k, v in self.parameters.items() if not v.get("optional")
                ],
            },
        }

    async def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        return await self.executor.execute(self.command, args)


class SafetyError(Exception):
    def __init__(self, message: str, command: str, tool_args: dict[str, Any]):
        super().__init__(message)
        self.command = command
        self.tool_args = tool_args


@dataclass
class RobotExecutor:
    robot_name: str
    daemon_host: str = "localhost"
    daemon_port: int = 9100
    use_subprocess: bool = False
    _process: asyncio.subprocess.Process | None = field(
        default=None, init=False, repr=False
    )

    async def execute(self, cmd: str, args: dict[str, Any]) -> dict[str, Any]:
        if self.use_subprocess:
            return await self._execute_subprocess(cmd, args)
        return await self._execute_daemon(cmd, args)

    async def _execute_subprocess(self, cmd: str, args: dict[str, Any]) -> dict[str, Any]:
        cli_args = [f"--{k}={v}" for k, v in args.items() if v is not None]
        full_cmd = ["sdk2cli", "--robot", self.robot_name, cmd, *cli_args]

        proc = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 2:
            raise SafetyError(
                stderr.decode().strip() or "Safety limit triggered",
                cmd,
                args,
            )

        if proc.returncode != 0:
            return {
                "ok": False,
                "error": stderr.decode().strip(),
                "exit_code": proc.returncode,
            }

        try:
            return {"ok": True, "result": json.loads(stdout.decode())}
        except json.JSONDecodeError:
            return {"ok": True, "result": stdout.decode().strip()}

    async def _execute_daemon(self, cmd: str, args: dict[str, Any]) -> dict[str, Any]:
        reader, writer = await asyncio.open_connection(
            self.daemon_host, self.daemon_port
        )
        payload = json.dumps({"robot": self.robot_name, "cmd": cmd, "args": args})
        writer.write(payload.encode() + b"\n")
        await writer.drain()

        data = await reader.readline()
        writer.close()
        await writer.wait_closed()

        response = json.loads(data.decode())
        if response.get("exit_code") == 2:
            raise SafetyError(
                response.get("error", "Safety limit triggered"),
                cmd,
                args,
            )
        return response


def parse_manifest_tools(manifest_text: str) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw_line in manifest_text.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        cmd_match = re.match(r"^cmd:\s*(.+)$", line)
        if cmd_match:
            if current:
                tools.append(current)
            current = {
                "command": cmd_match.group(1).strip(),
                "name": cmd_match.group(1).strip().replace(".", "_"),
                "description": "",
                "parameters": {},
            }
            continue

        if current is None:
            continue

        desc_match = re.match(r"^desc:\s*(.+)$", line)
        if desc_match:
            current["description"] = desc_match.group(1).strip()
            continue

        param_match = re.match(
            r"^param:\s*(\w+)\s*\((\w+)\)\s*(?:\[optional\])?\s*(?:-\s*(.+))?$", line
        )
        if param_match:
            pname = param_match.group(1)
            ptype = param_match.group(2)
            pdesc = param_match.group(3) or ""
            optional = "[optional]" in line
            type_map = {
                "float": "number",
                "int": "integer",
                "str": "string",
                "bool": "boolean",
                "string": "string",
                "number": "number",
                "integer": "integer",
                "boolean": "boolean",
            }
            current["parameters"][pname] = {
                "type": type_map.get(ptype, "string"),
                "description": pdesc.strip(),
            }
            if optional:
                current["parameters"][pname]["optional"] = True
            continue

    if current:
        tools.append(current)

    return tools


def make_robot_tools(
    robot_name: str,
    manifest_text: str,
    executor: RobotExecutor | None = None,
) -> list[RobotTool]:
    if executor is None:
        executor = RobotExecutor(robot_name=robot_name, use_subprocess=True)

    parsed = parse_manifest_tools(manifest_text)
    tools: list[RobotTool] = []
    for entry in parsed:
        params = dict(entry["parameters"])
        for v in params.values():
            v.pop("optional", None)
        tool = RobotTool(
            name=entry["name"],
            description=entry["description"],
            parameters=entry["parameters"],
            command=entry["command"],
            executor=executor,
        )
        tools.append(tool)
    return tools
