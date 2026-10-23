document.querySelectorAll("[data-progress-width]").forEach((bar) => {
    const width = Number.parseFloat(bar.dataset.progressWidth || "0");
    const clampedWidth = Math.min(Math.max(width, 0), 100);
    bar.style.width = `${clampedWidth}%`;
});
