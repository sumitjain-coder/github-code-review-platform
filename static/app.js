// RE-RUN REVIEW BUTTON
// --------------------
// Clicking the button sends a POST request to our Flask server using
// fetch(), WITHOUT reloading the page. While we wait, we show a
// message. When it finishes, we reload to display the new review.

const rerunButton = document.getElementById("rerun-btn");
const statusText = document.getElementById("rerun-status");

if (rerunButton) {
  rerunButton.addEventListener("click", async () => {
    const prId = rerunButton.dataset.prId;

    rerunButton.disabled = true;
    statusText.textContent = "Reviewing… this can take up to 30 seconds.";

    try {
      const response = await fetch(`/api/pr/${prId}/rerun`, { method: "POST" });
      const result = await response.json();

      if (result.ok) {
        statusText.textContent = "Done! Loading the new review…";
        // Reload so the page shows the newest review
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
