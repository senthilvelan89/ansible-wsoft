"use strict";

const state = {
  today: new Date().toISOString().slice(0, 10),
  categories: [],
  selected: null,
};

const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== null && value !== undefined) node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined) continue;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

let toastTimer = null;
function toast(message, isError = false) {
  const node = $("toast");
  node.textContent = message;
  node.classList.toggle("error", isError);
  node.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("show"), isError ? 4200 : 2200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Task-Planner": "1",
      ...(options.headers || {}),
    },
  });
  let payload = {};
  try {
    payload = await response.json();
  } catch (error) {
    payload = {};
  }
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

function dueText(task) {
  if (!task.due_on) return "no date";
  if (task.is_overdue) return `${task.due_on} · overdue`;
  if (task.is_due_today) return `${task.due_on} · today`;
  return task.due_on;
}

function dueClass(task) {
  if (task.is_overdue) return "overdue";
  if (task.is_due_today) return "today";
  return "";
}

function fillCategorySelects(names, selected) {
  const options = names.map((name) => el("option", { value: name, text: name }));
  const currentTask = $("field-category").value;
  const currentComment = $("comment-category").value;
  $("field-category").replaceChildren(...options.map((node) => node.cloneNode(true)));
  $("comment-category").replaceChildren(...options.map((node) => node.cloneNode(true)));
  const pick = selected || currentTask;
  if (names.includes(pick)) $("field-category").value = pick;
  if (names.includes(currentComment)) $("comment-category").value = currentComment;
  else if (names.includes(pick)) $("comment-category").value = pick;
}

function renderDueSoon(tasks) {
  const container = $("due-soon");
  if (!tasks.length) {
    container.replaceChildren(el("p", { class: "empty", text: "Nothing dated in the next 7 days." }));
    return;
  }
  container.replaceChildren(
    el(
      "div",
      { class: "chips" },
      tasks.map((task) =>
        el("span", { class: `chip ${dueClass(task)}` }, [
          el("strong", { text: task.due_on }),
          el("span", { text: `${task.category}: ${task.title}` }),
        ])
      )
    )
  );
}

function renderBoard(categories) {
  const container = $("board");
  container.replaceChildren(
    ...categories.map((category) => {
      const next = category.next_step;
      const cardClass = [
        "card",
        next ? "" : "missing",
        next && next.is_overdue ? "overdue" : "",
      ]
        .filter(Boolean)
        .join(" ");

      const nextBlock = next
        ? el("div", { class: "next-step" }, [
            el("div", { class: "next-label", text: "Next step" }),
            el("div", { class: "next-title", text: next.title }),
            el("div", { class: `next-meta ${dueClass(next)}`, text: dueText(next) }),
            el("div", { class: "next-actions" }, [
              el("button", {
                class: "button primary small",
                text: "Mark done",
                onclick: (event) => {
                  event.stopPropagation();
                  completeTask(next);
                },
              }),
              el("button", {
                class: "button ghost small",
                text: "Comment",
                onclick: (event) => {
                  event.stopPropagation();
                  startComment(category.name, next);
                },
              }),
            ]),
          ])
        : el("p", {
            class: "empty-next",
            text: "No next step — add one so this category is not skipped.",
          });

      const upcoming = category.upcoming.length
        ? el(
            "ol",
            { class: "upcoming" },
            category.upcoming.map((task) =>
              el("li", { text: `${task.title}${task.due_on ? " · " + task.due_on : ""}` })
            )
          )
        : null;

      const note = category.latest_comment
        ? el("div", {
            class: "latest-note",
            text: `${category.latest_comment.comment_on}: ${category.latest_comment.body}`,
          })
        : el("div", { class: "latest-note", text: "No comments yet" });

      return el(
        "article",
        {
          class: cardClass,
          onclick: () => openDetail(category.name),
        },
        [
          el("div", { class: "card-head" }, [
            el("h3", { text: category.name }),
            el("span", { class: "count", text: `${category.open_count} open` }),
          ]),
          nextBlock,
          upcoming,
          note,
        ]
      );
    })
  );
}

function renderActivity(comments) {
  const container = $("activity");
  if (!comments.length) {
    container.replaceChildren(el("p", { class: "empty", text: "No comments yet. Add dated notes as you go." }));
    return;
  }
  const head = el("tr", {}, [
    el("th", { text: "Date" }),
    el("th", { text: "Category" }),
    el("th", { text: "Comment" }),
    el("th", { class: "actions", text: "" }),
  ]);
  const rows = comments.map((comment) =>
    el("tr", {}, [
      el("td", { class: "date", text: comment.comment_on }),
      el("td", {}, [
        el("span", { class: "tag", text: comment.category }),
        comment.task_title ? el("span", { class: "note", text: comment.task_title }) : null,
      ]),
      el("td", { text: comment.body }),
      el("td", { class: "actions" }, [
        el("button", {
          class: "button link danger",
          text: "Delete",
          onclick: () => removeComment(comment),
        }),
      ]),
    ])
  );
  container.replaceChildren(el("table", {}, [el("thead", {}, [head]), el("tbody", {}, rows)]));
}

function renderDetail(data) {
  const panel = $("detail-panel");
  if (!state.selected) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  $("detail-heading").textContent = `${state.selected} queue`;

  const tasks = data.detail.tasks || [];
  if (!tasks.length) {
    $("detail-queue").replaceChildren(el("p", { class: "empty", text: "Nothing queued in this category." }));
  } else {
    const open = tasks.filter((task) => task.status === "open");
    const nextId = open.length ? open[0].id : null;
    const head = el("tr", {}, [
      el("th", { text: "" }),
      el("th", { text: "Step" }),
      el("th", { text: "Due" }),
      el("th", { class: "actions", text: "" }),
    ]);
    const rows = tasks.map((task) => {
      const isNext = task.id === nextId;
      return el("tr", {}, [
        el("td", {}, [
          el("span", {
            class: `tag ${isNext ? "next" : ""} ${task.status === "done" ? "done" : ""}`,
            text: isNext ? "NEXT" : task.status,
          }),
        ]),
        el("td", { text: task.title }),
        el("td", { class: `date ${dueClass(task)}`, text: dueText(task) }),
        el("td", { class: "actions" }, [
          task.status === "open"
            ? el("button", { class: "button link", text: "Sooner", onclick: () => moveTask(task, "up") })
            : null,
          task.status === "open"
            ? el("button", { class: "button link", text: "Done", onclick: () => completeTask(task) })
            : el("button", { class: "button link", text: "Reopen", onclick: () => reopenTask(task) }),
          el("button", {
            class: "button link danger",
            text: "Delete",
            onclick: () => removeTask(task),
          }),
        ]),
      ]);
    });
    $("detail-queue").replaceChildren(el("table", {}, [el("thead", {}, [head]), el("tbody", {}, rows)]));
  }

  const comments = data.detail.comments || [];
  if (!comments.length) {
    $("detail-comments").replaceChildren(el("p", { class: "empty", text: "No comments in this category." }));
  } else {
    $("detail-comments").replaceChildren(
      el(
        "table",
        {},
        [
          el("thead", {}, [
            el("tr", {}, [el("th", { text: "Date" }), el("th", { text: "Comment" }), el("th", { class: "actions", text: "" })]),
          ]),
          el(
            "tbody",
            {},
            comments.map((comment) =>
              el("tr", {}, [
                el("td", { class: "date", text: comment.comment_on }),
                el("td", {}, [
                  el("span", { text: comment.body }),
                  comment.task_title ? el("span", { class: "note", text: comment.task_title }) : null,
                ]),
                el("td", { class: "actions" }, [
                  el("button", {
                    class: "button link danger",
                    text: "Delete",
                    onclick: () => removeComment(comment),
                  }),
                ]),
              ])
            )
          ),
        ]
      )
    );
  }
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadState() {
  const params = state.selected ? `?category=${encodeURIComponent(state.selected)}` : "";
  const data = await api(`/api/state${params}`);
  state.today = data.today;
  state.categories = data.categories.map((category) => category.name);

  const stats = data.stats;
  $("status-note").textContent =
    `${stats.with_next_step} of ${stats.categories} categories have a next step · ${stats.missing_next_step} missing · ${stats.overdue} overdue`;
  $("port-note").textContent = `port ${data.port || 8766}`;
  $("due-count").textContent = `${data.due_soon.length} dated`;
  $("due-count").classList.toggle("danger", stats.overdue > 0);
  $("due-count").classList.toggle("warn", stats.overdue === 0 && stats.due_today > 0);
  $("board-count").textContent = `${stats.open_tasks} open`;

  fillCategorySelects(state.categories, $("field-category").value);
  renderDueSoon(data.due_soon);
  renderBoard(data.categories);
  renderActivity(data.recent_comments);
  renderDetail(data);
}

async function refresh() {
  try {
    await loadState();
  } catch (error) {
    toast(error.message, true);
  }
}

async function completeTask(task) {
  try {
    const result = await api(`/api/tasks/${task.id}/done`, { method: "POST" });
    if (result.next_step) {
      toast(`Next in ${task.category}: ${result.next_step.title}`);
    } else {
      toast(`Done. Add a next step in ${task.category} so it is not skipped.`);
    }
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
}

async function reopenTask(task) {
  try {
    await api(`/api/tasks/${task.id}/reopen`, { method: "POST", body: JSON.stringify({ as_next: true }) });
    toast("Reopened as next step");
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
}

async function moveTask(task, direction) {
  try {
    await api(`/api/tasks/${task.id}/move`, { method: "POST", body: JSON.stringify({ direction }) });
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
}

async function removeTask(task) {
  if (!confirm(`Delete "${task.title}" from ${task.category}?`)) return;
  try {
    await api(`/api/tasks/${task.id}`, { method: "DELETE" });
    toast("Deleted");
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
}

async function removeComment(comment) {
  if (!confirm("Delete this comment?")) return;
  try {
    await api(`/api/comments/${comment.id}`, { method: "DELETE" });
    toast("Comment removed");
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
}

function startComment(category, task) {
  $("comment-category").value = category;
  $("comment-body").placeholder = task ? `Note on: ${task.title}` : "Called, waiting, blocked…";
  $("comment-body").dataset.taskId = task ? String(task.id) : "";
  $("comment-body").focus();
  $("comment-form").scrollIntoView({ behavior: "smooth", block: "center" });
}

function openDetail(name) {
  state.selected = name;
  $("field-category").value = name;
  $("comment-category").value = name;
  refresh();
}

$("close-detail").addEventListener("click", () => {
  state.selected = null;
  refresh();
});

$("task-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    category: $("field-category").value,
    title: $("field-title").value.trim(),
    due_on: $("field-due").value || null,
    as_next: $("field-as-next").checked,
  };
  try {
    const result = await api("/api/tasks", { method: "POST", body: JSON.stringify(payload) });
    toast(`Queued in ${result.task.category}`);
    $("field-title").value = "";
    $("field-due").value = "";
    $("field-as-next").checked = false;
    $("field-title").focus();
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
});

$("comment-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    category: $("comment-category").value,
    body: $("comment-body").value.trim(),
    date: $("comment-date").value,
  };
  const taskId = $("comment-body").dataset.taskId;
  if (taskId) payload.task_id = Number(taskId);
  try {
    await api("/api/comments", { method: "POST", body: JSON.stringify(payload) });
    toast("Comment saved");
    $("comment-body").value = "";
    $("comment-body").dataset.taskId = "";
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
});

$("new-category").addEventListener("click", async () => {
  const name = prompt("Name for the new category:");
  if (!name || !name.trim()) return;
  try {
    const result = await api("/api/categories", { method: "POST", body: JSON.stringify({ name: name.trim() }) });
    state.categories = result.categories.map((category) => category.name);
    fillCategorySelects(state.categories, result.category.name);
    toast(`Category "${result.category.name}" ready`);
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
});

$("comment-date").value = new Date().toISOString().slice(0, 10);
refresh().then(() => $("field-title").focus());
