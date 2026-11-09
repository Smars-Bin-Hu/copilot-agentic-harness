"""A built-in copy of the shipped gate policy (1.7.38, C13 F2c).

When `gate.json`, or the company's or the person's layer on it, cannot be read, the gate used to raise, the hook counted that as "no opinion", and every local protection passed (guardrail files, writes outside the task
folder, git writes). Now the gate runs on this copy: the shipped guardrail paths, the terminal rules and the git setting, without the company's and the person's layers (they are the part that cannot be read). The
rules are the same as the shipped ones; `fallback.py` adds the strict part (a write passes only inside the folder of an open task, no git write passes) and the reason names the file and the fault.

This is a copy of `.harness/policies/gate.json`. When that file changes, change this one: `test_c13_f2.BuiltinPolicyTests` fails until the two say the same. The `description` of the file is left out. The text is ASCII (`\\uXXXX` for the Chinese in the `why` of a rule): the engine's sources hold no Chinese outside the message tables.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict

_JSON = r'''
{
 "schema_version": 1,
 "guardrail_paths": [
  ".github/hooks/**",
  ".harness/policies/**",
  ".harness/engine/**",
  ".harness/bin/**",
  ".harness/toolpacks/**",
  ".harness/.env",
  "Start Harness.command",
  "Start Harness.cmd",
  ".harness/registry.json",
  ".harness/runtime/**",
  ".vscode/settings.json",
  ".vscode/mcp.json",
  "LICENSE",
  "NOTICE"
 ],
 "extra_guardrail_paths": [],
 "admin_locked_paths": [
  ".harness/runtime/**"
 ],
 "cli_owned_paths": [
  ".workspace/sandbox/tasks/*/.task/**",
  ".workspace/sandbox/tasks/*/PROMOTE-PLAN.diff",
  ".workspace/sandbox/tasks/*/CHANGES.diff",
  ".workspace/sandbox/tasks/*/CHANGES_r*.diff",
  ".workspace/sandbox/tasks/*/REVIEW/**",
  ".workspace/sandbox/tasks/*/SNAPSHOT/**",
  ".workspace/sandbox/tasks/*/OUTBOX/**",
  ".workspace/reports/**"
 ],
 "terminal": {
  "guardrail_write": [
   {
    "why": {
     "en": "it writes, deletes or moves one",
     "zh": "\u5199\u5165\u3001\u5220\u9664\u6216\u79fb\u52a8"
    },
    "pattern": "(?:>>?\\s*|\\btee\\b[^;&|\\n]*\\s)[\"']?(?:[^\\s\"';&|<>]*/)?{guard}"
   },
   {
    "why": {
     "en": "it writes, deletes or changes the rights of one",
     "zh": "\u5199\u5165\u3001\u5220\u9664\u6216\u6539\u6743\u9650"
    },
    "pattern": "{cmd}(?:rm|rmdir|unlink|mv|touch|chmod|chown|truncate|ln|mkdir|patch|del|erase|rd|ren|move|remove-item|move-item|rename-item|new-item|set-content|add-content|clear-content|out-file)\\b[^;&|\\n]*{guard}"
   },
   {
    "why": {
     "en": "it deletes or rewrites one with find",
     "zh": "\u7528 find \u5220\u9664\u6216\u6539\u5199"
    },
    "pattern": "\\bfind\\b[^;&|\\n]*{guard}[^;&|\\n]*(?:-delete\\b|-exec\\s+(?:rm|mv|chmod|sed)\\b)"
   },
   {
    "why": {
     "en": "it copies into one",
     "zh": "\u590d\u5236\u5230\u5b83\u91cc\u9762"
    },
    "pattern": "{cmd}(?:cp|rsync|install|copy|xcopy|copy-item)\\b[^;&|\\n]*{guard}[^\\s\"';&|]*[\"']?\\s*(?:[;&|]|$)"
   },
   {
    "why": {
     "en": "it edits one in place",
     "zh": "\u539f\u5730\u4fee\u6539"
    },
    "pattern": "{cmd}(?:sed|perl|ruby)\\b[^;&|\\n]*\\s-[a-z]*i[a-z]*\\b[^;&|\\n]*{guard}"
   },
   {
    "why": {
     "en": "it overwrites or rewrites one with git",
     "zh": "\u7528 git \u8986\u76d6\u6216\u6539\u5199"
    },
    "pattern": "{cmd}git\\s+(?:checkout|restore|rm|mv|apply|stash|reset)\\b[^;&|\\n]*{guard}"
   },
   {
    "why": {
     "en": "it rewrites one with an inline script",
     "zh": "\u7528\u5185\u8054\u811a\u672c\u6539\u5199"
    },
    "pattern": "{cmd}(?:python3?|py|node|perl|ruby)\\b[^\\n]*\\s-[ce]\\s[^\\n]*{guard}[^\\n]*(?:open|write|unlink|remove|rmtree|rename|replace|truncate)"
   }
  ],
  "deny": [
   {
    "why": {
     "en": "it recursively deletes the root, the home folder or the current folder",
     "zh": "\u9012\u5f52\u5220\u9664\u6839\u76ee\u5f55\u3001\u5bb6\u76ee\u5f55\u6216\u5f53\u524d\u76ee\u5f55"
    },
    "pattern": "{cmd}rm\\s+(?:-[a-z]+\\s+)*-[a-z]*(?:r[a-z]*f|f[a-z]*r)[a-z]*\\s+(?:/|~|\\$home|\\*|\\.|\\.\\.)/?\\*?(?:\\s|$|[;&|])"
   },
   {
    "why": {
     "en": "it recursively force-deletes the root, the home folder or every file",
     "zh": "\u9012\u5f52\u5f3a\u5236\u5220\u9664\u6839\u76ee\u5f55\u3001\u5bb6\u76ee\u5f55\u6216\u6240\u6709\u6587\u4ef6"
    },
    "pattern": "{cmd}remove-item\\b[^;&|\\n]*-recurse[^;&|\\n]*\\s(?:/|~|\\*|[a-z]:/?)(?:\\s|$|[;&|])"
   },
   {
    "why": {
     "en": "it hands a download straight to a shell or an interpreter to run",
     "zh": "\u628a\u4e0b\u8f7d\u7684\u5185\u5bb9\u76f4\u63a5\u4ea4\u7ed9 shell \u6216\u89e3\u91ca\u5668\u6267\u884c"
    },
    "pattern": "{cmd}(?:curl|wget|iwr|invoke-webrequest|irm|invoke-restmethod)\\b[^\\n]*\\|\\s*(?:sudo\\s+)?(?:sh|bash|zsh|python3?|py|node|perl|iex|invoke-expression)\\b"
   },
   {
    "why": {
     "en": "it formats a disk or writes to a disk device directly",
     "zh": "\u683c\u5f0f\u5316\u78c1\u76d8\u6216\u76f4\u63a5\u5199\u78c1\u76d8\u8bbe\u5907"
    },
    "pattern": "{cmd}mkfs(?:\\.\\w+)?\\b|{cmd}dd\\b[^\\n]*\\bof=/dev/|>\\s*/dev/(?:sd|nvme|disk)"
   },
   {
    "why": {
     "en": "it runs with administrator rights",
     "zh": "\u4f1a\u7528\u7ba1\u7406\u5458\u6743\u9650\u8fd0\u884c"
    },
    "pattern": "{cmd}(?:sudo|gsudo|doas|runas)(?:\\.exe)?\\b|-verb\\s+[\\\"']?runas\\b"
   },
   {
    "why": {
     "en": "it changes rights recursively, or deletes containers, clusters or infrastructure",
     "zh": "\u4f1a\u9012\u5f52\u6539\u6743\u9650\uff0c\u6216\u5220\u9664\u5bb9\u5668\u3001\u96c6\u7fa4\u3001\u57fa\u7840\u8bbe\u65bd"
    },
    "pattern": "\\b(?:chmod|chown|chgrp)\\s+(?:-R\\b|--recursive\\b)|\\bicacls(?:\\.exe)?\\b[^;&|\\n]*\\s/t\\b|\\btakeown(?:\\.exe)?\\b[^;&|\\n]*\\s/r\\b|-recurse\\b[^\\n]*\\bset-acl\\b|\\bdocker(?:\\.exe)?\\s+(?:rm|rmi|system\\s+prune|volume\\s+rm)\\b|\\bkubectl(?:\\.exe)?\\s+delete\\b|\\bterraform(?:\\.exe)?\\s+(?:apply|destroy)\\b"
   },
   {
    "why": {
     "en": "only the user may run these, in their own terminal: approving a plan (task approve-plan), confirming the requirement (task confirm-req), approving a write-back (task approve-promote), recovering a promote that failed halfway (task recover), giving more checks, waiving them or dismissing one (task review extend, task review waive, task review dismiss), letting the agent run a test environment itself (task test runner), opening an environment for a task (task allow), pausing and resuming a task (task pause, task resume, and all at once: task offwork, task onwork), switching autorun on (task autorun on), serving the board with buttons that act (task board, task board --serve; an agent writes the page with task board --once), approving a git command (approve-command), approving a call to an outside system (approve-action), switching admin mode on (admin on), accepting the guardrail files as they are (doctor --accept). Setting how many checks a task gets (task review set) is the user's too. Tell the user to run the command; do not run it yourself",
     "zh": "\u6279\u51c6\u8ba1\u5212\uff08task approve-plan\uff09\u3001\u6279\u51c6\u56de\u5199\uff08task approve-promote\uff09\u3001\u6062\u590d\u4e2d\u9014\u51fa\u9519\u7684 promote\uff08task recover\uff09\u3001\u518d\u7ed9\u68c0\u67e5\u6b21\u6570\u3001\u653e\u884c\u6216\u4f5c\u5e9f\u4e00\u6b21\u68c0\u67e5\uff08task review extend\u3001task review waive\u3001task review dismiss\uff09\u3001\u8ba9 agent \u81ea\u5df1\u8dd1\u4e00\u4e2a\u6d4b\u8bd5\u73af\u5883\uff08task test runner\uff09\u3001\u4e3a\u4e00\u4e2a\u4efb\u52a1\u6253\u5f00\u4e00\u4e2a\u73af\u5883\uff08task allow\uff09\u3001\u6401\u7f6e\u548c\u6062\u590d\u4efb\u52a1\uff08task pause\u3001task resume\uff0c\u4ee5\u53ca\u4e00\u6b21\u5168\u90e8\uff1atask offwork\u3001task onwork\uff09\u3001\u5f00 autorun\uff08task autorun on\uff09\u3001\u542f\u52a8\u80fd\u64cd\u4f5c\u7684\u770b\u677f\u670d\u52a1\uff08task board\u3001task board --serve\uff1bagent \u53ea\u80fd\u7528 task board --once \u751f\u6210\u9875\u9762\uff09\u3001\u6279\u51c6 git \u547d\u4ee4\uff08approve-command\uff09\u3001\u6279\u51c6\u5916\u90e8\u8c03\u7528\uff08approve-action\uff09\u3001\u5f00 admin \u6a21\u5f0f\uff08admin on\uff09\u3001\u63a5\u53d7\u62a4\u680f\u6587\u4ef6\u73b0\u5728\u7684\u6837\u5b50\uff08doctor --accept\uff09\u53ea\u80fd\u7531\u7528\u6237\u5728\u81ea\u5df1\u7684\u7ec8\u7aef\u91cc\u8fd0\u884c\u3002\u8bbe\u5b9a\u4efb\u52a1\u7684\u68c0\u67e5\u6b21\u6570\uff08task review set\uff09\u4e5f\u53ea\u80fd\u7531\u7528\u6237\u6765\u505a\u3002\u544a\u8bc9\u7528\u6237\u8fd0\u884c\u8fd9\u6761\u547d\u4ee4\uff0c\u4e0d\u8981\u81ea\u5df1\u8fd0\u884c"
    },
    "pattern": "\\b(?:cli\\.py|harness(?:\\.cmd)?)\\s+(?:task\\s+(?:approve-plan|confirm-req|approve-promote|recover|pause|resume|offwork|onwork|autorun\\s+on|review\\s+(?:set|extend|waive|dismiss)|test\\s+runner|allow\\s+--env|board\\b(?![^;&|\\n]*\\s--once\\b))|approve-command|approve-action|admin\\s+on|doctor\\s+(?:[^;&|\\n]*\\s)?--accept)\\b"
   },
   {
    "why": {
     "en": "the agent never closes a task. When the work is done, run `harness task deliver --summary \"<text>\"` and stop: the board shows the task as to accept, and the user presses Accept and closes it (or keeps talking in the same task). If the user asks you to close one, tell them to use Close on the board",
     "zh": "agent \u4e0d\u81ea\u5df1\u5173\u4efb\u52a1\u3002\u5de5\u4f5c\u505a\u5b8c\u540e\u8fd0\u884c `harness task deliver --summary \"<text>\"` \u7136\u540e\u505c\u4e0b\uff1a\u770b\u677f\u4f1a\u628a\u4efb\u52a1\u663e\u793a\u4e3a\u201c\u5f85\u9a8c\u6536\u201d\uff0c\u7531\u7528\u6237\u70b9\u201c\u9a8c\u6536\u5e76\u5173\u95ed\u201d\uff08\u6216\u7ee7\u7eed\u5728\u540c\u4e00\u4e2a\u4efb\u52a1\u91cc\u8bf4\u8bdd\uff09\u3002\u7528\u6237\u8ba9\u4f60\u5173\u4efb\u52a1\u65f6\uff0c\u544a\u8bc9\u4ed6\u5728\u770b\u677f\u4e0a\u7528\u201c\u5173\u95ed\u201d"
    },
    "pattern": "\\b(?:cli\\.py|harness(?:\\.cmd)?)\\s+task\\s+close(?![\\w-])"
   }
  ],
  "ask": [
   {
    "why": {
     "en": "it deletes files",
     "zh": "\u5220\u9664\u6587\u4ef6"
    },
    "pattern": "{cmd}(?:rm|rmdir|unlink|del|erase|rd|remove-item)\\b|\\bxargs\\s+rm\\b|\\bfind\\b[^;&|\\n]*(?:-delete\\b|-exec\\s+rm\\b)"
   },
   {
    "why": {
     "en": "it rewrites or drops git history, branches or changes that are not committed",
     "zh": "\u4f1a\u6539\u5199\u6216\u4e22\u5f03 git \u5386\u53f2\u3001\u5206\u652f\u6216\u672a\u63d0\u4ea4\u7684\u6539\u52a8"
    },
    "pattern": "\\bgit\\s+(?:push|reset\\s+--hard|clean(?!\\s+(?:-[a-zA-Z]*n[a-zA-Z]*|--dry-run)(?![\\w-]))|checkout\\s+(?:-f|--force)|branch\\s+-D|stash\\s+(?:drop|clear)|restore(?!\\s+--staged)|filter-branch|reflog\\s+expire)\\b"
   },
   {
    "why": {
     "en": "it goes on the network",
     "zh": "\u4f1a\u8054\u7f51"
    },
    "pattern": "{cmd}(?:curl|wget|nc|ncat|ssh|scp|sftp|rsync|ftp|telnet|invoke-webrequest|iwr|invoke-restmethod|irm)\\b"
   },
   {
    "why": {
     "en": "it installs packages",
     "zh": "\u4f1a\u5b89\u88c5\u8f6f\u4ef6\u5305"
    },
    "pattern": "\\b(?:pip3?|(?:python3?|py)(?:\\s+-[0-9.]+)?\\s+-m\\s+pip|npm|pnpm|yarn|brew|apt|apt-get|choco|winget|gem|cargo)\\s+(?:install|add|i)\\b|\\bgo\\s+(?:install|get)\\b|{cmd}npx\\b"
   },
   {
    "why": {
     "en": "it deletes session logs",
     "zh": "\u4f1a\u5220\u9664\u4f1a\u8bdd\u65e5\u5fd7"
    },
    "pattern": "\\b(?:cli\\.py|harness(?:\\.cmd)?)\\s+logs\\s+prune\\b"
   }
  ]
 },
 "git": {
  "approval_minutes": 10
 },
 "circuit_breaker": {
  "repeat_limit": 3
 }
}
'''

POLICY: Dict[str, Any] = json.loads(_JSON)


def policy() -> Dict[str, Any]:
    """A fresh copy: the caller may change it."""
    return copy.deepcopy(POLICY)
