document.querySelectorAll('[data-event-venue]').forEach((venue) => {
  const options = venue.querySelectorAll('input[type="radio"]');
  const panels = venue.querySelectorAll('[data-venue-fields]');

  function updatePanels() {
    const selected = venue.querySelector('input[type="radio"]:checked')?.value;
    panels.forEach((panel) => {
      const active = panel.dataset.venueFields === selected;
      panel.hidden = panel.disabled = !active;
    });
  }

  options.forEach((option) => option.addEventListener('change', updatePanels));
  updatePanels();
});
