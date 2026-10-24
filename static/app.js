// ---------- Re-run review button ----------
// Sends a POST with fetch() (no page reload), then loads the new review.
const rerunButton = document.getElementById("rerun-btn");
const statusText = document.getElementById("rerun-status");

if (rerunButton) {
  rerunButton.addEventListener("click", async () => {
    const prId = rerunButton.dataset.prId;

    rerunButton.disabled = true;
    statusText.textContent = "Reviewing… this can take up to a minute.";

    try {
      const response = await fetch(`/api/pr/${prId}/rerun`, { method: "POST" });
      const result = await response.json();

      if (result.ok) {
        statusText.textContent = "Done! Loading the new review…";
        window.location.href = `/pr/${prId}`;
      } else {
        statusText.textContent = `Couldn’t finish: ${result.message}`;
        rerunButton.disabled = false;
      }
    } catch (error) {
      statusText.textContent = "Network problem. Is the server still running?";
      rerunButton.disabled = false;
    }
  });
}

// ---------- Repository filter (only on the repos page, when it has a search box) ----------
const repoFilter = document.getElementById("repo-filter");

if (repoFilter) {
  const cards = document.querySelectorAll(".repo-card");
  const emptyMessage = document.getElementById("repo-filter-empty");

  repoFilter.addEventListener("input", () => {
    const query = repoFilter.value.trim().toLowerCase();
    let visible = 0;

    cards.forEach((card) => {
      const match = card.dataset.name.includes(query);
      card.hidden = !match;
      if (match) visible += 1;
    });

    emptyMessage.hidden = visible > 0;
  });
}

// ---------- Severity filter (only on reviews with many findings) ----------
const filterBar = document.getElementById("severity-filters");

if (filterBar) {
  const chips = filterBar.querySelectorAll(".chip");
  const findings = document.querySelectorAll(".finding");
  let activeFilter = null;

  chips.forEach((chip) => {
    chip.addEventListener("click", () => {
      // Clicking the active badge again clears the filter
      activeFilter = activeFilter === chip.dataset.filter ? null : chip.dataset.filter;

      chips.forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.filter === activeFilter)));
      findings.forEach((f) => {
        f.hidden = activeFilter !== null && f.dataset.severity !== activeFilter;
      });
    });
  });
}
