"use strict";

// Only the hosted build loads this adapter. SQLite remains the local default.
// A browser transaction commits the server-validated snapshot iff its revision
// still matches. Separate visitors never share a server-side writable plan.
(() => {
  const EMPTY = () => ({
    schema_version: 1,
    revision: 0,
    customers: [],
    tasks: [],
    activity: [],
  });
  let database;
  const storageError = () =>
    new Error(
      "This browser could not save the demo plan. Allow site storage, then refresh. Existing data was not reset.",
    );
  const conflict = () =>
    Object.assign(
      new Error(
        "This plan changed in another tab. Refresh before saving. Your edits are preserved.",
      ),
      { status: 409 },
    );
  function openDatabase() {
    if (!database)
      database = new Promise((resolve, reject) => {
        const opening = indexedDB.open("implementation-workbench-demo", 1);
        opening.onupgradeneeded = () =>
          opening.result.createObjectStore("plan");
        opening.onerror = () => {
          database = undefined;
          reject(storageError());
        };
        opening.onblocked = () => {
          database = undefined;
          reject(
            new Error(
              "Close other Workbench tabs, then refresh to reconnect browser storage.",
            ),
          );
        };
        opening.onsuccess = () => {
          const db = opening.result;
          db.onversionchange = () => {
            db.close();
            database = undefined;
          };
          resolve(db);
        };
      });
    return database;
  }
  async function readSnapshot() {
    const db = await openDatabase();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction("plan", "readonly");
      const reading = transaction.objectStore("plan").get("current");
      reading.onsuccess = () =>
        resolve(reading.result === undefined ? EMPTY() : reading.result);
      reading.onerror = () => reject(storageError());
      transaction.onabort = () => reject(storageError());
    });
  }
  async function commitSnapshot(state, revision) {
    const db = await openDatabase();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction("plan", "readwrite");
      const store = transaction.objectStore("plan");
      const reading = store.get("current");
      let stale = false;
      reading.onsuccess = () => {
        const current = reading.result === undefined ? EMPTY() : reading.result;
        if (current.revision !== revision) {
          stale = true;
          transaction.abort();
          return;
        }
        store.put(state, "current");
      };
      transaction.oncomplete = () => resolve();
      transaction.onabort = () => reject(stale ? conflict() : storageError());
      transaction.onerror = () => reject(storageError());
    });
  }
  async function operation(name, data, state) {
    const body = JSON.stringify({ operation: name, data, state });
    if (new TextEncoder().encode(body).length > 1024 * 1024)
      throw new Error(
        "The saved plan and intake exceed this demo's 1 MB request limit. Export your plan and use a smaller synthetic intake.",
      );
    let response;
    try {
      response = await fetch("/api/onboarding", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });
    } catch (_) {
      throw new Error(
        "The demo service could not be reached. Check your connection and try again. Your saved browser plan is preserved.",
      );
    }
    let result;
    try {
      result = await response.json();
    } catch (_) {
      throw new Error(
        "The demo service returned an unreadable response. Your saved browser plan is preserved.",
      );
    }
    if (!response.ok)
      throw Object.assign(
        new Error(result.error || "The demo request could not be completed."),
        { status: response.status, issues: result.issues || [] },
      );
    return result;
  }
  async function request(path, options = {}) {
    const url = new URL(path, location.origin);
    const data = options.body ? JSON.parse(options.body) : {};
    const state = await readSnapshot();
    let name;
    if (url.pathname === "/api/onboarding") name = "read";
    else if (url.pathname === "/api/onboarding/example") {
      name = "example";
      data.format = url.searchParams.get("format") || "csv";
      data.invalid = url.searchParams.get("invalid") !== "0";
    } else if (url.pathname === "/api/onboarding/preview") name = "preview";
    else if (url.pathname === "/api/onboarding/import") name = "import";
    else if (url.pathname.startsWith("/api/onboarding/tasks/")) {
      name = "update";
      data.task_id = decodeURIComponent(
        url.pathname.slice("/api/onboarding/tasks/".length),
      );
    } else if (url.pathname === "/api/onboarding/export") {
      name = "export";
      data.format = url.searchParams.get("format") || "json";
    } else throw new Error("Unknown demo operation.");
    if (
      (name === "import" || name === "update") &&
      data.revision !== state.revision
    )
      throw conflict();
    const response = await operation(name, data, state);
    if (name === "import" || name === "update")
      await commitSnapshot(response.state, state.revision);
    return response.result;
  }
  window.WorkbenchTransport = { request };
  document.addEventListener("DOMContentLoaded", () => {
    for (const link of document.querySelectorAll(".export-link"))
      link.addEventListener("click", async (event) => {
        event.preventDefault();
        if (link.getAttribute("aria-disabled") === "true") return;
        try {
          const result = await request(link.href);
          const blob = new Blob([result.text], {
            type:
              result.format === "json"
                ? "application/json"
                : "text/csv;charset=utf-8",
          });
          const url = URL.createObjectURL(blob);
          const download = document.createElement("a");
          download.href = url;
          download.download = `implementation-plan.${result.format}`;
          document.body.append(download);
          download.click();
          download.remove();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        } catch (error) {
          const box = document.getElementById("page-feedback");
          box.textContent = error.message;
          box.className = "feedback page-feedback error";
          box.hidden = false;
          box.scrollIntoView({ behavior: "auto", block: "center" });
        }
      });
  });
})();
