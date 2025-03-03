(function() {
    async function fetchTables(locationSlug) {
        const apiUrl = `https://board-gamers.com/api/tables/by-location/${locationSlug}/`;
        try {
            const response = await fetch(apiUrl);
            if (!response.ok) {
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
            const tables = await response.json();
            renderTables(tables);
        } catch (error) {
            console.error("Error fetching tables:", error);
        }
    }

    function renderTables(tables) {
        const container = document.getElementById('board-gamers-tables');
        if (!container) return;

        container.innerHTML = ""; // Pulizia della lista precedente

        if (tables.length === 0) {
            container.innerHTML = "<p class='bg-no-tables'>Nessun tavolo disponibile.</p>";
            return;
        }

        tables.forEach(table => {
            const tableDiv = document.createElement("div");
            tableDiv.classList.add("bg-table");

            tableDiv.innerHTML = `
                <h3 class="bg-title">${table.title}</h3>
                <p class="bg-description">${table.description}</p>
                <p class="bg-info">
                    📍 <span class="bg-location">${table.location_name}</span> | 🕒 
                    <span class="bg-date">${table.date}</span> ${table.time} | 👥 
                    ${table.min_players}-${table.max_players} giocatori
                </p>
                ${table.games.length ? `<p class="bg-games">🎲 Giochi: ${table.games.map(g => g.name).join(', ')}</p>` : ""}
            `;

            container.appendChild(tableDiv);
        });
    }

    // Per caricare automaticamente i tavoli se c'è un div con ID e data-location
    document.addEventListener("DOMContentLoaded", function() {
        const container = document.getElementById("board-gamers-tables");
        if (container && container.dataset.location) {
            fetchTables(container.dataset.location);
        }
    });

})();
