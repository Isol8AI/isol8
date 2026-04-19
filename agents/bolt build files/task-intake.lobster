pipeline: task-intake
description: Convert founder's plain-English request into a scoped task spec, gate on sensitive paths, get confirmation before acting.
trigger: message

steps:

  - id: parse-intent
    type: llm-task
    prompt: |
      The founder sent this request: "{{input}}"
      
      Convert it into a structured task spec with:
      1. what_to_do: one sentence, plain English
      2. files_likely_touched: list any files or folders this probably involves
      3. success_criteria: how we know it's done
      4. scope: "low" (boilerplate/simple), "medium" (feature), "high" (architecture decision)
      5. can_bolt_do_it: true if low/medium scope with no architecture decisions, false if high
      
      Respond in JSON only.
    output: task_spec

  - id: sensitive-gate
    type: script
    run: node scripts/bolt-sensitive-gate.js "{{task_spec.files_likely_touched}}"
    output: gate_result
    on_blocked: |
      🚫 I can't handle this one — it involves {{gate_result.results[0].reason}}.
      This needs a developer. Want me to create a Linear issue for it instead?
    exit_if_blocked: true

  - id: scope-gate
    type: conditional
    condition: "{{task_spec.can_bolt_do_it}} === false"
    if_true:
      message: |
        This one is outside what I can handle safely on my own — it involves architecture decisions that need human judgment.
        
        Here's what I understood: {{task_spec.what_to_do}}
        
        Want me to create a Linear issue so your developer can pick it up?
      exit: true

  - id: confirm-with-founder
    type: approval
    message: |
      Here's what I'm planning to do:
      
      **{{task_spec.what_to_do}}**
      
      Files I'll likely touch: {{task_spec.files_likely_touched}}
      Done when: {{task_spec.success_criteria}}
      
      Should I go ahead?
    options: ["Yes, go ahead", "No, cancel", "Change something"]
    output: founder_confirmation

  - id: execute-task
    type: llm-task
    condition: "{{founder_confirmation}} === 'Yes, go ahead'"
    prompt: |
      Execute this task: {{task_spec.what_to_do}}
      Files to touch: {{task_spec.files_likely_touched}}
      Success criteria: {{task_spec.success_criteria}}
      
      Produce the code or changes needed. Be minimal — only change what's needed.
    output: task_output

  - id: report-completion
    type: message
    channel: "{{user.slack_channel}}"
    content: |
      ✅ Done. {{task_spec.what_to_do}}
      
      {{task_output.summary}}
      
      Want me to open a PR for review?
