#!/usr/bin/env python3
"""PreToolUse guard for Claude Code, Codex and GitHub Copilot, on Windows and Unix.

Blocks destructive git commands, recursive deletes of root, home or wildcard
paths (rm, Remove-Item, rd /s), reading or writing secret files, and running
code-review-graph through the shell. Commands are tokenized, so words inside
branch names or commit messages do not trigger it. Exit 2 blocks the call and
sends the reason on stderr; every agent treats that as a denial.
"""
import os
import re
import shlex
import sys

sys.dont_write_bytecode = True  # keep ~/.agents free of __pycache__

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (IS_WINDOWS, POWERSHELL_TOOLS, input_paths, normalize_event,  # noqa: E402
                     patch_paths, read_event)

OPERATORS = {";", "&&", "||", "|", "&", "(", ")", "|&"}
REDIRECTS = {">", ">>", "<", "&>", "2>", "1>", ">|"}
WRAPPERS = {"sudo", "command", "env", "nohup", "time", "exec", "xargs", "cmd", "/c", "cmd.exe"}
SECRET_READERS = {"cat", "less", "more", "head", "tail", "bat", "nl", "strings", "xxd", "od",
                  "base64", "source", ".", "grep", "rg", "awk", "sed", "vi", "vim", "nano", "code",
                  "open", "cut", "sort", "diff", "type", "get-content", "gc", "select-string", "sls",
                  "findstr", "notepad", "import-csv"}
COPIERS = {"cp", "mv", "scp", "rsync", "copy", "move", "copy-item", "move-item", "cpi", "mi",
           "xcopy", "robocopy"}
PS_REMOVERS = {"remove-item", "ri", "del", "erase", "rd", "rmdir", "rm"}
SAFE_ENV_SUFFIXES = (".example", ".sample", ".template", ".dist")
KEY_FILE = re.compile(r"^(id_rsa|id_ed25519|id_ecdsa)$|\.(pem|key|p12|pfx)$", re.I)
HOME_TOKENS = {"~", "$home", "${home}", "$env:userprofile", "$env:home", "%userprofile%",
               "$env:homedrive", "%homedrive%"}
GRAPH_CLI_ALLOWED = {"install", "--help", "-h", "--version", "-V"}


def is_secret_path(path: str) -> bool:
    name = re.split(r"[\\/]", str(path).strip().strip("'\""))[-1]
    lower = name.lower()
    if lower == ".env" or (lower.startswith(".env.") and not lower.endswith(SAFE_ENV_SUFFIXES)):
        return True
    return bool(KEY_FILE.search(name))


def is_dangerous_target(target: str) -> bool:
    t = target.strip().strip("'\"").replace("\\", "/").rstrip()
    if not t:
        return False
    if re.fullmatch(r"[A-Za-z]:/?(\*|\*\.\*)?", t):  # drive root such as C:\ or C:\*
        return True
    base = t.rstrip("/*").rstrip("/") if t not in ("/", "/*") else t
    if t in ("/", "/*", "*", "*.*", ".", "..", "./", "../", "./*"):
        return True
    return base.lower() in HOME_TOKENS


def tokenize(cmd: str, powershell: bool) -> list:
    if powershell or IS_WINDOWS:
        cmd = cmd.replace("\\", "/")  # Windows paths: keep separators, avoid shell escapes
    lexer = shlex.shlex(cmd.replace("\n", " ; "), posix=True, punctuation_chars=";&|()<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:  # unbalanced quotes: fall back to a plain split
        return cmd.split()


def segments(tokens: list) -> list:
    current, result = [], []
    for token in tokens:
        if token in OPERATORS:
            if current:
                result.append(current)
            current = []
        else:
            current.append(token)
    if current:
        result.append(current)
    return result


def strip_prefix(words: list) -> list:
    i = 0
    while i < len(words) and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[i]) or
                              words[i].lower() in WRAPPERS or words[i] == "&"):
        i += 1
        while i < len(words) and words[i - 1].lower() in WRAPPERS and words[i].startswith("-"):
            i += 1
    return words[i:]


def short_flags(args: list) -> str:
    return "".join(a[1:] for a in args if re.match(r"^-[A-Za-z]+$", a))


def check_git(args: list):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") else 1
    if i >= len(args):
        return None
    sub, rest = args[i], args[i + 1:]
    flags = short_flags(rest)
    if sub == "push" and ("f" in flags or any(a in ("--force", "--force-if-includes") or
                                              a.startswith("--force-with-lease") or
                                              (a.startswith("+") and len(a) > 1) for a in rest)):
        return "force push"
    if sub == "reset" and "--hard" in rest:
        return "git reset --hard"
    if sub == "clean" and ("f" in flags or "--force" in rest):
        return "git clean -f"
    if sub == "branch" and ("D" in flags or (("d" in flags or "--delete" in rest) and
                                             ("f" in flags or "--force" in rest))):
        return "git branch -D"
    return None


def split_options(args: list):
    options, targets, after_dashes = [], [], False
    for arg in args:
        if arg == "--" and not after_dashes:
            after_dashes = True
        elif (arg.startswith("-") or re.fullmatch(r"/[A-Za-z]", arg)) and not after_dashes:
            options.append(arg)
        else:
            targets.append(arg)
    return options, targets


def check_rm_unix(args: list):
    options, targets = split_options(args)
    flags = short_flags(options)
    recursive = "r" in flags or "R" in flags or "--recursive" in options
    if recursive and any(is_dangerous_target(t) for t in targets):
        return "recursive delete of a root, home, or wildcard path"
    return None


def check_rm_powershell(args: list):
    options, targets = split_options(args)
    lowered = [o.lower() for o in options]
    recursive = any(o.startswith("-r") and "-recurse".startswith(o) for o in lowered) or \
        "/s" in lowered or "-recurse:$true" in lowered
    targets += [args[i + 1] for i, a in enumerate(args[:-1]) if a.lower() in ("-path", "-literalpath")]
    if recursive and any(is_dangerous_target(t) for t in targets):
        return "recursive delete of a root, home, or wildcard path"
    return None


def check_command(cmd: str, powershell: bool):
    tokens = tokenize(cmd, powershell)
    for i, token in enumerate(tokens):
        if token in REDIRECTS and i + 1 < len(tokens) and is_secret_path(tokens[i + 1]):
            return "the command writes to a secrets file"
    for segment in segments(tokens):
        words = [w for j, w in enumerate(segment)
                 if w not in REDIRECTS and (j == 0 or segment[j - 1] not in REDIRECTS)]
        words = strip_prefix(words)
        if not words:
            continue
        program = re.split(r"[\\/]", words[0])[-1].lower()
        if program.endswith(".exe"):
            program = program[:-4]
        args = words[1:]
        reason = None
        if program == "git":
            reason = check_git(args)
        elif program in PS_REMOVERS and (powershell or program not in ("rm", "rmdir")):
            reason = check_rm_powershell(args)
        elif program in ("rm", "rmdir"):
            reason = check_rm_unix(args)
        elif program == "code-review-graph" and args and args[0] not in GRAPH_CLI_ALLOWED:
            reason = ("code-review-graph runs through its MCP tools, not the shell "
                      "(use build_or_update_graph_tool and the other *_tool calls)")
        elif program in SECRET_READERS and any(is_secret_path(a) for a in args if not a.startswith("-")):
            reason = "the command reads a secrets file"
        elif program in COPIERS:
            sources = [a for a in args if not a.startswith("-")][:-1]
            if any(is_secret_path(a) for a in sources):
                reason = "the command copies a secrets file"
        if reason:
            return reason
    return None


def check_shell(cmd: str, tool: str):
    if tool in POWERSHELL_TOOLS:
        return check_command(cmd, powershell=True)
    reason = check_command(cmd, powershell=False)
    if not reason and IS_WINDOWS:  # Codex and Copilot run PowerShell on Windows under any name
        reason = check_command(cmd, powershell=True)
    return reason


def block(reason: str) -> None:
    sys.stderr.write(f"Blocked by harness guard: {reason}. "
                     "Ask the user to run it themselves or approve another approach.\n")
    sys.exit(2)


def main() -> None:
    event = read_event()
    if event is None:
        sys.exit(0)
    e = normalize_event(event)
    tool_input = e["input"]

    if e["kind"] == "shell":
        reason = check_shell(str(tool_input.get("command", "") or ""), e["tool"])
        if reason:
            block(reason)
    elif e["kind"] in ("edit", "read"):
        for path in input_paths(tool_input):
            if is_secret_path(path):
                block(f"{re.split(r'[/]', path.replace(chr(92), '/'))[-1]} is a secrets file")
    elif e["kind"] == "patch":
        for path in patch_paths(str(tool_input.get("command", "") or "")):
            if is_secret_path(path):
                block(f"{re.split(r'[/]', path.replace(chr(92), '/'))[-1]} is a secrets file")
    sys.exit(0)


if __name__ == "__main__":
    main()
