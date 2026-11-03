#!/usr/bin/env python3
"""PreToolUse guard shared by Claude Code and Codex.

Blocks destructive git commands, recursive rm on root/home/wildcard paths,
reading or writing secret files, and running code-review-graph through the
shell. Commands are tokenized, so words inside branch names or commit
messages do not trigger it. Exit 2 blocks the call and sends the reason on
stderr back to the agent; exit 0 lets it through.
"""
import json
import os
import re
import shlex
import sys

OPERATORS = {";", "&&", "||", "|", "&", "\n", "(", ")", "|&"}
REDIRECTS = {">", ">>", "<", "&>", "2>", "1>", ">|"}
WRAPPERS = {"sudo", "command", "env", "nohup", "time", "exec", "xargs"}
SECRET_READERS = {"cat", "less", "more", "head", "tail", "bat", "nl", "strings", "xxd", "od",
                  "base64", "source", ".", "grep", "rg", "awk", "sed", "vi", "vim", "nano",
                  "code", "open", "cut", "sort", "diff", "type", "Get-Content"}
SAFE_ENV_SUFFIXES = (".example", ".sample", ".template", ".dist")
KEY_FILE = re.compile(r"^(id_rsa|id_ed25519|id_ecdsa)$|\.(pem|key|p12|pfx)$")
DANGEROUS_RM_TARGETS = {"/", "/*", "~", "~/", "~/*", "$HOME", "${HOME}", "$HOME/", "${HOME}/",
                        "$HOME/*", "${HOME}/*", "*", ".", "..", "./", "../", "./*"}
GRAPH_CLI_ALLOWED = {"install", "--help", "-h", "--version", "-V"}
PATCH_FILE_LINE = re.compile(r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+)$", re.M)


def is_secret_path(path: str) -> bool:
    name = os.path.basename(str(path).strip().strip("'\""))
    if name == ".env" or (name.startswith(".env.") and not name.endswith(SAFE_ENV_SUFFIXES)):
        return True
    return bool(KEY_FILE.search(name))


def tokenize(cmd: str) -> list:
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
    """Drop VAR=value assignments and wrappers like sudo/env before the command word."""
    i = 0
    while i < len(words) and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[i]) or words[i] in WRAPPERS):
        i += 1
        while i < len(words) and words[i - 1] in WRAPPERS and words[i].startswith("-"):
            i += 1
    return words[i:]


def short_flags(args: list) -> str:
    return "".join(a[1:] for a in args if re.match(r"^-[A-Za-z]+$", a))


def check_git(args: list):
    i = 0
    while i < len(args) and args[i].startswith("-"):  # global options such as -C <dir>, -c k=v
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


def check_rm(args: list):
    options, targets, after_dashes = [], [], False
    for arg in args:
        if arg == "--" and not after_dashes:
            after_dashes = True
        elif arg.startswith("-") and not after_dashes:
            options.append(arg)
        else:
            targets.append(arg)
    flags = short_flags(options)
    recursive = "r" in flags or "R" in flags or "--recursive" in options
    if recursive and any(t.rstrip() in DANGEROUS_RM_TARGETS for t in targets):
        return "recursive rm on a root, home, or wildcard path"
    return None


def check_bash(cmd: str):
    tokens = tokenize(cmd)
    for i, token in enumerate(tokens):  # writing into a secret file through a redirect
        if token in REDIRECTS and i + 1 < len(tokens) and is_secret_path(tokens[i + 1]):
            return "the command writes to a secrets file"
    for segment in segments(tokens):
        words = [w for j, w in enumerate(segment)
                 if w not in REDIRECTS and (j == 0 or segment[j - 1] not in REDIRECTS)]
        words = strip_prefix(words)
        if not words:
            continue
        program, args = os.path.basename(words[0]), words[1:]
        if program == "git":
            reason = check_git(args)
            if reason:
                return reason
        elif program == "rm":
            reason = check_rm(args)
            if reason:
                return reason
        elif program == "code-review-graph" and args and args[0] not in GRAPH_CLI_ALLOWED:
            return ("code-review-graph runs through its MCP tools, not the shell "
                    "(use build_or_update_graph_tool and the other *_tool calls)")
        elif program in SECRET_READERS and any(is_secret_path(a) for a in args if not a.startswith("-")):
            return "the command reads a secrets file"
        elif program in ("cp", "mv", "scp", "rsync"):
            sources = [a for a in args if not a.startswith("-")][:-1]
            if any(is_secret_path(a) for a in sources):
                return "the command copies a secrets file"
    return None


def block(reason: str) -> None:
    sys.stderr.write(f"Blocked by harness guard: {reason}. "
                     "Ask the user to run it themselves or approve another approach.\n")
    sys.exit(2)


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    if not isinstance(event, dict):
        sys.exit(0)
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        sys.exit(0)

    if tool == "Bash":
        reason = check_bash(str(tool_input.get("command", "") or ""))
        if reason:
            block(reason)
    elif tool in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Read"):
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if is_secret_path(path):
            block(f"{os.path.basename(str(path))} is a secrets file")
    elif tool == "Grep":
        if is_secret_path(tool_input.get("path") or ""):
            block("the search targets a secrets file")
    elif tool == "apply_patch":
        for path in PATCH_FILE_LINE.findall(str(tool_input.get("command", "") or "")):
            if is_secret_path(path):
                block(f"{os.path.basename(path.strip())} is a secrets file")
    sys.exit(0)


if __name__ == "__main__":
    main()
