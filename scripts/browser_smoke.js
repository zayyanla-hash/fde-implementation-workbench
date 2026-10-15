// Optional real-browser regression test. Requires an existing Ego Browser CLI.
// Run against a fresh WORKBENCH_DB; see docs/ONBOARDING_DEMO.md.
const assert = (await import("node:assert/strict")).default;
const fs = await import("node:fs/promises");
const path = await import("node:path");
// Ego's embedded runtime does not inherit the launching shell's cwd/env.
// A runner may set globalThis.workbenchQA before this source is evaluated.
const config = globalThis.workbenchQA || {};
const base = config.url || "http://127.0.0.1:8765";
const output = path.resolve(config.output || "/tmp/workbench-browser-proof");
await fs.mkdir(output, { recursive: true });
const task = await taskSpace(config.space || "Workbench browser regression");
const page = task.page("p1");
const results = [];
const record = (name) => { results.push({ name, passed: true }); console.log(`PASS ${name}`); };
console.log({ taskSpaceId: task.spaceId, base, output });
await page.goto(base + "/");
await page.waitForFunction(() => document.getElementById("storage-label").textContent === "Saved on this computer");
await page.cdp("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
assert.match(await page.title(), /Implementation Workbench/);
assert.equal(await page.url(), base + "/");
assert.equal(await page.evaluate(() => document.querySelectorAll(".task-card").length), 0, "Use a fresh WORKBENCH_DB for this test");
await page.evaluate(() => {
  window.__qaErrors = [];
  window.addEventListener("error", (event) => window.__qaErrors.push(event.message));
  window.addEventListener("unhandledrejection", (event) => window.__qaErrors.push(String(event.reason)));
});
record("meaningful empty screen and local storage connection");
assert.equal(await page.evaluate(() => {
  const source = document.getElementById("intake-source");
  return source.getBoundingClientRect().width >= source.parentElement.clientWidth - 55;
}), true, "Intake textarea must use its panel width");
record("intake source uses the available panel width");
console.log(await page.snapshot());
await page.click("#load-example");
await page.waitForFunction(() => document.getElementById("intake-source").value.includes("harbor-demo"));
await page.click("#validate-intake");
await page.waitForFunction(() => document.querySelector(".issue-card code")?.textContent === "technical_owner");
assert.equal(await page.evaluate(() => document.getElementById("create-plan").disabled), true);
await page.screenshot({ path: path.join(output, "workbench-validation-desktop.png") });
record("CSV missing technical owner is identified by row and field before import");
const corrected = await page.evaluate(() => document.getElementById("intake-source").value.replace(",,", ",technical-owner@example.test,"));
await page.fill("#intake-source", corrected);
await page.click("#validate-intake");
await page.waitForFunction(() => !document.getElementById("create-plan").disabled);
await page.click("#create-plan");
await page.waitForFunction(() => document.querySelectorAll(".task-card").length === 5);
record("corrected CSV creates exactly five owned tasks");

const openCard = async (index) => {
  if (!await page.evaluate((i) => document.querySelectorAll(".task-edit")[i].open, index))
    await page.click(`#task-heading-${index} ~ .task-edit summary`);
};
const saveCard = async (index, expectedStatus) => {
  await page.click(`#task-heading-${index} ~ .task-edit .task-save`);
  await page.waitForFunction(({ index, expectedStatus }) => {
    const card = document.querySelectorAll(".task-card")[index];
    return card.querySelector(".task-feedback")?.textContent.includes("Saved to the local plan") && (!expectedStatus || card.querySelector("select").value === expectedStatus);
  }, { index, expectedStatus });
};
await openCard(2);
await page.selectOption("#task-edit-2-status", "in_progress");
await page.click("#task-heading-2 ~ .task-edit .task-save");
await page.waitForFunction(() => document.querySelectorAll(".task-feedback")[2].textContent.includes("Dependency"));
assert.match(await page.evaluate(() => document.querySelectorAll(".task-card")[2].textContent), /scope|data access/i);
await page.click('#task-heading-2 ~ .task-edit button[type="button"]');
record("server rejects starting integration while named prerequisites are incomplete");

await openCard(1);
await page.fill("#task-edit-1-title", "Provision synthetic sandbox access — draft retained");
await openCard(0);
await page.selectOption("#task-edit-0-status", "in_progress");
await saveCard(0, "in_progress");
assert.equal(await page.evaluate(() => document.getElementById("task-edit-1-title").value), "Provision synthetic sandbox access — draft retained");
await page.click("#refresh-plan");
await page.waitForFunction(() => document.getElementById("page-feedback").textContent.includes("refreshed"));
assert.equal(await page.evaluate(() => document.getElementById("task-edit-1-title").value), "Provision synthetic sandbox access — draft retained");
await page.click('#task-heading-1 ~ .task-edit button[type="button"]');
record("saving another task and refreshing preserve sibling unsaved drafts");
await openCard(0);
await page.selectOption("#task-edit-0-status", "done");
await saveCard(0, "done");
await page.evaluate(() => document.getElementById("plan").scrollIntoView());
await page.screenshot({ path: path.join(output, "workbench-plan-desktop.png") });
for (const index of [1, 2, 3, 4]) {
  await openCard(index);
  if (index === 1) await page.fill("#task-edit-1-blocker", "");
  await page.selectOption(`#task-edit-${index}-status`, "in_progress");
  await saveCard(index, "in_progress");
  await openCard(index);
  await page.selectOption(`#task-edit-${index}-status`, "done");
  await saveCard(index, "done");
}
assert.equal(await page.evaluate(() => document.getElementById("complete-count").textContent), "5");
assert.equal(await page.evaluate(() => document.getElementById("waiting-count").textContent), "0");
record("explicit access-blocker correction and all dependency-ordered status transitions complete");
await page.click("#validate-intake");
await page.waitForFunction(() => document.getElementById("validation-issues").textContent.includes("identical"));
await page.click("#create-plan");
await page.waitForFunction(() => document.getElementById("page-feedback").textContent.includes("No duplicate"));
assert.equal(await page.evaluate(() => document.querySelectorAll(".task-card").length), 5);
record("duplicate import through UI creates no additional tasks");
await page.fill("#intake-source", corrected.replace("Harbor Supply (synthetic)", "Conflicting customer"));
await page.click("#validate-intake");
await page.waitForFunction(() => document.getElementById("validation-issues").textContent.includes("conflicting"));
assert.equal(await page.evaluate(() => document.getElementById("create-plan").disabled), true);
record("conflicting intake is explicit and existing plan is preserved");
await page.fill("#intake-source", corrected);
const errorsBeforeReload = await page.evaluate(() => window.__qaErrors || []);
await page.reload();
await page.waitForFunction(() => document.getElementById("complete-count").textContent === "5");
assert.equal(await page.evaluate(() => document.getElementById("activity-count").textContent), "11 events");
record("reload retains five completed tasks and eleven timestamped activity entries");
await page.evaluate(() => {
  window.__qaErrors = [];
  window.addEventListener("error", (event) => window.__qaErrors.push(event.message));
  window.addEventListener("unhandledrejection", (event) => window.__qaErrors.push(String(event.reason)));
});
for (const format of ["json", "csv"]) {
  const downloadPromise = page.waitForEvent("download", { timeout: 30000 });
  await page.click(`#export-${format}`);
  const download = await downloadPromise;
  await download.saveAs(path.join(output, `implementation-plan.${format}`));
}
record("actual browser JSON and CSV downloads saved");

await page.cdp("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
await page.evaluate(() => window.scrollTo(0, 0));
assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "Narrow screen must not overflow horizontally");
await page.screenshot({ path: path.join(output, "workbench-mobile.png") });
record("390px narrow screen has no horizontal overflow");
await page.cdp("Emulation.setDeviceMetricsOverride", { width: 900, height: 900, deviceScaleFactor: 1, mobile: false });
assert.equal(await page.evaluate(() => getComputedStyle(document.getElementById("refresh-plan")).display !== "none"), true);
record("tablet refresh recovery control remains visible");
await page.cdp("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });

// A second customer checks real DOM rendering, not a string-pattern assertion.
const markup = '<img src=x onerror="window.__markupExecuted=1">';
const maliciousRecord = [{ customer_id: "markup-demo", customer_name: markup,
  integration: "=2+2", technical_owner: "tech@example.test", data_access_owner: "data@example.test",
  launch_owner: "launch@example.test", acceptance_criteria: '<script>window.__markupExecuted=1</script>' }];
await page.selectOption("#intake-format", "json");
await page.fill("#intake-source", JSON.stringify(maliciousRecord));
await page.click("#validate-intake");
await page.waitForFunction(() => !document.getElementById("create-plan").disabled);
await page.click("#create-plan");
await page.waitForFunction(() => document.querySelectorAll(".task-card").length === 10);
const safety = await page.evaluate(() => ({
  executed: Boolean(window.__markupExecuted),
  injectedElements: document.querySelectorAll('#plan-content img, #plan-content script, #activity-list img, #activity-list script').length,
  literal: document.getElementById("plan-content").textContent.includes('<img src=x onerror="window.__markupExecuted=1">')
}));
assert.deepEqual(safety, { executed: false, injectedElements: 0, literal: true });
record("imported HTML/script payloads remain literal text and create no executable elements");

await page.fill("#intake-source", JSON.stringify(maliciousRecord));
await page.cdp("Network.enable");
await page.cdp("Network.emulateNetworkConditions", { offline: true, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
try {
  await page.click("#validate-intake");
  await page.waitForFunction(() => document.getElementById("page-feedback").textContent.includes("could not be reached"));
} finally {
  await page.cdp("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  await page.cdp("Network.disable");
}
record("network failure produces actionable feedback without a secondary exception");
const runtimeErrors = [...errorsBeforeReload, ...await page.evaluate(() => window.__qaErrors || [])];
assert.deepEqual(runtimeErrors, []);
record("no captured uncaught app errors or unhandled promise rejections");
await fs.writeFile(path.join(output, "browser-results.json"), JSON.stringify({ base, viewports: ["1440x1000", "390x844", "900x900"], results, runtimeErrors, safety }, null, 2) + "\n");
console.log(JSON.stringify({ passed: results.length, failed: 0, output }));
await task.finish({ keep: [] });
