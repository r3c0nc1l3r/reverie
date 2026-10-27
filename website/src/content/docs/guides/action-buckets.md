---
title: Action buckets and visual actions
description: Keep large pages navigable and use guarded screenshot coordinates.
---

Large pages must not lose controls to a model's choice limit. The browser keeps every observed action. Models choose from bounded lists and open groups to see more choices.

## Browser observation

The snapshot keeps the existing action order and `e` IDs when there are 250 or fewer real actions. Scroll and wait actions keep their existing IDs. No options change on these pages.

Above 250 real actions, the snapshot assigns IDs before it groups actions. It returns `actions` as the first level and `action_buckets` as a map from bucket IDs to child lists. An `expand` action names its bucket and gives its label and action count. Each native select becomes one group. Its children are the enabled, unselected options. Other groups contain buttons and links, inputs, or other controls. Lists above 200 entries use nested range groups. Every leaf remains reachable. `omitted_actions` is zero.

The marker and node guards cover the complete observation. Group navigation sends no browser input. The executor still resolves node geometry and hit-tests before input.

## Model navigation

The session keeps the root observation and the current bucket path. After each observation, it reapplies the valid part of that path. Back and root actions let a model leave a group. Missing groups return the session to a valid parent.

The pilot uses at most 220 rows. Escalation uses at most 250 rows. If an otherwise compatible flat snapshot exceeds a model's limit, the session adds ordered range groups to its presentation. It keeps the browser's leaf IDs. Jev can choose groups as control operations. Laya asks a separate group question before it chooses a field or option. Its group and option questions use at most 20 choices. Larger questions use internal ranges and keep the lowest confidence along the chosen path. Escalation and the pilot can choose `expand` IDs directly.

`expand REF` opens a group. `act REF --option Wyoming` resolves an exact option label or value within the observed select group. Exactly one option must match. The executor checks the observed option index, label, value, and enabled state before selection. Duplicate values cannot redirect the selection to another option.

## Visual escape hatch

The pilot already receives a screenshot with element marks. It can also choose a point when a custom control has no listed action. The pilot uses coordinates in the supplied image. The controller converts them to viewport CSS pixels. The CLI command `visual-act X Y` accepts viewport CSS pixels directly.

A visual action requires a successful screenshot whose page marker and full DOM signature match before and after capture. The signature includes custom node identities, geometry, and interaction state. The browser rejects a changed page. It hit-tests the point and creates a browser-owned node reference and guard. Execution uses the normal observed-action path. It checks the signature, same node, guard, and original hit point immediately before input. It does not accept a selector or executable code from the caller.

Password, hidden, file, disabled, and inert controls are refused. Visual clicks on labels are also refused because they can activate another field. Use the field itself. Text must be stated in the goal, plan, or notes. Commit actions need explicit intent. Read-only and avoid rules still apply. Password entry keeps its separate `secret` path.

The synthetic [action bucket fixture](https://github.com/r3c0nc1l3r/reverie/blob/main/examples/action-buckets/fixture.html) provides a large form for local exploration.

## Hover menus

Use `hover REF` for an observed clickable menu parent, or `visual-hover X Y` for a point in the latest screenshot. CLI coordinates are viewport CSS pixels. The pilot accepts `hover` and `visual_hover`; visual coordinates use its supplied image dimensions. Hover moves the pointer without clicking or typing. Freshness, hit-test, avoid-list, and control-ownership checks still apply. Protected controls, their ancestors, and labels linked to protected controls are refused.
