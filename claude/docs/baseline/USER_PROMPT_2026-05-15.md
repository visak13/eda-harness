# Baseline User Prompt — 2026-05-15

**Source:** `C:\Projects\Learning\evolving-deep-agent\instructions.txt` (the old repo, where the user typed this in)
**Captured:** 2026-05-15 (verbatim, do not edit; if user updates, append a new dated file)
**Status:** LOAD-BEARING. North-star intent for the rewrite. Re-read at the start of every session.

---

## Verbatim prompt

This repo (evolving-deep-agent) was designed to overcome the challenges of traditional llms and develop capabilities beyond claude's own. This was not an attempt to replace claude or abuse the system. However, the implementation failed. And we must learn from this and develop a simpler system that works.

### What went wrong:
- The system kept developing across multiple claude sessions with compacted sessions.
- The system kept working on long plans but failed to retrieve context across the plans.
- The system didnt store contextual information in plans or any other documentation.
- The documentation was done at the end of the development which broke the process.
- The system kept making assumptions throughout the plan.
- The system didn't regularly cross-validate.
- There is no saying which documents are correct and which are false.
- The system is complex for a llm to follow (too many protocols to follow with all responsibility laid on the shoulders of the llm)
- The system is a llm (which means its no system at all)
- The llm doesnt have a context window large enough to follow the neuron pattern, agentic-plan pattern, worker pattern
- Knowledge graph is polluted with irrelevant noise
- machine learning tools are trained upon these patterns

### What worked (at least partially):
- The planner json was able to save partial context for llm to continue
- The recipe json was supposed to save snapshot of llm's progress and help drive the llm
- The llm kept acting to develop a workaround for failing protocols
- The schema validators served as pinch points that avoided errors in state but also made it difficult for llm to operate
- Anti-patterns help detect failures before-hand
- The phased prompts help the llm to build context gradually and actually build upon the network of tools by setting up a monitor first and then follow the recipe and plan but it still failed to dynamically act. The dynamic part being: not able to reactivate neurons when needed; neurons, planner and workers not using the event system to openly communicate and solve the problems as a team.

### What needs to happen:
- mcp tools library need to take the brunt of the work
- user problem and llm solution/progress context needs to be preserved so that work can actually migrate across sessions without loss
- solution needs to be an agent harness that works towards solving the problem rather than solving the system
- agentic-plan was working end-to-end with an abstract factory of plans (software, movie, robotic, etc), multiple shapes of plans making it possible to context. this structure needs to serve as baseline upon which other complex commands build upon
- commands act as activators and help guide the llm based on actions/events
- single event broker that is reliable and only transmits events
- rely on the event driven system to inter-communicate with special commands or mcp tools
- the pool is a working server that spawns claude shells (use this pattern for activation + work assignment)
- the hooks like pii were supposed to be a poc but they crept into the system by adding hinderance
- the knowledge graph server has improved in fault tolerance. the system should be reclaimed and reused if possible without the previous knowledge (or vector entries)
- the ollama docker image is already working and shouldnt be changed
- a proxy was developed for reliably communicating between the knowledge graph and ollama. should be used as it adds fault tolerance
- all these microservices should live in their own repo to avoid issues where updating one service required to shut others due to shared venv collisions
- the neuron architecture needs to adapt to the agentic-plan style architecture of dependency injection and inversion of control
- the neuron state should adapt to work like a true event-driven system and preseve states by version to help with diagnosis
- to reduce the complexity of the system, the neuron will work as a simple phased approach with flexible shapes and approaches of how to build neural networks. the first steps will be to arm the monitor and set a loop command of 30 minutes interval (subject to revision based on my feedback). then in phase b to create the recipe shape by consulting other neurons (simplified neurons -> we will simplify the aggregator neuron to take all tasks up in a single shell instead of branching workers and call it ocak neuron). other neurons will be called at intervals using loop command to drift check and pattern observe. phase d to drive a plan or plans. phase e checks if phases b to d need to repeat and acts. finally the last phase will close out the goal. this system will act as dependency injection and not as burden of tasks for driving neuron.
- the loop that we create in phase b is to remind the user neuron to just drive the recipe from start to finish and consult other neurons if needed
- we remove python driven neuron like idle-worker reaper as it adds no value.
- proper logging across all mcp tools and microservices so that we can visualize the data flow.
- in the end, I visualize a proper server that scales and not a patchwork of spaghetti scripts that achieve a solution. the server needs to be production grade. each modification to the system does an impact analysis and there are proper unit test cases if needed.
- re-write the python microservices but keep them aligned to the behaviors. refactoring them will be a monumental task.
- dont use mono-repo. each micro-service gets its own repo, separate from the claude repo. claude repo will only maintain the mcp tools, commands, plans, recipe and states.

### Operating instructions (before acting):
- use C:\Projects\Learning\eda-base as your project base
- create a docs folder inside the claude repo and store my prompt as the baseline so that it survives session compacts
- use a document based system to track your progress and keep it updated
- set a loop to remind you of this

### Closing:
i will regualarly compact or clear this session. So, add proper context around the docs. maintain a guideline in your docs that will help you reliably work without losing context. do thorough analysis of the current repo and micro-services to understand it and why it failed. check the plans and recipes to understand what kind of work the previous system did and what went wrong. dont assume anything. i am here to discuss and this is a bi-directional channel. you use this channel effectively and regularly. you discuss before acting.
