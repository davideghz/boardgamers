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

            // Troncatura descrizione
            const shortDescription = table.description.length > 100
                ? table.description.slice(0, 100).trim() + "…"
                : table.description;

            // Data e ora leggibili
            const date = new Date(`${table.date}T${table.time}`);
            const day = date.toLocaleDateString("en-GB", { day: '2-digit', month: 'short' });
            const time = date.toLocaleTimeString("en-GB", { hour: '2-digit', minute: '2-digit' });


            tableCard.innerHTML = `
            <div style="position: relative;
                        background-image: linear-gradient(to top,
                       rgba(0, 0, 0, 0.8) 0%,
                       rgba(0, 0, 0, 0.3) 40%,
                       rgba(0, 0, 0, 0) 100%),
                       url('https://board-gamers.com/${table.cover_url}');
                       background-position: center;
                       background-size: cover;
                       height: 150px;
            ">
                <span class="bg-card-status-${table.status}"
                  style="
                    position: absolute;
                    top: 8px;
                    right: 8px;
                    color: white;
                    font-size: 0.75rem;
                    font-family: sans-serif;
                    padding: 4px 8px;
                    border-radius: 8px;
                ">${table.status}</span>
                <div style="
                    position: absolute;
                    bottom: 8px;
                    left: 8px;
                    color: white;
                    font-weight: bold;
                    text-shadow: 1px 1px 2px rgba(0,0,0,0.6);
                    font-size: 20px;
                ">
                    ${table.game?.name || ""}
                </div>
            </div>

            <div class="bg-card-body">
                <h3 class="bg-title">${table.title}</h3>
                <p class="bg-description">${shortDescription}</p>
            </div>

            <div class="bg-card-footer" style="display: flex; justify-content: space-between; align-items: center;">
                <div>📅 ${day}</div>
                <div>⏰ ${time}</div>
                <div>👥 ${table.min_players}/${table.max_players}</div>
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
