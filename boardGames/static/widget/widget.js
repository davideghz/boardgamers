(function() {
    function getLangPrefix(container) {
        // Legge la lingua da data-lang o <html lang>
        const raw = (container?.dataset.lang || document.documentElement.lang || 'it').toLowerCase().trim();
        // Normalizza (es. 'en-US' -> 'en')
        const code = raw.split(/[-_]/)[0];
        // Nessun prefisso per italiano, altrimenti usa /<codice>
        return code === 'it' ? '' : `/${code}`;
    }

    function getLangCode(container) {
        // Legge la lingua da data-lang o <html lang>
        const raw = (container?.dataset.lang || document.documentElement.lang || 'it').toLowerCase().trim();
        return raw;
    }

    function cleanBase(url) {
        return (url || '').replace(/\/+$/, '');
    }

    function joinUrl() {
        const parts = Array.from(arguments)
            .filter(Boolean)
            .map((p, i) => i === 0 ? p.replace(/\/+$/,'') : p.replace(/^\/+|\/+$/g,''));
        if (!parts.length) return '';
        const [first, ...rest] = parts;
        return [first, ...rest].join('/').replace(/^(https?:)\/+/, '$1//');
    }

    async function fetchTables(locationSlug) {
        const container = document.getElementById('board-gamers-tables');
        const apiBase = cleanBase(container?.dataset.apiBase || 'https://board-gamers.com');
        const apiUrl  = joinUrl(apiBase, 'api', 'tables', 'by-location', locationSlug) + '/';

        try {
            const response = await fetch(apiUrl);
            if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
            const tables = await response.json();
            renderTables(tables);
        } catch (error) {
            console.error("Error fetching tables:", error);
        }
    }

    function renderTables(tables) {
        const container = document.getElementById('board-gamers-tables');
        if (!container) return;

        const apiBase  = cleanBase(container?.dataset.apiBase || 'https://board-gamers.com');
        const langPref = getLangPrefix(container); // '' per IT, '/xx' per altre lingue
        const langCode = getLangCode(container);
        const siteRoot = joinUrl(apiBase, langPref); // es. https://board-gamers.com/en

        container.innerHTML = "";

        if (!Array.isArray(tables) || tables.length === 0) {
            container.innerHTML = "<p class='bg-no-tables'>No tables available.</p>";
            return;
        }

        tables.forEach(table => {
            const tableCard = document.createElement("a");
            tableCard.classList.add("bg-card");
            tableCard.href = joinUrl(siteRoot, 'tables', table.slug) + '/';
            tableCard.target = "_blank";
            tableCard.rel = "noopener noreferrer";

            const shortTitle = table.title.length > 65 ? table.title.slice(0, 65).trim() + "…" : table.title;
            const shortDescription = table.description.length > 75 ? table.description.slice(0, 75).trim() + "…" : table.description;

            const date = new Date(`${table.date}T${table.time}`);
            const day = date.toLocaleDateString(`${langCode}`, { day: '2-digit', month: 'short' });
            const time = date.toLocaleTimeString(`${langCode}`, { hour: '2-digit', minute: '2-digit' });

            tableCard.innerHTML = `
            <div style="position: relative;
                        background-image: linear-gradient(to top,
                            rgba(0,0,0,0.8) 0%,
                            rgba(0,0,0,0.3) 40%,
                            rgba(0,0,0,0) 100%),
                            url('${table.cover_url}');
                        background-position: center;
                        background-size: cover;
                        height: 150px;">
                <span class="bg-card-status bg-card-status-${table.status}"
                      style="position: absolute; top: 8px; right: 12px; color: white; font-size: 0.75rem; font-family: sans-serif; padding: 4px 8px; border-radius: 8px;">
                    ${table.status}
                </span>
                <div style="position: absolute; bottom: 8px; left: 12px; color: white; font-weight: bold; text-shadow: 1px 1px 2px rgba(0,0,0,0.6); font-size: 20px;">
                    ${table.game?.name || ""}
                </div>
            </div>

            <div class="bg-card-body">
                <p class="bg-title">${shortTitle}</p>
                <p class="bg-description">${shortDescription}</p>
            </div>

            <div class="bg-card-footer">
                <small>${table.location_name}</small>
            </div>

            <div class="bg-card-footer" style="display: flex; justify-content: space-between; align-items: center;">
                <div>📅 ${day}</div>
                <div>⏰ ${time}</div>
                <div>👾 ${table.current_players}/${table.max_players}</div>
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
