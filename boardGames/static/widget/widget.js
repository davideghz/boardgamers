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
            const tableCard = document.createElement("a");
            tableCard.classList.add("bg-card");
            tableCard.href = `https://board-gamers.com/tables/${table.slug}/`;
            tableCard.target = "_blank";
            tableCard.rel = "noopener noreferrer";

            tableCard.innerHTML = `
                <div class="bg-card-header">
                    <h3 class="bg-title">${table.title}</h3>
                    <p class="bg-date-time">${table.date} - ${table.time}</p>
                </div>
                <div class="bg-card-body">
                    <p class="bg-description">${table.description}</p>
                    <p class="bg-info">📍 ${table.location_name} | 👥 ${table.min_players}-${table.max_players} giocatori</p>
                </div>
                <div class="bg-card-footer">
                    ${table.game ? `<p class="bg-games">🎲 Gioco: ${table.game.name}</p>` : "<p class='bg-no-game'>Nessun gioco specificato</p>"}
                </div>
            `;

            container.appendChild(tableCard);
        });
    }

    document.addEventListener("DOMContentLoaded", function() {
        const container = document.getElementById("board-gamers-tables");
        if (container && container.dataset.location) {
            fetchTables(container.dataset.location);
        }
    });

})();
