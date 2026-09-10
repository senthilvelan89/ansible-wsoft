"use strict";

const state = {
  currency: "$",
  categories: [],
  orderNames: [],
  today: new Date().toISOString().slice(0, 10),
};

const $ = (id) => document.getElementById(id);

const form = $("entry-form");
const fieldDate = $("field-date");
const fieldItem = $("field-item");
const fieldAmount = $("field-amount");
const fieldCategory = $("field-category");
const fieldOrder = $("field-order");
const fieldNote = $("field-note");
const editId = $("edit-id");
const submitButton = $("submit-button");
const cancelEdit = $("cancel-edit");
const filterRange = $("filter-range");
const filterFrom = $("filter-from");
const filterTo = $("filter-to");
const filterCategory = $("filter-category");
const filterOrder = $("filter-order");
const filterSearch = $("filter-search");
const amountLabel = $("amount-label");

// ------------------------------------------------------------------ utils

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
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
      "X-Expense-Tracker": "1",
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

function money(cents) {
  const negative = cents < 0;
  const value = Math.abs(cents) / 100;
  const text = state.currency + value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return negative ? "-" + text : text;
}

function debounce(fn, wait) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

function monthLabel(key) {
  const [year, month] = key.split("-").map(Number);
  const date = new Date(year, month - 1, 1);
  const name = date.toLocaleString(undefined, { month: "short" });
  return month === 1 ? `${name} '${String(year).slice(2)}` : name;
}

// ------------------------------------------------------------- rendering

function isIncomeCategory(name) {
  return (name || "").trim().toLowerCase() === "income";
}

function syncAmountLabel() {
  const income = isIncomeCategory(fieldCategory.value);
  amountLabel.textContent = income ? "Amount received" : "Cost";
  fieldItem.placeholder = income ? "Which food order was this payment for?" : "What did you buy?";
  submitButton.textContent = editId.value
    ? `Save changes to #${editId.value}`
    : income
      ? "Add income"
      : "Add expense";
}

function renderCategoryOptions() {
  const current = fieldCategory.value;
  fieldCategory.replaceChildren(...state.categories.map((name) => el("option", { value: name, text: name })));
  if (state.categories.includes(current)) fieldCategory.value = current;
  else if (state.categories.includes("Dining")) fieldCategory.value = "Dining";

  const selectedFilter = filterCategory.value;
  filterCategory.replaceChildren(
    el("option", { value: "", text: "All categories" }),
    ...state.categories.map((name) => el("option", { value: name, text: name }))
  );
  if (state.categories.includes(selectedFilter)) filterCategory.value = selectedFilter;

  const suggestions = $("order-suggestions");
  suggestions.replaceChildren(...state.orderNames.map((name) => el("option", { value: name })));

  const selectedOrder = filterOrder.value;
  filterOrder.replaceChildren(
    el("option", { value: "", text: "All orders" }),
    ...state.orderNames.map((name) => el("option", { value: name, text: name }))
  );
  if (state.orderNames.includes(selectedOrder)) filterOrder.value = selectedOrder;
  syncAmountLabel();
}

function expenseTable(expenses, { showDate }) {
  if (!expenses.length) {
    return el("p", { class: "empty", text: "Nothing recorded yet." });
  }

  const head = el("tr", {}, [
    showDate ? el("th", { text: "Date" }) : null,
    el("th", { text: "Item" }),
    el("th", { text: "Category" }),
    el("th", { text: "Order" }),
    el("th", { class: "amount", text: "Amount" }),
    el("th", { class: "actions", text: "" }),
  ]);

  const rows = expenses.map((expense) =>
    el("tr", {}, [
      showDate ? el("td", { class: "date", text: expense.date }) : null,
      el("td", {}, [
        el("span", { text: expense.item }),
        expense.note ? el("span", { class: "note", text: expense.note }) : null,
      ]),
      el("td", {}, [
        el("span", { class: expense.is_income ? "tag income" : "tag", text: expense.category }),
      ]),
      el("td", {}, expense.order_name ? [el("span", { class: "tag", text: expense.order_name })] : [el("span", { class: "note", text: "" })]),
      el("td", { class: "amount", text: expense.amount_display }),
      el("td", { class: "actions" }, [
        el("button", { class: "button link", text: "Edit", onclick: () => startEdit(expense) }),
        el("button", {
          class: "button link danger",
          text: "Delete",
          onclick: () => removeExpense(expense),
        }),
      ]),
    ])
  );

  return el("table", {}, [el("thead", {}, [head]), el("tbody", {}, rows)]);
}

function renderBars(container, buckets) {
  if (!buckets.length) {
    container.replaceChildren(el("p", { class: "empty", text: "No spending in this range." }));
    return;
  }
  const largest = Math.max(...buckets.map((bucket) => Math.abs(bucket.total_cents)), 1);
  const total = buckets.reduce((sum, bucket) => sum + bucket.total_cents, 0);
  container.replaceChildren(
    ...buckets.map((bucket) => {
      const share = total ? Math.round((bucket.total_cents / total) * 100) : 0;
      return el("div", { class: "bar-row" }, [
        el("span", { class: "bar-label", text: `${bucket.key} · ${share}%` }),
        el("span", { class: "bar-value", text: bucket.total_display }),
        el("div", { class: "bar-track" }, [
          el("div", {
            class: "bar-fill",
            style: `width: ${Math.max((Math.abs(bucket.total_cents) / largest) * 100, 2)}%`,
          }),
        ]),
      ]);
    })
  );
}

function renderTrend(months) {
  const container = $("trend");
  if (!months.length) {
    container.replaceChildren(el("p", { class: "empty", text: "No history yet." }));
    return;
  }
  const largest = Math.max(...months.map((bucket) => Math.abs(bucket.total_cents)), 1);
  container.replaceChildren(
    ...months.map((bucket) =>
      el("div", { class: "trend-col", title: `${bucket.key}: ${bucket.total_display}` }, [
        el("div", {
          class: "trend-bar",
          style: `height: ${Math.max((Math.abs(bucket.total_cents) / largest) * 100, 2)}%`,
        }),
        el("span", { class: "month", text: monthLabel(bucket.key) }),
      ])
    )
  );
}

function renderOrders(orders, totals) {
  const container = $("orders-table");
  $("orders-total").textContent = totals
    ? `Profit ${totals.profit_display}`
    : "—";
  if (!orders.length) {
    container.replaceChildren(
      el("p", {
        class: "empty",
        text: "No food orders in this range. Log income with category Income and put the same order name on the costs.",
      })
    );
    return;
  }

  const stats = el("p", { class: "order-stats" }, [
    el("span", {}, ["Income ", el("strong", { text: totals.income_display })]),
    el("span", {}, ["Expenses ", el("strong", { text: totals.expense_display })]),
    el("span", {}, [
      "Profit ",
      el("strong", {
        class: totals.profit_cents >= 0 ? "profit-positive" : "profit-negative",
        text: totals.profit_display,
      }),
    ]),
  ]);

  const head = el("tr", {}, [
    el("th", { text: "Order" }),
    el("th", { text: "Last date" }),
    el("th", { class: "amount", text: "Income" }),
    el("th", { class: "amount", text: "Expenses" }),
    el("th", { class: "amount", text: "Profit" }),
  ]);
  const rows = orders.map((order) =>
    el("tr", {}, [
      el("td", {}, [el("span", { text: order.name })]),
      el("td", { class: "date", text: order.last_date || "" }),
      el("td", { class: "amount", text: order.income_display }),
      el("td", { class: "amount", text: order.expense_display }),
      el("td", {
        class: `amount ${order.profit_cents >= 0 ? "profit-positive" : "profit-negative"}`,
        text: order.profit_display,
      }),
    ])
  );
  container.replaceChildren(stats, el("table", {}, [el("thead", {}, [head]), el("tbody", {}, rows)]));
}

// --------------------------------------------------------------- loading

async function loadState() {
  const data = await api(`/api/state?date=${encodeURIComponent(fieldDate.value || state.today)}`);
  state.currency = data.currency;
  state.categories = data.categories;
  state.orderNames = data.order_names || [];
  state.today = data.today;

  renderCategoryOptions();

  $("retention-note").textContent =
    `Keeping ${data.retention_months} months of history · entries before ${data.retention_cutoff} are archived to CSV`;

  let dayLabel = `${data.day.total_display} spent on ${data.day.date}`;
  if (data.day.income_cents) dayLabel += ` · ${data.day.income_display} in`;
  $("day-total").textContent = dayLabel;
  $("day-label").textContent = data.day.date === data.today ? `today (${data.day.date})` : data.day.date;
  $("day-entries").replaceChildren(expenseTable(data.day.expenses, { showDate: false }));

  $("month-total").textContent = data.month.total_display + " spent";
  $("month-label").textContent = `${data.month.label} · ${data.month.start} to ${data.month.end}`;
  renderBars($("month-breakdown"), data.month.categories);

  $("window-total").textContent =
    `${data.window.total_display} between ${data.window.start} and ${data.window.end}`;
  renderTrend(data.window.months);
}

function currentFilters() {
  const params = new URLSearchParams();
  const range = filterRange.value;
  if (range === "month") params.set("month", "this");
  else if (range === "last-month") params.set("month", "last");
  else if (range === "custom") {
    if (filterFrom.value) params.set("from", filterFrom.value);
    if (filterTo.value) params.set("to", filterTo.value);
  } else params.set("days", range);

  if (filterCategory.value) params.set("category", filterCategory.value);
  if (filterOrder.value) params.set("order", filterOrder.value);
  if (filterSearch.value.trim()) params.set("search", filterSearch.value.trim());
  return params;
}

async function loadHistory() {
  const params = currentFilters();
  $("export-link").href = `/export.csv?${params.toString()}`;

  const [listing, summary, orders] = await Promise.all([
    api(`/api/expenses?${params.toString()}`),
    api(`/api/summary?${params.toString()}`),
    api(`/api/orders?${params.toString()}`),
  ]);

  $("history-total").textContent = `${listing.total_display} spent · ${listing.expenses.length} entries`;
  renderBars($("history-breakdown"), summary.buckets);
  $("history-entries").replaceChildren(expenseTable(listing.expenses, { showDate: true }));
  $("orders-label").textContent =
    "Income minus costs for each named food order in this range. Use the same order name on both.";
  renderOrders(orders.orders, orders);
}

async function refresh() {
  try {
    await Promise.all([loadState(), loadHistory()]);
  } catch (error) {
    toast(error.message, true);
  }
}

// ---------------------------------------------------------------- actions

function startEdit(expense) {
  editId.value = expense.id;
  fieldDate.value = expense.date;
  fieldItem.value = expense.item;
  fieldAmount.value = (expense.amount_cents / 100).toFixed(2);
  if (!state.categories.includes(expense.category)) {
    fieldCategory.appendChild(el("option", { value: expense.category, text: expense.category }));
  }
  fieldCategory.value = expense.category;
  fieldOrder.value = expense.order_name || "";
  fieldNote.value = expense.note || "";
  syncAmountLabel();
  submitButton.textContent = `Save changes to #${expense.id}`;
  cancelEdit.classList.remove("hidden");
  fieldItem.focus();
  fieldItem.scrollIntoView({ behavior: "smooth", block: "center" });
}

function stopEdit() {
  editId.value = "";
  fieldItem.value = "";
  fieldAmount.value = "";
  fieldNote.value = "";
  submitButton.textContent = "Add expense";
  cancelEdit.classList.add("hidden");
  syncAmountLabel();
}

async function removeExpense(expense) {
  if (!confirm(`Delete "${expense.item}" (${expense.amount_display}) from ${expense.date}?`)) return;
  try {
    await api(`/api/expenses/${expense.id}`, { method: "DELETE" });
    if (editId.value === String(expense.id)) stopEdit();
    toast("Deleted");
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    date: fieldDate.value,
    item: fieldItem.value.trim(),
    amount: fieldAmount.value.trim(),
    category: fieldCategory.value,
    order_name: fieldOrder.value.trim(),
    note: fieldNote.value.trim(),
  };

  try {
    if (editId.value) {
      await api(`/api/expenses/${editId.value}`, { method: "PATCH", body: JSON.stringify(payload) });
      toast("Saved");
      stopEdit();
    } else {
      const result = await api("/api/expenses", { method: "POST", body: JSON.stringify(payload) });
      const kind = result.expense.is_income ? "income" : result.expense.category;
      toast(`Added ${result.expense.amount_display} to ${kind}`);
      if (result.expense.order_name) fieldOrder.value = result.expense.order_name;
      fieldItem.value = "";
      fieldAmount.value = "";
      fieldNote.value = "";
    }
    fieldItem.focus();
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
});

cancelEdit.addEventListener("click", stopEdit);

$("new-category").addEventListener("click", async () => {
  const name = prompt("Name for the new category:");
  if (!name || !name.trim()) return;
  try {
    const result = await api("/api/categories", {
      method: "POST",
      body: JSON.stringify({ name: name.trim() }),
    });
    state.categories = result.categories;
    renderCategoryOptions();
    fieldCategory.value = result.category;
    toast(`Category "${result.category}" ready`);
  } catch (error) {
    toast(error.message, true);
  }
});

fieldCategory.addEventListener("change", syncAmountLabel);

fieldDate.addEventListener("change", () => {
  loadState().catch((error) => toast(error.message, true));
});

filterRange.addEventListener("change", () => {
  const custom = filterRange.value === "custom";
  $("custom-from-field").classList.toggle("hidden", !custom);
  $("custom-to-field").classList.toggle("hidden", !custom);
  if (custom && !filterFrom.value && !filterTo.value) {
    const now = new Date();
    filterFrom.value = new Date(now.getFullYear(), now.getMonth(), 1).toLocaleDateString("en-CA");
    filterTo.value = new Date(now.getFullYear(), now.getMonth() + 1, 0).toLocaleDateString("en-CA");
  }
  loadHistory().catch((error) => toast(error.message, true));
});

[filterFrom, filterTo, filterCategory, filterOrder].forEach((input) =>
  input.addEventListener("change", () => loadHistory().catch((error) => toast(error.message, true)))
);

filterSearch.addEventListener(
  "input",
  debounce(() => loadHistory().catch((error) => toast(error.message, true)), 250)
);

// ------------------------------------------------------------------ start

fieldDate.value = new Date().toISOString().slice(0, 10);
refresh().then(() => fieldItem.focus());
