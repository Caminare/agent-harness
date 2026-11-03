---
name: pr-description
description: Generate a structured PR description by diffing the current branch against a target branch, reading the changed files, pulling Jira ticket context, and writing pr_description.md. Use whenever the user asks to write, generate, or draft a PR description, PR body, or pull request summary.
---

# PR description

Act as a Principal Software Engineer. Produce a factual, concise PR description from the diff between the current branch and a target branch.

## 1. Target branch
Ask: "Which branch should I compare against? (for example `master`, `develop`)". Do not assume. Call it TARGET.

## 2. Collect the diff (run in parallel)
```bash
git diff --stat TARGET...HEAD
git log TARGET...HEAD --oneline
git branch --show-current
git diff --diff-filter=A --name-only TARGET...HEAD   # added
git diff --diff-filter=M --name-only TARGET...HEAD   # modified
git diff --diff-filter=D --name-only TARGET...HEAD   # deleted
```

## 3. Jira context
Extract ticket keys (`[A-Z]+-\d+`) from the branch name and commit messages, deduplicate, and fetch each with the Atlassian tool (for example `getJiraIssue`, or `acli` if installed). Use the context to write an accurate summary, not to paste it. No tickets: rely on the diff.

## 4. Understand each change
Read each changed file or its diff chunk. Describe behavior (endpoints, models, consumers, config), not line counts.

## 5. Tests
Test files match `*Test*`, `*Tests*`, `*Spec*`, `*.test.*`, `*.spec.*`, or live under `tests/` or `__tests__/`. For each: new or changed, and which scenarios it covers. List production files with no matching test change as coverage gaps.

## 6. Write `pr_description.md` at the repository root
```
This PR <one-sentence summary, grounded in Jira context when available>.

New
- `<path>`: <what was added>.

Changed
- `<path>`: <what changed>.

Testing
- `<test path>`: <scenarios covered>.
- Coverage gaps: <production files without test changes, or "None">.
```
Rules:
1. One bullet per file, or per logical group of small files. Paths in backticks. One line per bullet.
2. Only the New, Changed, and Testing sections. Omit New or Changed when empty.
3. Testing is always present; with no test changes write "No test changes on this branch."
4. Deleted files go under Changed, marked "removed". Test files appear only under Testing.

## 7. Report
Say "Written to `pr_description.md`." and print the file inline.
