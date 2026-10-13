# 1. How a coding agent works

## In one sentence

An agent = a loop that calls tools. The model does not change your files directly. It says "I want to read this file", the program around it reads the file for it and hands back the result, and then it thinks about the next step.

## Chunks

### 1.1 The loop

```text
You say something
  -> the model thinks: what is to be done? which information is needed?
  -> the model sends one "tool call" (read a file, search, change a file, run a command ...)
  -> the program around it runs the call and hands the result back to the model as text
  -> the model looks at the result and thinks again
  -> repeat, until the model says "done"
```

Key points:

- The model only produces text. "Changing a file" means it produced a piece of text that says "call the tool that changes files", and Copilot does the real change.
- So **every action goes through a tool call**. That is also why the harness can stop things: it stands at the door of every tool call (see topic 6).

### 1.2 The context window

There is a limit to how much text the model can see at once: the context window. It holds: the rules, your words, the files it read, the results the tools returned, and what it said itself.

- The longer the conversation, the fuller the window. When it is full it gets compressed (summarised), and details are lost.
- In a new session the window is empty: it remembers nothing from before.
- Reading a large file puts the whole text into the window, which takes a lot of room.

What the harness does about it: **important state is written into files** (`TASK.md`, `REQ.md`) and does not rely on the conversation; rules are layered and loaded when needed (topics 2 and 3).

### 1.3 Tools

Reading, searching, writing, running commands, calling a subagent, looking up web pages. The stronger a tool, the more a mistake costs: "run a command" can delete things, "write a file" can change the wrong thing. Which tools there are is in topic 5.

### 1.4 Why an agent goes wrong

| What you see | Why |
| --- | --- |
| It changed what it should not | It reasons about "how to get it done", not about "is it allowed". A rule in a prompt is only a request |
| It forgot along the way | The window was compressed, or the session changed |
| It checks its own work and says it is fine | The same model with the same reasoning has the same blind spots |
| It keeps retrying an action that was refused | It wants to finish the task and does not give up by nature |
| It says "done" without having done it | Models lean towards reporting success. Facts have to be checked |

What the harness does falls into two kinds: **what can be judged right or wrong is stopped by code** (topics 6 and 7); **what cannot be judged is checked from another point of view** (topics 10 and 11).

### 1.5 Choosing a model

A strong model suits thinking and planning; a fast model suits doing and quick answers. The harness cannot change the model in the middle of a session, and cannot set the reasoning effort. The user picks the model in the drop-down; a subagent's model is written in its `.agent.md` (topic 4).

## Hands on

- Open Copilot's chat window and let the agent read a file. Note the "Read ..." the chat shows: that is one tool call.
- Run `harness stats` and look at "tool_calls": how many times tools were called in this session.

## Where to look

- Section 1, the goal, of [docs/05-design.md](../../../../docs/05-design.md).

## Common questions

- **"What is the difference between an agent and a chatbot?"** A chatbot only answers. An agent calls tools by itself and finishes in several steps.
- **"Why not just make the model smarter so it makes no mistakes?"** A stronger model makes fewer mistakes, but never none; in a repository with compliance requirements, one mistake is costly enough.
