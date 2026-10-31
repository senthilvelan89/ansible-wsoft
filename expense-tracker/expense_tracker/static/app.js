"use strict";

const state = {
  currency: "$",
  categories: [],
  expenseCategories: [],
  orderCategories: [],
  today: new Date().toISOString().slice(0, 10),
  currentOrderId: null,
};

const $ = (id) => document.getElementById(id);
const path = (location.pathname.replace(/\/+$/, "") || "/");
const orderMatch = path.match(/^\/orders\/(\d+)$/);
const page = orderMatch
  ? "order"
  : path === "/orders"
    ? "orders"
    : path === "/statements"
      ? "statements"
      : path === "/income"
        ? "income"
        : "expenses";

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

function expenseCategories() {
  if (state.expenseCategories && state.expenseCategories.length) {
    return state.expenseCategories;
  }
  return (state.categories || []).filter((name) => !isIncomeCategory(name));
}

function isLabourCategory(name) {
  return (name || "").trim().toLowerCase() === "labour";
}


function profitClass(cents) {
  return cents >= 0 ? "profit-positive" : "profit-negative";
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
      `${overhead.year}: ${overhead.ytd_reserved_display} of ${overhead.annual_display} for rates/ABN (${overhead.remaining_display} still to fund). ` +
      `Income tax set aside: ${overhead.ytd_tax_display} (${overhead.tax_percent_display} of profit).`;
  }
  const bar = $("overhead-bar");
  if (bar) {
    const pct = Math.max(0, Math.min(100, Math.round((overhead.progress || 0) * 100)));
    bar.style.width = `${pct}%`;
  }
  const annual = $("overhead-annual");
  const monthly = $("overhead-monthly");
  const tax = $("overhead-tax");
  if (annual && document.activeElement !== annual) annual.value = dollarsInput(overhead.annual_cents);
  if (monthly && document.activeElement !== monthly) monthly.value = dollarsInput(overhead.expected_monthly_income_cents);
  if (tax && document.activeElement !== tax) {
    const rate = overhead.tax_percent;
    tax.value = Number.isInteger(rate) ? String(rate) : String(rate);
  }
  if ($("order-overhead-note")) {
    $("order-overhead-note").textContent =
      `${overhead.rate_display} of income toward ${overhead.label}; ${overhead.tax_percent_display} of profit toward ${overhead.tax_label}. ` +
      `${overhead.year} so far: rates/ABN ${overhead.ytd_reserved_display} of ${overhead.annual_display}, tax ${overhead.ytd_tax_display}.`;
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
  $("view-income").classList.toggle("hidden", page !== "income");
  $("view-orders").classList.toggle("hidden", page !== "orders");
  $("view-order").classList.toggle("hidden", page !== "order");
  $("view-statements").classList.toggle("hidden", page !== "statements");
  $("nav-expenses").classList.toggle("active", page === "expenses");
  $("nav-income").classList.toggle("active", page === "income");
  $("nav-orders").classList.toggle("active", page === "orders" || page === "order");
  $("nav-statements").classList.toggle("active", page === "statements");
  $("export-link").classList.toggle("hidden", page !== "expenses" && page !== "income");
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
  const names = expenseCategories();
  const current = fieldCategory.value;
  fieldCategory.replaceChildren(...names.map((name) => el("option", { value: name, text: name })));
  if (names.includes(current)) fieldCategory.value = current;
  else if (names.includes("Dining")) fieldCategory.value = "Dining";

  const selectedFilter = filterCategory.value;
  filterCategory.replaceChildren(
    el("option", { value: "", text: "All categories" }),
    ...names.map((name) => el("option", { value: name, text: name }))
  );
  if (names.includes(selectedFilter)) filterCategory.value = selectedFilter;
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

function renderMonthBudgets(month) {
  const node = $("month-budgets");
  if (!month.budgets || !month.budgets.length) {
    node.classList.add("hidden");
    node.replaceChildren();
    return;
  }
  node.classList.remove("hidden");
  const title = month.budgets_preview
    ? "October remaining · September left as-is"
    : "Remaining this month";
  node.replaceChildren(
    el("h3", { class: "section-title", text: title }),
    ...month.budgets.map((row) =>
      el("div", { class: row.over ? "budget-row over" : "budget-row" }, [
        el("span", { class: "budget-name", text: row.category }),
        el("span", { class: "budget-spent", text: `spent ${row.spent_display}` }),
        el("span", { class: "budget-left", text: row.remaining_label }),
      ])
    )
  );
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
  state.expenseCategories = data.expense_categories || [];
  state.today = data.today;
  renderCategoryOptions();
  $("retention-note").textContent =
    `Keeping ${data.retention_months} months of history · entries before ${data.retention_cutoff} are archived to CSV`;
  $("day-total").textContent = `${data.day.total_display} spent on ${data.day.date}`;
  $("day-label").textContent = data.day.date === data.today ? `today (${data.day.date})` : data.day.date;
  $("day-entries").replaceChildren(
    expenseTable(
      (data.day.expenses || []).filter((row) => !row.is_income),
      { showDate: false }
    )
  );
  $("month-total").textContent = data.month.total_display + " spent";
  $("month-label").textContent = `${data.month.label} · ${data.month.start} to ${data.month.end}`;
  renderMonthBudgets(data.month);
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
  params.set("exclude_income", "1");
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
  $("orders-profit-pill").textContent = `Keep ${data.keep_display}`;
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
      { label: "Rates", amount: true, value: (row) => row.overhead_reserve_display },
      { label: "Tax", amount: true, value: (row) => row.tax_reserve_display },
      { label: "Keep", amount: true, value: (row) => row.keep_display, className: (row) => profitClass(row.keep_cents) },
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
  $("order-profit-pill").textContent = `Keep ${order.keep_display}`;
  $("order-profit-pill").className = `pill`;
  renderOverhead(order.overhead);
  $("order-stats").replaceChildren(
    ...[
      ["Income", order.income_display, ""],
      ["Expenses", order.expense_display, ""],
      ["Profit", order.profit_display, profitClass(order.profit_cents)],
      ["Rates / ABN", order.overhead_reserve_display, ""],
      ["Income tax", order.tax_reserve_display, ""],
      ["Keep", order.keep_display, profitClass(order.keep_cents)],
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
            income_tax_percent: $("overhead-tax").value.trim(),
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

// --------------------------------------------------------------- income

function incomeTable(entries, { showDate }) {
  if (!entries.length) return empty("Nothing recorded yet.");
  const head = el("tr", {}, [
    showDate ? el("th", { text: "Date" }) : null,
    el("th", { text: "Source" }),
    el("th", { class: "amount", text: "Amount" }),
    el("th", { class: "actions", text: "" }),
  ]);
  const rows = entries.map((entry) =>
    el("tr", {}, [
      showDate ? el("td", { class: "date", text: entry.date }) : null,
      el("td", {}, [
        el("span", { text: entry.item }),
        entry.note ? el("span", { class: "note", text: entry.note }) : null,
      ]),
      el("td", { class: "amount", text: entry.amount_display }),
      el("td", { class: "actions" }, [
        el("button", { class: "button link", text: "Edit", onclick: () => startIncomeEdit(entry) }),
        el("button", {
          class: "button link danger",
          text: "Delete",
          onclick: () => removeIncome(entry),
        }),
      ]),
    ])
  );
  return el("table", {}, [el("thead", {}, [head]), el("tbody", {}, rows)]);
}

function incomeFilters() {
  const params = new URLSearchParams();
  const range = $("income-filter-range").value;
  if (range === "month") params.set("month", "this");
  else if (range === "last-month") params.set("month", "last");
  else if (range === "custom") {
    if ($("income-filter-from").value) params.set("from", $("income-filter-from").value);
    if ($("income-filter-to").value) params.set("to", $("income-filter-to").value);
  } else params.set("days", range);
  if ($("income-filter-search").value.trim()) params.set("search", $("income-filter-search").value.trim());
  params.set("category", "Income");
  return params;
}

async function loadIncomeState() {
  const date = $("income-field-date").value || state.today;
  const data = await api(`/api/state?date=${encodeURIComponent(date)}`);
  state.currency = data.currency;
  state.today = data.today;
  $("retention-note").textContent =
    `Keeping ${data.retention_months} months of history · entries before ${data.retention_cutoff} are archived to CSV`;
  $("income-day-total").textContent = `${data.day.income_display} received on ${data.day.date}`;
  $("income-day-label").textContent = data.day.date === data.today ? `today (${data.day.date})` : data.day.date;
  $("income-day-entries").replaceChildren(incomeTable(data.day.income_entries || [], { showDate: false }));
  $("income-month-total").textContent = data.month.income_display + " received";
  $("income-month-label").textContent = `${data.month.label} · ${data.month.start} to ${data.month.end}`;
  $("income-window-total").textContent =
    `${data.window.income_display} between ${data.window.start} and ${data.window.end}`;
  renderTrendInto($("income-trend"), data.window.income_months || []);
}

function renderTrendInto(container, months) {
  if (!container) return;
  if (!months.length) {
    container.replaceChildren(empty("No income yet."));
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

async function loadIncomeHistory() {
  const params = incomeFilters();
  $("export-link").href = `/export.csv?${params.toString()}`;
  const listing = await api(`/api/expenses?${params.toString()}`);
  $("income-history-total").textContent =
    `${listing.income_display || listing.total_display} received · ${listing.expenses.length} entries`;
  $("income-history-entries").replaceChildren(incomeTable(listing.expenses, { showDate: true }));
}

async function refreshIncome() {
  await Promise.all([loadIncomeState(), loadIncomeHistory()]);
}

function startIncomeEdit(entry) {
  $("income-edit-id").value = entry.id;
  $("income-field-date").value = entry.date;
  $("income-field-item").value = entry.item;
  $("income-field-amount").value = (entry.amount_cents / 100).toFixed(2);
  $("income-field-note").value = entry.note || "";
  $("income-submit").textContent = `Save changes to #${entry.id}`;
  $("income-cancel").classList.remove("hidden");
  $("income-field-item").focus();
}

function stopIncomeEdit() {
  $("income-edit-id").value = "";
  $("income-field-item").value = "";
  $("income-field-amount").value = "";
  $("income-field-note").value = "";
  $("income-submit").textContent = "Add income";
  $("income-cancel").classList.add("hidden");
}

async function removeIncome(entry) {
  if (!confirm(`Delete "${entry.item}" (${entry.amount_display}) from ${entry.date}?`)) return;
  await api(`/api/expenses/${entry.id}`, { method: "DELETE" });
  if ($("income-edit-id").value === String(entry.id)) stopIncomeEdit();
  toast("Deleted");
  await refreshIncome();
}

function wireIncomePage() {
  $("personal-income-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      date: $("income-field-date").value,
      item: $("income-field-item").value.trim(),
      amount: $("income-field-amount").value.trim(),
      category: "Income",
      note: $("income-field-note").value.trim(),
    };
    try {
      if ($("income-edit-id").value) {
        await api(`/api/expenses/${$("income-edit-id").value}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        toast("Saved");
        stopIncomeEdit();
      } else {
        const result = await api("/api/expenses", { method: "POST", body: JSON.stringify(payload) });
        toast(`Added ${result.expense.amount_display} income`);
        $("income-field-item").value = "";
        $("income-field-amount").value = "";
        $("income-field-note").value = "";
      }
      $("income-field-item").focus();
      await refreshIncome();
    } catch (error) {
      toast(error.message, true);
    }
  });
  $("income-cancel").addEventListener("click", stopIncomeEdit);
  $("income-field-date").addEventListener("change", () =>
    loadIncomeState().catch((error) => toast(error.message, true))
  );
  $("income-filter-range").addEventListener("change", () => {
    const custom = $("income-filter-range").value === "custom";
    $("income-custom-from-field").classList.toggle("hidden", !custom);
    $("income-custom-to-field").classList.toggle("hidden", !custom);
    loadIncomeHistory().catch((error) => toast(error.message, true));
  });
  [$("income-filter-from"), $("income-filter-to")].forEach((input) =>
    input.addEventListener("change", () => loadIncomeHistory().catch((error) => toast(error.message, true)))
  );
  $("income-filter-search").addEventListener(
    "input",
    debounce(() => loadIncomeHistory().catch((error) => toast(error.message, true)), 250)
  );
}

// ------------------------------------------------------------ statements

const statementState = { lines: [], categories: [] };

function monthValue(offset = 0) {
  const now = new Date();
  const date = new Date(now.getFullYear(), now.getMonth() + offset, 1);
  const month = String(date.getMonth() + 1).padStart(2, "0");
  return `${date.getFullYear()}-${month}`;
}

function lastMonthValue() {
  return monthValue(-1);
}

function thisMonthValue() {
  return monthValue(0);
}

function monthLabelFromValue(value) {
  if (!value) return "this month";
  const [year, month] = value.split("-").map(Number);
  return new Date(year, month - 1, 1).toLocaleString(undefined, { month: "long", year: "numeric" });
}

function fillStatementCategories(selected) {
  const clueSelect = $("clue-category");
  const names = ["SKIP", ...statementState.categories];
  clueSelect.replaceChildren(...names.map((name) => el("option", { value: name, text: name })));
  if (selected && names.includes(selected)) clueSelect.value = selected;
}

function reviewSelect(line) {
  const names = ["", "SKIP", ...statementState.categories];
  const select = el(
    "select",
    { class: "review-category", "data-fp": line.fingerprint },
    names.map((name) =>
      el("option", {
        value: name,
        text: name === "" ? "Pick a category" : name === "SKIP" ? "Skip" : name,
      })
    )
  );
  if (line.category === "SKIP") select.value = "SKIP";
  else if (line.category && statementState.categories.includes(line.category)) select.value = line.category;
  return select;
}

function renderClues(clues) {
  if (!clues.length) {
    $("clues-list").replaceChildren(empty("No clues yet. Add merchant text above as you learn your statements."));
    return;
  }
  $("clues-list").replaceChildren(
    lineTable(
      clues,
      [
        { label: "Contains", value: (row) => row.pattern },
        { label: "Category", value: (row) => (row.skip ? "SKIP" : row.category) },
      ],
      {
        onDelete: async (row) => {
          if (!confirm(`Forget clue "${row.pattern}"?`)) return;
          const result = await api(`/api/statements/clues/${row.id}`, { method: "DELETE" });
          renderClues(result.clues || []);
          toast("Clue forgotten");
        },
      }
    )
  );
}

function renderStatementPreview(data) {
  statementState.lines = data.lines || [];
  statementState.categories = data.categories || statementState.categories;
  fillStatementCategories();
  const counts = data.counts || {};
  $("statements-pill").textContent = data.month && data.month.label ? data.month.label : "Statements";
  $("statement-errors").textContent = (data.errors || []).join(" · ");
  $("statement-summary").classList.remove("hidden");
  $("statement-summary").replaceChildren(
    ...[
      ["Ready", counts.ready || 0],
      ["Need you", counts.review || 0],
      ["Skipped", counts.skip || 0],
      ["Already in", counts.duplicate || 0],
    ].map(([label, value]) =>
      el("div", { class: "stat-card" }, [
        el("span", { class: "label", text: label }),
        el("span", { class: "value", text: String(value) }),
      ])
    )
  );
  if (!statementState.lines.length) {
    $("statement-review").replaceChildren(empty("No transactions in that month."));
    $("statement-actions").classList.add("hidden");
    return;
  }
  const table = el("table", {}, [
    el("thead", {}, [
      el("tr", {}, [
        el("th", { text: "Date" }),
        el("th", { text: "Item" }),
        el("th", { text: "File" }),
        el("th", { class: "amount", text: "Amount" }),
        el("th", { text: "Category" }),
        el("th", { text: "Remember" }),
      ]),
    ]),
    el(
      "tbody",
      {},
      statementState.lines.map((line) => {
        const locked = line.status === "duplicate";
        const skipLocked = line.status === "skip";
        const categoryCell = locked || skipLocked
          ? el("td", { text: line.status === "skip" ? "skip" : line.category || "already in" })
          : el("td", {}, [reviewSelect(line)]);
        const remember = el("input", {
          type: "text",
          value: line.remember || "",
          placeholder: "merchant text",
          maxlength: "80",
          "data-remember": line.fingerprint,
        });
        if (locked) remember.disabled = true;
        return el("tr", { class: `review-row ${line.status === "review" ? "needs" : line.status}` }, [
          el("td", { class: "date", text: line.date }),
          el("td", {}, [
            el("span", { text: line.item }),
            el("span", { class: "review-note", text: line.reason }),
          ]),
          el("td", { class: "date", text: line.source }),
          el("td", { class: "amount", text: line.amount_display }),
          categoryCell,
          el("td", {}, [remember]),
        ]);
      })
    ),
  ]);
  $("statement-review").replaceChildren(table);
  $("statement-actions").classList.remove("hidden");
  $("statement-commit-hint").textContent =
    "The category you pick is remembered for next month. Highlighted rows wait until you choose one. Leave a row blank to ask again.";
}

function collectStatementDecisions(includeDuplicates = false) {
  const items = [];
  for (const line of statementState.lines) {
    if (line.status === "duplicate" && !includeDuplicates) continue;
    const select = document.querySelector(`select.review-category[data-fp="${line.fingerprint}"]`);
    const rememberInput = document.querySelector(`input[data-remember="${line.fingerprint}"]`);
    const remember = (rememberInput ? rememberInput.value.trim() : "") || line.remember || "";
    let category = line.category;
    if (select) category = select.value;
    const skip = line.status === "skip" || category === "SKIP" || category === "skip";
    if (skip) {
      items.push({
        action: "skip",
        fingerprint: line.fingerprint,
        date: line.date,
        item: line.item,
        amount_cents: line.amount_cents,
        category: "SKIP",
        source: line.source,
        remember,
      });
      continue;
    }
    if (!category) continue;
    items.push({
      action: "import",
      fingerprint: line.fingerprint,
      date: line.date,
      item: line.item,
      amount_cents: line.amount_cents,
      category,
      source: line.source,
      remember,
    });
  }
  return items;
}

async function loadClues() {
  const data = await api("/api/statements/clues");
  const categories = await api("/api/categories");
  statementState.categories = categories.categories || [];
  fillStatementCategories();
  renderClues(data.clues || []);
}

function wireStatementsPage() {
  $("statement-month").value = thisMonthValue();
  const drop = $("statement-drop");
  const filesInput = $("statement-files");
  const names = $("statement-file-names");
  const refreshNames = () => {
    const files = [...filesInput.files];
    names.textContent = files.length ? files.map((file) => file.name).join(", ") : "No files chosen";
  };
  filesInput.addEventListener("change", refreshNames);
  ["dragenter", "dragover"].forEach((eventName) =>
    drop.addEventListener(eventName, (event) => {
      event.preventDefault();
      drop.classList.add("drag");
    })
  );
  ["dragleave", "drop"].forEach((eventName) =>
    drop.addEventListener(eventName, (event) => {
      event.preventDefault();
      drop.classList.remove("drag");
    })
  );
  drop.addEventListener("drop", (event) => {
    if (event.dataTransfer && event.dataTransfer.files.length) {
      filesInput.files = event.dataTransfer.files;
      refreshNames();
    }
  });
  $("statement-upload").addEventListener("submit", async (event) => {
    event.preventDefault();
    const files = [...filesInput.files];
    if (!files.length) {
      toast("Choose one or more statement files", true);
      return;
    }
    const body = new FormData();
    body.append("month", $("statement-month").value);
    if ($("statement-replace").checked) body.append("replace", "1");
    files.forEach((file) => body.append("files", file));
    try {
      const response = await fetch("/api/statements/preview", {
        method: "POST",
        headers: { "X-Expense-Tracker": "1" },
        body,
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Could not read statements");
      if (payload.categories) statementState.categories = payload.categories;
      if (payload.clues) renderClues(payload.clues);
      renderStatementPreview(payload);
      toast(`Read ${files.length} file${files.length === 1 ? "" : "s"}`);
    } catch (error) {
      toast(error.message, true);
    }
  });
  $("statement-commit").addEventListener("click", async () => {
    const replace = $("statement-replace").checked;
    const month = $("statement-month").value;
    const items = collectStatementDecisions(replace);
    if (!items.length) {
      toast("Nothing to add — pick categories on the highlighted rows", true);
      return;
    }
    if (replace) {
      const label = monthLabelFromValue(month);
      if (
        !confirm(
          `Erase every personal expense in ${label}, then add these statement rows? Food orders are kept.`
        )
      ) {
        return;
      }
    }
    try {
      const result = await api("/api/statements/commit", {
        method: "POST",
        body: JSON.stringify({ items, replace, month }),
      });
      const erased = result.erased ? ` Erased ${result.erased} existing. ` : " ";
      toast(
        `Imported ${result.imported}, skipped ${result.skipped}, remembered ${result.remembered} clue(s).${erased}`.trim()
      );
      statementState.lines = [];
      $("statement-review").replaceChildren(empty("Imported. Drop next month's statements when they arrive."));
      $("statement-actions").classList.add("hidden");
      $("statement-summary").classList.add("hidden");
      await loadClues();
    } catch (error) {
      toast(error.message, true);
    }
  });
  $("statement-erase").addEventListener("click", async () => {
    const month = $("statement-month").value;
    const label = monthLabelFromValue(month);
    if (!confirm(`Erase every personal expense in ${label}? Food orders are kept. This cannot be undone.`)) {
      return;
    }
    try {
      const result = await api("/api/statements/erase", {
        method: "POST",
        body: JSON.stringify({ month }),
      });
      toast(`Erased ${result.erased} expense(s) for ${result.month.label}`);
    } catch (error) {
      toast(error.message, true);
    }
  });
  $("clue-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const category = $("clue-category").value;
      const result = await api("/api/statements/clues", {
        method: "POST",
        body: JSON.stringify({
          pattern: $("clue-pattern").value.trim(),
          category: category === "SKIP" ? "" : category,
          skip: category === "SKIP",
        }),
      });
      $("clue-pattern").value = "";
      renderClues(result.clues || []);
      toast(`Remembered "${result.clue.pattern}"`);
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
} else if (page === "income") {
  $("income-field-date").value = new Date().toISOString().slice(0, 10);
  $("retention-note").textContent = "Salary and other money in · food-order payments stay on Food orders";
  wireIncomePage();
  refreshIncome()
    .then(() => $("income-field-item").focus())
    .catch((error) => toast(error.message, true));
} else if (page === "orders") {
  $("retention-note").textContent = "Income minus costs, with reserves for rates, ABN, registration and income tax";
  wireOrderPages();
  loadOrderList().catch((error) => toast(error.message, true));
} else if (page === "statements") {
  $("retention-note").textContent = "Drop last month's bank PDFs on the 5th · unclear merchants wait for you";
  wireStatementsPage();
  loadClues().catch((error) => toast(error.message, true));
} else {
  $("retention-note").textContent = "Income, costs, labour hours, profit, rates reserve and income tax for this order";
  wireOrderPages();
  loadOrderDetail(Number(orderMatch[1])).catch((error) => toast(error.message, true));
}
