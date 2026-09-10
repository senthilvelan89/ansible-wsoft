"use strict";

const state = {
  currency: "$",
  categories: [],
  orderCategories: [],
  today: new Date().toISOString().slice(0, 10),
  currentOrderId: null,
};

const $ = (id) => document.getElementById(id);
const path = (location.pathname.replace(/\/+$/, "") || "/");
const orderMatch = path.match(/^\/orders\/(\d+)$/);
const page = orderMatch ? "order" : path === "/orders" ? "orders" : "expenses";

const form = $("entry-form");
const fieldDate = $("field-date");
const fieldItem = $("field-item");
const fieldAmount = $("field-amount");
const fieldCategory = $("field-category");
const fieldNote = $("field-note");
const editId = $("edit-id");
const submitButton = $("submit-button");
const cancelEdit = $("cancel-edit");
const filterRange = $("filter-range");
const filterFrom = $("filter-from");
const filterTo = $("filter-to");
const filterCategory = $("filter-category");
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

async function api(pathName, options = {}) {
  const response = await fetch(pathName, {
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

function isIncomeCategory(name) {
  return (name || "").trim().toLowerCase() === "income";
}

function isLabourCategory(name) {
  return (name || "").trim().toLowerCase() === "labour";
}

function dollarsInput(cents) {
  const value = (cents || 0) / 100;
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function renderOverhead(overhead) {
  if (!overhead) return;
  if ($("overhead-summary")) $("overhead-summary").textContent = overhead.summary;
  if ($("overhead-progress")) {
    $("overhead-progress").textContent =
      `${overhead.year}: ${overhead.ytd_reserved_display} of ${overhead.annual_display} set aside (${overhead.remaining_display} still to fund)`;
  }
  const bar = $("overhead-bar");
  if (bar) {
    const pct = Math.max(0, Math.min(100, Math.round((overhead.progress || 0) * 100)));
    bar.style.width = `${pct}%`;
  }
  const annual = $("overhead-annual");
  const monthly = $("overhead-monthly");
  if (annual && document.activeElement !== annual) annual.value = dollarsInput(overhead.annual_cents);
  if (monthly && document.activeElement !== monthly) monthly.value = dollarsInput(overhead.expected_monthly_income_cents);
  if ($("order-overhead-note")) {
    $("order-overhead-note").textContent =
      `Set aside is ${overhead.rate_display} of income toward ${overhead.label}. ` +
      `${overhead.year} reserved so far: ${overhead.ytd_reserved_display} of ${overhead.annual_display}.`;
  }
}

function syncAmountLabel() {
  const income = isIncomeCategory(fieldCategory.value);
  amountLabel.textContent = income ? "Amount received" : "Cost";
  fieldItem.placeholder = income ? "Where did this money come from?" : "What did you buy?";
  if (!editId.value) submitButton.textContent = income ? "Add income" : "Add expense";
}

function showPage() {
  $("view-expenses").classList.toggle("hidden", page !== "expenses");
  $("view-orders").classList.toggle("hidden", page !== "orders");
  $("view-order").classList.toggle("hidden", page !== "order");
  $("nav-expenses").classList.toggle("active", page === "expenses");
  $("nav-orders").classList.toggle("active", page === "orders" || page === "order");
  $("export-link").classList.toggle("hidden", page !== "expenses");
}

function empty(text) {
  return el("p", { class: "empty", text });
}

function lineTable(rows, columns, { onDelete } = {}) {
  if (!rows.length) return empty("Nothing recorded yet.");
  const head = el(
    "tr",
    {},
    columns.map((col) => el("th", { class: col.amount ? "amount" : "", text: col.label }))
  );
  head.appendChild(el("th", { class: "actions", text: "" }));
  const body = rows.map((row) => {
    const tr = el(
      "tr",
      {},
      columns.map((col) =>
        el("td", {
          class: [col.amount ? "amount" : col.date ? "date" : "", typeof col.className === "function" ? col.className(row) : ""]
            .filter(Boolean)
            .join(" "),
          text: col.value(row),
        })
      )
    );
    tr.appendChild(
      el("td", { class: "actions" }, [
        el("button", {
          class: "button link danger",
          text: "Delete",
          onclick: () => onDelete(row),
        }),
      ])
    );
    return tr;
  });
  return el("table", {}, [el("thead", {}, [head]), el("tbody", {}, body)]);
}

// ------------------------------------------------------------- expenses

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
  syncAmountLabel();
}

function expenseTable(expenses, { showDate }) {
  if (!expenses.length) return empty("Nothing recorded yet.");
  const head = el("tr", {}, [
    showDate ? el("th", { text: "Date" }) : null,
    el("th", { text: "Item" }),
    el("th", { text: "Category" }),
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
    container.replaceChildren(empty("No spending in this range."));
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
    container.replaceChildren(empty("No history yet."));
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

async function loadState() {
  const data = await api(`/api/state?date=${encodeURIComponent(fieldDate.value || state.today)}`);
  state.currency = data.currency;
  state.categories = data.categories;
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
  if (filterSearch.value.trim()) params.set("search", filterSearch.value.trim());
  return params;
}

async function loadHistory() {
  const params = currentFilters();
  $("export-link").href = `/export.csv?${params.toString()}`;
  const [listing, summary] = await Promise.all([
    api(`/api/expenses?${params.toString()}`),
    api(`/api/summary?${params.toString()}`),
  ]);
  $("history-total").textContent = `${listing.total_display} spent · ${listing.expenses.length} entries`;
  renderBars($("history-breakdown"), summary.buckets);
  $("history-entries").replaceChildren(expenseTable(listing.expenses, { showDate: true }));
}

async function refreshExpenses() {
  await Promise.all([loadState(), loadHistory()]);
}

function startEdit(expense) {
  editId.value = expense.id;
  fieldDate.value = expense.date;
  fieldItem.value = expense.item;
  fieldAmount.value = (expense.amount_cents / 100).toFixed(2);
  if (!state.categories.includes(expense.category)) {
    fieldCategory.appendChild(el("option", { value: expense.category, text: expense.category }));
  }
  fieldCategory.value = expense.category;
  fieldNote.value = expense.note || "";
  syncAmountLabel();
  submitButton.textContent = `Save changes to #${expense.id}`;
  cancelEdit.classList.remove("hidden");
  fieldItem.focus();
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
  await api(`/api/expenses/${expense.id}`, { method: "DELETE" });
  if (editId.value === String(expense.id)) stopEdit();
  toast("Deleted");
  await refreshExpenses();
}

function wireExpensePage() {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      date: fieldDate.value,
      item: fieldItem.value.trim(),
      amount: fieldAmount.value.trim(),
      category: fieldCategory.value,
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
        fieldItem.value = "";
        fieldAmount.value = "";
        fieldNote.value = "";
      }
      fieldItem.focus();
      await refreshExpenses();
    } catch (error) {
      toast(error.message, true);
    }
  });

  cancelEdit.addEventListener("click", stopEdit);
  $("new-category").addEventListener("click", async () => {
    const name = prompt("Name for the new category:");
    if (!name || !name.trim()) return;
    try {
      const result = await api("/api/categories", { method: "POST", body: JSON.stringify({ name: name.trim() }) });
      state.categories = result.categories;
      renderCategoryOptions();
      fieldCategory.value = result.category;
      toast(`Category "${result.category}" ready`);
    } catch (error) {
      toast(error.message, true);
    }
  });
  fieldCategory.addEventListener("change", syncAmountLabel);
  fieldDate.addEventListener("change", () => loadState().catch((error) => toast(error.message, true)));
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
  [filterFrom, filterTo, filterCategory].forEach((input) =>
    input.addEventListener("change", () => loadHistory().catch((error) => toast(error.message, true)))
  );
  filterSearch.addEventListener(
    "input",
    debounce(() => loadHistory().catch((error) => toast(error.message, true)), 250)
  );
}

// --------------------------------------------------------------- orders

function fillOrderCategories(selected) {
  const select = $("cost-category");
  select.replaceChildren(...state.orderCategories.map((name) => el("option", { value: name, text: name })));
  if (selected && state.orderCategories.includes(selected)) select.value = selected;
  else if (state.orderCategories.includes("Grocery")) select.value = "Grocery";
  $("cost-hours-field").classList.toggle("hidden", !isLabourCategory(select.value));
}

async function loadOrderList() {
  const data = await api("/api/food-orders");
  $("orders-profit-pill").textContent = `After reserve ${data.profit_after_reserve_display}`;
  renderOverhead(data.overhead);
  if (!data.orders.length) {
    $("orders-list").replaceChildren(empty("No food orders yet. Create one above."));
    return;
  }
  const table = lineTable(
    data.orders,
    [
      { label: "Order", value: (row) => row.name },
      { label: "Date", date: true, value: (row) => row.date },
      { label: "Income", amount: true, value: (row) => row.income_display },
      { label: "Expenses", amount: true, value: (row) => row.expense_display },
      { label: "Profit", amount: true, value: (row) => row.profit_display, className: (row) => profitClass(row.profit_cents) },
      { label: "Set aside", amount: true, value: (row) => row.overhead_reserve_display },
      { label: "After reserve", amount: true, value: (row) => row.profit_after_reserve_display, className: (row) => profitClass(row.profit_after_reserve_cents) },
      { label: "Hours", amount: true, value: (row) => row.hours_display },
    ],
    {
      onDelete: async (row) => {
        if (!confirm(`Delete order "${row.name}" and all of its income and costs?`)) return;
        await api(`/api/food-orders/${row.id}`, { method: "DELETE" });
        toast("Order deleted");
        await loadOrderList();
      },
    }
  );
  table.querySelectorAll("tbody tr").forEach((tr, index) => {
    const order = data.orders[index];
    tr.style.cursor = "pointer";
    tr.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      location.href = `/orders/${order.id}`;
    });
  });
  $("orders-list").replaceChildren(table);
}

async function loadOrderDetail(orderId) {
  const [order, categories] = await Promise.all([
    api(`/api/food-orders/${orderId}`),
    api("/api/order-categories"),
  ]);
  state.orderCategories = categories.categories;
  state.currentOrderId = order.id;
  fillOrderCategories($("cost-category").value);
  $("order-title").textContent = order.name;
  $("order-meta").textContent = `${order.date}${order.note ? " · " + order.note : ""}`;
  $("order-profit-pill").textContent = `After reserve ${order.profit_after_reserve_display}`;
  $("order-profit-pill").className = `pill`;
  renderOverhead(order.overhead);
  $("order-stats").replaceChildren(
    ...[
      ["Income", order.income_display, ""],
      ["Expenses", order.expense_display, ""],
      ["Profit", order.profit_display, profitClass(order.profit_cents)],
      ["Set aside", order.overhead_reserve_display, ""],
      ["After reserve", order.profit_after_reserve_display, profitClass(order.profit_after_reserve_cents)],
      ["Labour hours", order.hours_display, ""],
    ].map(([label, value, extra]) =>
      el("div", { class: "stat-card" }, [
        el("span", { class: "label", text: label }),
        el("span", { class: `value ${extra}`, text: value }),
      ])
    )
  );
  renderBars($("order-cost-bars"), order.cost_categories || []);
  $("order-income-table").replaceChildren(
    lineTable(
      order.income_entries || [],
      [
        { label: "Date", date: true, value: (row) => row.date },
        { label: "Item", value: (row) => row.item },
        { label: "Amount", amount: true, value: (row) => row.amount_display },
      ],
      { onDelete: (row) => deleteOrderEntry(row) }
    )
  );
  $("order-cost-table").replaceChildren(
    lineTable(
      order.cost_entries || [],
      [
        { label: "Date", date: true, value: (row) => row.date },
        { label: "Item", value: (row) => row.item },
        { label: "Category", value: (row) => row.category },
        { label: "Cost", amount: true, value: (row) => row.amount_display },
        { label: "Hours", amount: true, value: (row) => (row.hours ? row.hours_display : "") },
      ],
      { onDelete: (row) => deleteOrderEntry(row) }
    )
  );
  if (!$("income-date").value) $("income-date").value = order.date;
  if (!$("cost-date").value) $("cost-date").value = order.date;
}

async function deleteOrderEntry(row) {
  if (!confirm(`Delete "${row.item}" (${row.amount_display})?`)) return;
  await api(`/api/food-orders/${state.currentOrderId}/entries/${row.id}`, { method: "DELETE" });
  toast("Deleted");
  await loadOrderDetail(state.currentOrderId);
}

function wireOrderPages() {
  if ($("new-order-date") && !$("new-order-date").value) $("new-order-date").value = state.today;
  if ($("overhead-form")) {
    $("overhead-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const overhead = await api("/api/overhead", {
          method: "PATCH",
          body: JSON.stringify({
            annual_overhead: $("overhead-annual").value.trim(),
            monthly_order_income: $("overhead-monthly").value.trim(),
          }),
        });
        renderOverhead(overhead);
        toast("Reserve updated");
        if (page === "orders") await loadOrderList();
        else if (state.currentOrderId) await loadOrderDetail(state.currentOrderId);
      } catch (error) {
        toast(error.message, true);
      }
    });
  }
  $("create-order-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const created = await api("/api/food-orders", {
        method: "POST",
        body: JSON.stringify({
          name: $("new-order-name").value.trim(),
          date: $("new-order-date").value,
          note: $("new-order-note").value.trim(),
        }),
      });
      location.href = `/orders/${created.order.id}`;
    } catch (error) {
      toast(error.message, true);
    }
  });

  $("income-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api(`/api/food-orders/${state.currentOrderId}/entries`, {
        method: "POST",
        body: JSON.stringify({
          kind: "income",
          date: $("income-date").value,
          item: $("income-item").value.trim(),
          amount: $("income-amount").value.trim(),
          note: $("income-note").value.trim(),
        }),
      });
      $("income-item").value = "";
      $("income-amount").value = "";
      $("income-note").value = "";
      toast("Income recorded");
      await loadOrderDetail(state.currentOrderId);
    } catch (error) {
      toast(error.message, true);
    }
  });

  $("cost-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api(`/api/food-orders/${state.currentOrderId}/entries`, {
        method: "POST",
        body: JSON.stringify({
          kind: "cost",
          date: $("cost-date").value,
          item: $("cost-item").value.trim(),
          amount: $("cost-amount").value.trim(),
          category: $("cost-category").value,
          hours: $("cost-hours").value.trim(),
          note: $("cost-note").value.trim(),
        }),
      });
      $("cost-item").value = "";
      $("cost-amount").value = "";
      $("cost-hours").value = "";
      $("cost-note").value = "";
      toast("Cost recorded");
      await loadOrderDetail(state.currentOrderId);
    } catch (error) {
      toast(error.message, true);
    }
  });

  $("cost-category").addEventListener("change", () => {
    $("cost-hours-field").classList.toggle("hidden", !isLabourCategory($("cost-category").value));
  });

  $("new-order-category").addEventListener("click", async () => {
    const name = prompt("Name for the new order cost category:");
    if (!name || !name.trim()) return;
    try {
      const result = await api("/api/order-categories", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() }),
      });
      state.orderCategories = result.categories;
      fillOrderCategories(result.category);
      toast(`Category "${result.category}" ready`);
    } catch (error) {
      toast(error.message, true);
    }
  });
}

// ------------------------------------------------------------------ start

showPage();
if (page === "expenses") {
  fieldDate.value = new Date().toISOString().slice(0, 10);
  wireExpensePage();
  refreshExpenses()
    .then(() => fieldItem.focus())
    .catch((error) => toast(error.message, true));
} else if (page === "orders") {
  $("retention-note").textContent = "Income minus costs, with a reserve for rates, ABN and registration";
  wireOrderPages();
  loadOrderList().catch((error) => toast(error.message, true));
} else {
  $("retention-note").textContent = "Income, costs, labour hours, profit and the rates/ABN reserve for this order";
  wireOrderPages();
  loadOrderDetail(Number(orderMatch[1])).catch((error) => toast(error.message, true));
}
