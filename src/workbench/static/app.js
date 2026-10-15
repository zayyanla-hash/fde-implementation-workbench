"use strict";

// Imported values are only rendered with textContent or form values. Keep this
// independent of markup parsing: customer input is data, including HTML-like text.
const byId = (id) => document.getElementById(id);
const source = byId("intake-source");
const format = byId("intake-format");
const statusNames = {
  todo: "To do",
  in_progress: "In progress",
  blocked: "Blocked",
  done: "Done",
};
let savedState = { revision: 0, customers: [], tasks: [], activity: [] };
let connected = false;
let busy = false;
let validation = null;
let exampleLoaded = false;
let historyExpanded = false;
const taskFeedback = new Map();
const taskDrafts = new Map();
const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
let motionPaused = false;
let mapCustomerId = "";
const metricValues = new Map();
const activeAnimations = new Set();
const animationTargets = new Map();

// Motion 14.2.0 is vendored locally (MIT). The workflow still runs if it fails to load.
function animateUI(target, values, options = {}) {
  if (!motionEnabled() || !window.Motion?.animate) return null;
  const previous = animationTargets.get(target);
  if (previous) {
    previous.stop();
    activeAnimations.delete(previous);
  }
  const animation = window.Motion.animate(target, values, options);
  activeAnimations.add(animation);
  animationTargets.set(target, animation);
  animation.then(() => {
    activeAnimations.delete(animation);
    if (animationTargets.get(target) === animation)
      animationTargets.delete(target);
  });
  return animation;
}

function inspectStage(stage) {
  const tasks = savedState.tasks.filter(
    (task) => task.customer_id === mapCustomerId,
  );
  const task = tasks.find((item) => item.id === `${mapCustomerId}:${stage}`);
  const stages = {
    scope: [
      "01",
      "Agree on the scope",
      "Start here. Define what success means and who owns it.",
    ],
    "data-access": [
      "02",
      "Provision the sandbox",
      "Runs alongside scope. Confirm access before integration begins.",
    ],
    integration: [
      "03",
      "Connect the integration",
      "Requires both scope and data access to be complete.",
    ],
    acceptance: [
      "04",
      "Validate the outcome",
      "Integration must finish before acceptance can begin.",
    ],
    launch: [
      "05",
      "Approve the launch",
      "Acceptance comes first. Launch is the final handoff.",
    ],
  };
  const [index, title, detail] = stages[stage];
  byId("inspector-index").textContent = index;
  byId("inspector-title").textContent = task?.title || title;
  byId("inspector-detail").textContent = task
    ? `${task.owner} · ${task.blocked_reasons?.length ? task.blocked_reasons.join(" ") : task.status === "done" ? "Completed. This prerequisite is clear." : "Prerequisites clear. Open the task to continue."}`
    : detail;
  animateUI(
    byId("map-inspector").lastElementChild,
    { opacity: [0.4, 1], y: [5, 0] },
    { duration: 0.22, ease: "easeOut" },
  );
}

function initializeMotion() {
  if (motionEnabled()) {
    document.body.classList.add("is-entering");
    window.setTimeout(
      () => document.body.classList.remove("is-entering"),
      1500,
    );
  }
  // Adapted from Vengeance UI's word-mask stagger pattern, without React.
  animateUI(
    ".motion-word",
    { y: ["110%", "0%"] },
    {
      duration: 0.85,
      delay: (index) => 0.08 + index * 0.065,
      ease: [0.22, 1, 0.36, 1],
    },
  );
  animateUI(
    ".route-base",
    { pathLength: [0, 1] },
    { duration: 1.6, delay: 0.3, ease: "easeInOut" },
  );
  animateUI(
    ".node-symbol",
    { opacity: [0, 1], scale: [0.7, 1] },
    {
      type: "spring",
      duration: 0.65,
      bounce: 0.25,
      delay: (index) => 0.5 + index * 0.09,
    },
  );
  window.Motion?.inView?.(
    ".plan-heading, .history-panel>.section-heading",
    (node) => {
      animateUI(
        node,
        { opacity: [0.4, 1], y: [16, 0] },
        { duration: 0.6, ease: [0.22, 1, 0.36, 1] },
      );
    },
  );
  for (const node of document.querySelectorAll(".map-node")) {
    const symbol = node.querySelector(".node-symbol");
    node.setAttribute("aria-describedby", "map-inspector");
    const enter = () => {
      inspectStage(node.dataset.stage);
      animateUI(
        symbol,
        { scale: 1.13 },
        { type: "spring", stiffness: 380, damping: 20 },
      );
    };
    const leave = () =>
      animateUI(
        symbol,
        { scale: 1 },
        { type: "spring", stiffness: 260, damping: 18 },
      );
    node.addEventListener("pointerenter", enter);
    node.addEventListener("focus", enter);
    node.addEventListener("pointerleave", leave);
    node.addEventListener("blur", leave);
  }
}

function motionEnabled() {
  return !motionPaused && !motionPreference.matches;
}
function updateMotion() {
  document.body.classList.toggle("motion-paused", !motionEnabled());
  const control = byId("motion-toggle");
  control.textContent = motionPreference.matches
    ? "Motion reduced"
    : motionPaused
      ? "Motion off ▷"
      : "Motion on Ⅱ";
  control.setAttribute("aria-pressed", String(motionEnabled()));
  control.disabled = motionPreference.matches;
  control.title = motionPreference.matches
    ? "Follows your device’s reduced motion preference."
    : "Turn interface animation on or off.";
  if (!motionEnabled()) {
    document.body.classList.remove("is-entering");
    for (const animation of activeAnimations) animation.complete();
    activeAnimations.clear();
    animationTargets.clear();
  }
}

function setMetric(id, value) {
  const node = byId(id);
  const previous = metricValues.get(id);
  node.textContent = String(value);
  metricValues.set(id, value);
  if (previous !== undefined && previous !== value && motionEnabled()) {
    animateUI(
      node,
      { opacity: [0.3, 1], y: [8, 0] },
      { type: "spring", duration: 0.5, bounce: 0.18 },
    );
  }
}

function renderMap() {
  const select = byId("map-customer");
  if (
    !savedState.customers.some(
      (customer) => customer.customer_id === mapCustomerId,
    )
  )
    mapCustomerId = savedState.customers[0]?.customer_id || "";
  select.replaceChildren();
  for (const customer of savedState.customers) {
    const option = element("option", "", customer.customer_name);
    option.value = customer.customer_id;
    select.append(option);
  }
  if (!mapCustomerId)
    select.append(element("option", "", "No saved customers yet"));
  else select.value = mapCustomerId;
  select.disabled = !mapCustomerId;
  byId("map-mode").textContent = mapCustomerId
    ? "Saved task status"
    : "Workflow preview";
  const tasks = savedState.tasks.filter(
    (task) => task.customer_id === mapCustomerId,
  );
  const preview = {
    scope: "Define the work",
    "data-access": "Clear the way",
    integration: "Connect the pieces",
    acceptance: "Prove it works",
    launch: "Make it real",
  };
  for (const node of document.querySelectorAll(".map-node")) {
    const stage = node.dataset.stage;
    const task = tasks.find((item) => item.id === `${mapCustomerId}:${stage}`);
    const state = task
      ? task.status === "done" || task.status === "in_progress"
        ? task.status
        : task.blocked_reasons?.length
          ? "waiting"
          : task.status
      : "preview";
    node.dataset.state = state;
    const description = task
      ? state === "waiting"
        ? "Waiting"
        : statusNames[state]
      : preview[stage];
    node.querySelector("small").textContent = description;
    node.href = task ? `#${encodeURIComponent(`task-${task.id}`)}` : "#intake";
    node.setAttribute(
      "aria-label",
      task
        ? `${task.title}: ${description}. Go to task.`
        : `${node.querySelector("strong").textContent}: ${description}. Start with intake.`,
    );
    node.onclick = task
      ? (event) => {
          event.preventDefault();
          const card = byId(`task-${task.id}`);
          if (!card) return;
          card.focus({ preventScroll: true });
          card.scrollIntoView({
            behavior: motionEnabled() ? "smooth" : "auto",
            block: "center",
          });
        }
      : null;
  }
  const done = tasks.filter((task) => task.status === "done").length;
  const waiting = tasks.filter((task) => task.blocked_reasons?.length).length;
  inspectStage("scope");
  byId("map-caption").textContent = tasks.length
    ? `${done} of ${tasks.length} complete · ${waiting} waiting. Select a stage to inspect.`
    : "Two foundations. One path to launch.";
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}

function clear(node) {
  node.replaceChildren();
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
    });
  } catch (_) {
    throw new Error(
      "The local server could not be reached. Keep the server running, then try again.",
    );
  }
  let data;
  try {
    data = await response.json();
  } catch (_) {
    throw new Error(
      "The local server returned an unreadable response. Try refreshing the saved plan.",
    );
  }
  if (!response.ok) {
    const error = new Error(
      data.error || `The request could not be saved (HTTP ${response.status}).`,
    );
    error.issues = data.issues || [];
    error.status = response.status;
    throw error;
  }
  return data;
}

function pageFeedback(message, kind = "info") {
  const box = byId("page-feedback");
  box.textContent = message;
  box.className = `feedback page-feedback ${kind}`;
  box.hidden = !message;
}

function setStorage(ok, detail) {
  connected = ok;
  byId("storage-indicator").className =
    `storage-indicator ${ok ? "connected" : "failed"}`;
  byId("storage-label").textContent = ok
    ? "Saved on this computer"
    : "Local storage unavailable";
  byId("storage-detail").textContent = detail;
  updateControls();
}

function validCurrentSource() {
  return (
    validation &&
    validation.text === source.value &&
    validation.format === format.value &&
    !validation.result.issues.some((issue) => issue.severity !== "warning")
  );
}

function updateControls() {
  byId("load-example").disabled = busy;
  byId("validate-intake").disabled = busy || !source.value.trim();
  byId("create-plan").disabled = busy || !connected || !validCurrentSource();
  byId("refresh-plan").disabled = busy;
  document.querySelectorAll(".task-save").forEach((button) => {
    button.disabled = busy || !connected;
  });
  const hasTasks = savedState.tasks.length > 0 && connected;
  document.querySelectorAll(".export-link").forEach((link) => {
    link.setAttribute("aria-disabled", String(!hasTasks));
  });
}

function setBusy(value, control, label) {
  busy = value;
  byId("intake").setAttribute("aria-busy", String(value));
  if (control) control.textContent = label;
  updateControls();
}

function invalidateSource() {
  const hadValidation = Boolean(validation);
  validation = null;
  byId("intake-action-help").textContent = "Validate before creating a plan.";
  if (hadValidation) {
    showValidation(
      null,
      "Source changed. Validate again to check these edits.",
    );
  }
  updateControls();
}

function showValidation(result, summary) {
  const badge = byId("validation-badge");
  const issues = byId("validation-issues");
  clear(issues);
  byId("example-hint").hidden = true;
  byId("validation-empty").hidden = false;
  if (!result) {
    badge.textContent = source.value.trim()
      ? "Ready to validate"
      : "Waiting for source";
    badge.className = "pill pill-neutral";
    byId("validation-summary").textContent =
      summary ||
      "Load the example to find a missing technical owner before any work is created.";
    return;
  }
  const errors = result.issues.filter((issue) => issue.severity !== "warning");
  const warnings = result.issues.filter(
    (issue) => issue.severity === "warning",
  );
  const recordCount = result.records.length;
  const duplicateCount = result.duplicates || 0;
  badge.className = `pill ${errors.length ? "pill-error" : "pill-success"}`;
  badge.textContent = errors.length
    ? `${errors.length} ${errors.length === 1 ? "issue" : "issues"} to resolve`
    : "Validation passed";
  byId("validation-summary").textContent =
    summary ||
    (errors.length
      ? "The intake needs a correction. No customers or tasks have been saved. Edit the source and validate again."
      : `${recordCount} ${recordCount === 1 ? "customer record" : "customer records"} checked. ${duplicateCount ? `${duplicateCount} ${duplicateCount === 1 ? "duplicate" : "duplicates"} will be skipped without creating extra tasks. ` : ""}Ready to create the plan.`);
  byId("validation-empty").hidden = result.issues.length > 0;
  for (const issue of result.issues) {
    const warning = issue.severity === "warning";
    const card = element("div", `issue-card${warning ? " issue-warning" : ""}`);
    const location = element("div", "issue-location");
    location.append(
      element("span", "", issue.row ? `Row ${issue.row}` : "Source"),
      element("code", "", issue.field || "document"),
    );
    card.append(
      location,
      element("p", "issue-message", issue.message),
      element(
        "p",
        "issue-code",
        `${warning ? "Warning" : "Error"} · ${issue.code || "validation"}`,
      ),
    );
    issues.append(card);
  }
  if (
    exampleLoaded &&
    errors.some((issue) => issue.field === "technical_owner")
  )
    byId("example-hint").hidden = false;
  byId("intake-action-help").textContent = errors.length
    ? "Resolve issues, then validate again."
    : warnings.length
      ? "Warnings reviewed. Ready to create."
      : "Validation passed. Ready to create.";
}

async function loadSavedPlan({ announce = false } = {}) {
  setBusy(true);
  try {
    savedState = await request("/api/onboarding");
    renderState();
    setStorage(
      true,
      `Revision ${savedState.revision} · persists across reloads`,
    );
    if (announce)
      pageFeedback(
        `Saved plan refreshed. The intake source is preserved.${taskDrafts.size ? ` ${taskDrafts.size} unsaved task ${taskDrafts.size === 1 ? "draft is" : "drafts are"} preserved below; review before saving.` : ""}`,
        "success",
      );
  } catch (error) {
    setStorage(false, "Refresh to reconnect to the local server.");
    pageFeedback(error.message, "error");
  } finally {
    setBusy(false);
  }
}

async function validateIntake() {
  const text = source.value;
  const selectedFormat = format.value;
  const button = byId("validate-intake");
  setBusy(true, button, "Validating…");
  try {
    const result = await request("/api/onboarding/preview", {
      method: "POST",
      body: JSON.stringify({ text, format: selectedFormat }),
    });
    if (text !== source.value || selectedFormat !== format.value) {
      validation = null;
      showValidation(
        null,
        "The source changed during validation. Validate again to check the latest version.",
      );
      return;
    }
    validation = { text, format: selectedFormat, result };
    showValidation(result);
    pageFeedback("");
  } catch (error) {
    validation = null;
    if ((error.issues || []).length)
      showValidation(
        { records: [], duplicates: 0, issues: error.issues },
        error.message,
      );
    else pageFeedback(error.message, "error");
  } finally {
    setBusy(false, button, "Validate intake");
  }
}

async function createPlan() {
  if (!validCurrentSource()) return;
  const button = byId("create-plan");
  setBusy(true, button, "Creating plan…");
  try {
    const oldTaskCount = savedState.tasks.length;
    savedState = await request("/api/onboarding/import", {
      method: "POST",
      body: JSON.stringify({
        text: source.value,
        format: format.value,
        revision: savedState.revision,
      }),
    });
    renderState();
    setStorage(
      true,
      `Revision ${savedState.revision} · persists across reloads`,
    );
    const added = savedState.tasks.length - oldTaskCount;
    const message =
      added > 0
        ? `Plan saved. ${added} tasks created with owners, dependencies and blockers.`
        : "This intake is already saved. No duplicate customers or tasks were created.";
    pageFeedback(message, "success");
    byId("validation-badge").textContent = "Plan saved";
    byId("validation-summary").textContent = message;
    byId("intake-action-help").textContent =
      "Saved. Review the implementation plan below.";
    byId("plan").scrollIntoView({
      behavior: motionEnabled() ? "smooth" : "auto",
      block: "start",
    });
  } catch (error) {
    if ((error.issues || []).length)
      showValidation(
        { records: [], duplicates: 0, issues: error.issues },
        error.message,
      );
    pageFeedback(
      `${error.message}${error.status === 409 ? " Refresh the saved plan to load the latest revision before trying again. Your intake source is preserved." : " Your intake source is preserved for correction."}`,
      "error",
    );
  } finally {
    setBusy(false, button, "Create plan →");
  }
}

function labeledControl(
  form,
  type,
  id,
  labelText,
  value,
  accessibleName,
  className = "",
) {
  const wrapper = element("div", className);
  const label = element("label", "", labelText);
  label.htmlFor = id;
  const control = element(type);
  control.id = id;
  control.name = id;
  control.setAttribute("aria-label", accessibleName);
  if (type === "input") control.type = "text";
  if (value !== undefined) control.value = value;
  wrapper.append(label, control);
  form.append(wrapper);
  return control;
}

function taskCard(task, index, taskLookup) {
  const card = element("article", "task-card");
  card.id = `task-${task.id}`;
  card.tabIndex = -1;
  card.dataset.status = task.status;
  const headingId = `task-heading-${index}`;
  card.setAttribute("aria-labelledby", headingId);
  const top = element("div", "task-topline");
  const statusClass =
    task.status === "done"
      ? "pill-success"
      : task.status === "blocked"
        ? "pill-warning"
        : task.status === "in_progress"
          ? "pill-progress"
          : "pill-neutral";
  top.append(
    element("span", "task-index", `TASK ${String(index + 1).padStart(2, "0")}`),
    element(
      "span",
      `pill ${statusClass}`,
      statusNames[task.status] || task.status,
    ),
  );
  const title = element("h4", "", task.title);
  title.id = headingId;
  const owner = element("p", "task-owner");
  owner.append(element("span", "", "OWNER"), element("span", "", task.owner));
  card.append(top, title, owner);

  const dependencies = element("div", "dependency-block");
  dependencies.append(element("p", "task-label", "Dependencies"));
  if (task.depends_on.length) {
    const list = element("ul", "dependency-list");
    for (const id of task.depends_on) {
      const dependency = taskLookup.get(id);
      const done = dependency && dependency.status === "done";
      list.append(
        element(
          "li",
          done ? "completed" : "",
          `${done ? "✓ " : "○ "}${dependency ? dependency.title : id} · ${dependency ? statusNames[dependency.status] : "Unavailable"}`,
        ),
      );
    }
    dependencies.append(list);
  } else
    dependencies.append(element("p", "no-dependencies", "No prerequisites"));
  card.append(dependencies);

  const reasons = Array.isArray(task.blocked_reasons)
    ? task.blocked_reasons
    : [];
  if (reasons.length) {
    const box = element("div", "blocker-box");
    box.append(
      element("p", "task-label", "Waiting on · cannot start or complete"),
    );
    const list = element("ul", "blocker-list");
    reasons.forEach((reason) => list.append(element("li", "", reason)));
    box.append(list);
    card.append(box);
  } else
    card.append(
      element(
        "p",
        "ready-note",
        task.status === "done"
          ? "✓ Completed"
          : task.status === "in_progress"
            ? "✓ Prerequisites cleared · work in progress"
            : "✓ Ready to start",
      ),
    );
  if (task.acceptance_criteria) {
    const acceptance = element("p", "acceptance-block");
    acceptance.append(
      element("strong", "", "Acceptance criteria"),
      document.createTextNode(task.acceptance_criteria),
    );
    card.append(acceptance);
  }

  const details = element("details", "task-edit");
  const summary = element("summary", "", "Edit task");
  const taskLabel = `${task.title} (${task.customer_id})`;
  summary.setAttribute("aria-label", `Edit task: ${taskLabel}`);
  const draft = taskDrafts.get(task.id) || {};
  const editable = { ...task, ...draft };
  const form = element("form");
  const fields = element("div", "task-fields");
  const unique = `task-edit-${index}`;
  const titleInput = labeledControl(
    fields,
    "input",
    `${unique}-title`,
    "Task title",
    editable.title,
    `Title for ${taskLabel}`,
    "task-field-full",
  );
  const ownerInput = labeledControl(
    fields,
    "input",
    `${unique}-owner`,
    "Owner email",
    editable.owner,
    `Owner for ${taskLabel}`,
  );
  ownerInput.autocomplete = "off";
  const statusInput = labeledControl(
    fields,
    "select",
    `${unique}-status`,
    "Status",
    undefined,
    `Status for ${taskLabel}`,
  );
  for (const [value, name] of Object.entries(statusNames)) {
    const option = element("option", "", name);
    option.value = value;
    statusInput.append(option);
  }
  statusInput.value = editable.status;
  const blockerInput = labeledControl(
    fields,
    "textarea",
    `${unique}-blocker`,
    "Blocker / reason for waiting",
    editable.blocker || "",
    `Blocker for ${taskLabel}`,
    "task-field-full",
  );
  blockerInput.rows = 2;
  const help = element(
    "p",
    "field-help",
    "To complete a task, first move it to In progress, clear its blocker, and finish its prerequisites. Generated dependencies stay fixed.",
  );
  help.id = `${unique}-help`;
  statusInput.setAttribute("aria-describedby", help.id);
  blockerInput.setAttribute("aria-describedby", help.id);
  const saveRow = element("div", "task-save-row");
  const save = element(
    "button",
    "button button-primary task-save",
    "Save changes",
  );
  save.type = "submit";
  save.id = `${unique}-save`;
  save.setAttribute("aria-label", `Save changes for ${taskLabel}`);
  const discard = element("button", "button button-secondary", "Discard draft");
  discard.type = "button";
  discard.hidden = !taskDrafts.has(task.id);
  discard.setAttribute("aria-label", `Discard unsaved draft for ${taskLabel}`);
  const feedback = element("p", "task-feedback");
  feedback.setAttribute("role", "status");
  feedback.setAttribute("aria-live", "polite");
  const priorFeedback = taskFeedback.get(task.id);
  if (priorFeedback) {
    feedback.textContent = priorFeedback.message;
    feedback.classList.toggle("success", priorFeedback.success);
    details.open = true;
  }
  if (taskDrafts.has(task.id)) {
    details.open = true;
    summary.textContent = "Edit task · unsaved draft";
    if (!priorFeedback)
      feedback.textContent = "Unsaved draft preserved. Review, then save.";
  }
  function collectChanges() {
    const values = {
      title: titleInput.value,
      owner: ownerInput.value,
      status: statusInput.value,
      blocker: blockerInput.value,
    };
    return Object.fromEntries(
      Object.entries(values).filter(
        ([key, value]) => value !== (task[key] || ""),
      ),
    );
  }
  function rememberDraft() {
    const changes = collectChanges();
    const hasChanges = Object.keys(changes).length > 0;
    if (hasChanges) taskDrafts.set(task.id, changes);
    else taskDrafts.delete(task.id);
    taskFeedback.delete(task.id);
    summary.textContent = hasChanges
      ? "Edit task · unsaved draft"
      : "Edit task";
    discard.hidden = !hasChanges;
    feedback.classList.remove("success");
    feedback.textContent = hasChanges
      ? "Unsaved draft. Save to persist across reloads."
      : "";
  }
  for (const control of [titleInput, ownerInput, statusInput, blockerInput])
    control.addEventListener("input", rememberDraft);
  statusInput.addEventListener("change", rememberDraft);
  discard.addEventListener("click", () => {
    titleInput.value = task.title;
    ownerInput.value = task.owner;
    statusInput.value = task.status;
    blockerInput.value = task.blocker || "";
    rememberDraft();
  });
  saveRow.append(save, discard, feedback);
  form.append(fields, help, saveRow);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || !connected) return;
    const changes = collectChanges();
    if (!Object.keys(changes).length) {
      feedback.textContent = "No changes to save.";
      feedback.classList.add("success");
      return;
    }
    setBusy(true);
    save.textContent = "Saving…";
    for (const control of [
      titleInput,
      ownerInput,
      statusInput,
      blockerInput,
      discard,
    ])
      control.disabled = true;
    feedback.textContent = "";
    feedback.classList.remove("success");
    try {
      savedState = await request(
        `/api/onboarding/tasks/${encodeURIComponent(task.id)}`,
        {
          method: "PATCH",
          body: JSON.stringify({ revision: savedState.revision, changes }),
        },
      );
      taskDrafts.delete(task.id);
      taskFeedback.delete(task.id);
      taskFeedback.set(task.id, {
        success: true,
        message: "Saved to the local plan.",
      });
      renderState();
      setStorage(
        true,
        `Revision ${savedState.revision} · persists across reloads`,
      );
      pageFeedback("");
    } catch (error) {
      const issueText = (error.issues || [])
        .map((issue) => `${issue.field || "Task"}: ${issue.message}`)
        .join(" ");
      feedback.textContent = `${error.message}${issueText ? ` ${issueText}` : ""}${error.status === 409 ? " Resolve prerequisites or refresh if the saved plan changed. Your edits remain here." : " Your edits remain here for correction."}`;
      taskFeedback.set(task.id, {
        success: false,
        message: feedback.textContent,
      });
    } finally {
      save.textContent = "Save changes";
      for (const control of [
        titleInput,
        ownerInput,
        statusInput,
        blockerInput,
        discard,
      ])
        control.disabled = false;
      setBusy(false);
      byId(`${unique}-save`)?.focus({ preventScroll: true });
    }
  });
  details.append(summary, form);
  card.append(details);
  return card;
}

function renderPlan() {
  const target = byId("plan-content");
  clear(target);
  const tasks = savedState.tasks;
  setMetric("customer-count", savedState.customers.length);
  setMetric("task-count", tasks.length);
  setMetric(
    "complete-count",
    tasks.filter((task) => task.status === "done").length,
  );
  setMetric(
    "waiting-count",
    tasks.filter(
      (task) =>
        Array.isArray(task.blocked_reasons) && task.blocked_reasons.length,
    ).length,
  );
  if (!tasks.length) {
    const empty = element("div", "empty-state");
    empty.append(
      element("span", "empty-icon", "≡"),
      element("h3", "", "Your implementation plan will appear here."),
      element(
        "p",
        "",
        "Load the example, resolve the missing owner, and create a five-step onboarding checklist.",
      ),
    );
    const link = element("a", "text-link", "Start with customer intake ↑");
    link.href = "#intake";
    empty.append(link);
    target.append(empty);
    return;
  }
  const taskLookup = new Map(tasks.map((task) => [task.id, task]));
  let taskIndex = 0;
  for (const customer of savedState.customers) {
    const customerTasks = tasks.filter(
      (task) => task.customer_id === customer.customer_id,
    );
    const group = element("section", "customer-group");
    const header = element("div", "customer-heading");
    const avatar = element(
      "span",
      "customer-avatar",
      (customer.customer_name || "C").slice(0, 1).toUpperCase(),
    );
    avatar.setAttribute("aria-hidden", "true");
    const identity = element("div");
    const title = element("div", "customer-title");
    title.append(
      element("h3", "", customer.customer_name),
      element("code", "", customer.customer_id),
    );
    identity.append(
      title,
      element("p", "customer-integration", customer.integration),
    );
    header.append(
      avatar,
      identity,
      element(
        "p",
        "customer-progress",
        `${customerTasks.filter((task) => task.status === "done").length} / ${customerTasks.length} completed`,
      ),
    );
    const grid = element("div", "task-grid");
    customerTasks.forEach((task) =>
      grid.append(taskCard(task, taskIndex++, taskLookup)),
    );
    group.append(header, grid);
    target.append(group);
  }
}

function renderActivity() {
  const events = savedState.activity || [];
  const list = byId("activity-list");
  clear(list);
  byId("activity-count").textContent =
    `${events.length} ${events.length === 1 ? "event" : "events"}`;
  if (!events.length)
    list.append(
      element(
        "li",
        "activity-empty",
        "Imports and saved task changes will be recorded here with their timestamps.",
      ),
    );
  const ordered = [...events].reverse();
  const visible = historyExpanded ? ordered : ordered.slice(0, 8);
  for (const event of visible) {
    const item = element("li");
    const time = element("time");
    const date = new Date(event.at);
    time.dateTime = event.at;
    time.textContent = Number.isNaN(date.getTime())
      ? event.at
      : new Intl.DateTimeFormat(undefined, {
          month: "short",
          day: "numeric",
          hour: "numeric",
          minute: "2-digit",
          second: "2-digit",
          timeZoneName: "short",
        }).format(date);
    const content = element("div");
    const action = String(event.action || "Change saved").replaceAll("_", " ");
    content.append(
      element(
        "p",
        "activity-action",
        action.charAt(0).toUpperCase() + action.slice(1),
      ),
      element("p", "activity-details", event.details || ""),
    );
    item.append(time, content);
    list.append(item);
  }
  const showAll = byId("show-all-activity");
  showAll.hidden = historyExpanded || events.length <= 8;
  showAll.textContent = `Show all ${events.length} events`;
}

function renderState() {
  const focusedId = document.activeElement?.id;
  renderPlan();
  renderActivity();
  renderMap();
  updateControls();
  // Rebuilding the task list must not strand keyboard focus after a save.
  if (focusedId && byId(focusedId))
    byId(focusedId).focus({ preventScroll: true });
}

source.addEventListener("input", invalidateSource);
window.addEventListener("beforeunload", (event) => {
  if (taskDrafts.size) {
    event.preventDefault();
    event.returnValue = "";
  }
});
format.addEventListener("change", invalidateSource);
byId("validate-intake").addEventListener("click", validateIntake);
byId("create-plan").addEventListener("click", createPlan);
byId("refresh-plan").addEventListener("click", () =>
  loadSavedPlan({ announce: true }),
);
byId("show-all-activity").addEventListener("click", () => {
  historyExpanded = true;
  renderActivity();
});
document.querySelectorAll(".export-link").forEach((link) =>
  link.addEventListener("click", (event) => {
    if (link.getAttribute("aria-disabled") === "true") event.preventDefault();
  }),
);
byId("load-example").addEventListener("click", async () => {
  const button = byId("load-example");
  setBusy(true, button, "Loading…");
  try {
    const example = await request(
      `/api/onboarding/example?format=${encodeURIComponent(format.value)}&invalid=1`,
    );
    source.value = example.text;
    format.value = example.format;
    exampleLoaded = true;
    validation = null;
    byId("intake-file").value = "";
    byId("file-feedback").textContent = "";
    showValidation(
      null,
      "Example loaded: a synthetic AI software onboarding with one missing owner. Validate the intake to see the exact issue.",
    );
    byId("intake-action-help").textContent =
      "Example loaded. Validate to check the handoff.";
    pageFeedback("");
  } catch (error) {
    pageFeedback(error.message, "error");
  } finally {
    setBusy(false, button, "Load example");
  }
});
byId("intake-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  if (file.size > 1024 * 1024) {
    byId("file-feedback").textContent =
      "Choose a file smaller than 1 MB for this demo.";
    return;
  }
  try {
    const text = await file.text();
    source.value = text;
    if (/\.json$/i.test(file.name)) format.value = "json";
    if (/\.csv$/i.test(file.name)) format.value = "csv";
    exampleLoaded = false;
    invalidateSource();
    showValidation(
      null,
      "File loaded into the editable source. Validate it before creating a plan.",
    );
    byId("file-feedback").textContent =
      `${file.name} loaded. Source remains editable.`;
  } catch (_) {
    byId("file-feedback").textContent =
      "The file could not be read. Paste the source directly or choose another file.";
  }
});

byId("motion-toggle").addEventListener("click", () => {
  motionPaused = !motionPaused;
  updateMotion();
});
motionPreference.addEventListener("change", updateMotion);
byId("map-customer").addEventListener("change", (event) => {
  mapCustomerId = event.target.value;
  renderMap();
});
updateMotion();
initializeMotion();
loadSavedPlan();
