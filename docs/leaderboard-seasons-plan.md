# Classifica tavoli + Season — piano di design (bozza, 2026-10-12)

Ripensamento del sistema di classifica del tavolo per supportare più modalità di
gioco, e introduzione delle **season** per Location.

> Stato: **design in bozza, non implementato.** Nessuna riga di codice scritta.

## Situazione attuale

- `Player.position` (default `99` = "non compilata") + `Player.score`. Supporta solo
  il tutti contro tutti.
- Unico punto di scrittura: `update_player_position` in `webapp/api/views.py`.
- Gate: `Game.leaderboard_enabled` (default off, acceso a mano dall'admin; **da eliminare**, vedi §1
  "Senza classifica"); finestra di modifica governata da
  `Table.leaderboard_status` (derivato dal lifecycle phase, vedi `docs/table-lifecycle.md`).
- Statistiche Location (`location_views.py`, pagina location): giochi più giocati,
  top winners per gioco, classifica giocatori a **medaglie** (1°/2°/3° + partite) su
  tutto lo storico.

## Principio: la classifica si compila a partita finita

Le squadre non vanno definite prima di giocare: sono un **dato del risultato**, come
il punteggio. Conseguenza: "ruoli nascosti / traditore" non è un caso speciale, è una
partita a squadre; "1 contro tutti" / "pochi contro molti" sono squadre asimmetriche,
senza modellare l'asimmetria.

## 1. Risultato del tavolo

### Modalità di risultato

```
Game.default_result_mode   suggerimento (default: none)
Table.result_mode          valore effettivo, precompilato dal gioco, modificabile
```

Valori (tre modalità + "senza classifica"):

| Modalità            | Struttura                      | Cosa si inserisce                           |
|---------------------|--------------------------------|---------------------------------------------|
| `ffa` (tutti c. tutti) | ogni giocatore è un lato    | posizione per giocatore (pari merito ok) **oppure** "ha vinto il gioco" |
| `teams`             | gruppi di giocatori            | squadra + posizione della squadra           |
| `coop`              | un solo gruppo vs il gioco     | vinto/perso (+ punteggio facoltativo)       |
| `none` (senza classifica) | nessuna                  | niente (es. giochi di ruolo, partite di prova) |

**Niente modalità semi-cooperativa** (decisione 2026-10-12). I semi-coop (Archipelago,
Legendary, Cutthroat Caverns, Dead of Winter) si compilano come `ffa`: se il gioco è
stato battuto è una classifica normale; se ha vinto il gioco si attiva l'interruttore
**"Ha vinto il gioco: avete perso tutti"** e le posizioni non vengono chieste. Il gioco
può suggerire l'interruttore (es. renderlo visibile in evidenza), ma la modalità è `ffa`.

### Senza classifica (`none`) — sostituisce `Game.leaderboard_enabled` (deciso 2026-10-12)

`leaderboard_enabled` serviva **solo** a escludere i giochi senza classifica: viene eliminato e
assorbito dal valore `none` della modalità.

- **Default di `Game.default_result_mode` = `none`**: si usa in caso di dubbio.
- Gioco con suggerimento `none` (es. gioco di ruolo): il tavolo nasce senza classifica, la sezione
  mostra "Questa partita non prevede una classifica". Autore/manager/superadmin possono
  **"Attiva la classifica"** (parte da `ffa`, con l'avviso ambra della modalità non suggerita).
- Gioco con classifica: un singolo tavolo può scegliere `none` (es. partita di prova/spiegazione)
  con il link **"Questa partita non prevede una classifica"** sotto il selettore (non è un quarto
  pulsante). La scelta si applica subito, senza dati da inserire.
- Cambiare modalità resta un permesso di autore/manager/superadmin: un giocatore non può attivare
  né disattivare la classifica.
- Statistiche: i tavoli `none` contano in "tavoli giocati" e "giochi più giocati", **non** nelle
  classifiche di season.

### Suggerimento automatico da BGG (nuovi import)

All'import da BGG (`services/bgg.py`) si propone `default_result_mode` dai dati BGG:

| Dato BGG                                         | Suggerimento |
|--------------------------------------------------|--------------|
| tipo `rpgitem` (gioco di ruolo)                  | `none`       |
| meccanica "Cooperative Game"                     | `coop`       |
| meccanica "Team-Based Game"                      | `teams`      |
| meccanica "Semi-Cooperative Game"                | `ffa`        |
| tipo `boardgame` senza le meccaniche sopra        | `ffa`        |
| dati mancanti / fetch fallito                    | `none`       |

Note:
- Le meccaniche si riconoscono **per nome** (link `boardgamemechanic` della risposta `/thing`);
  verificare nomi/id reali contro l'API in fase di sviluppo.
- Priorità in caso di più meccaniche: Semi-Cooperative → `ffa` prima di Cooperative (molti semi-coop
  hanno anche il tag Cooperative); poi Cooperative → `coop`; poi Team-Based → `teams`.
- **Coerenza con "none in caso di dubbio"**: BGG non ha un tag "competitivo", quindi `ffa` si deduce
  sempre per esclusione. Applicare alla lettera "nel dubbio none" renderebbe `none` quasi tutti i
  giochi da tavolo, cioè la situazione di oggi. Per questo un `boardgame` BGG senza tag coop/squadre
  diventa `ffa`, e `none` resta per i giochi di ruolo, i dati mancanti e i giochi creati a mano.
- È solo un suggerimento: correggibile dall'admin e sul singolo tavolo.
- Sotto l'editor della classifica, card "Vuoi segnalarci un errore o una modalità suggerita migliore
  per questo gioco? Contattaci": link a `contacts?topic=result-mode&game=<slug>`, che precompila il
  messaggio (IT/EN) con il nome del gioco. Il testo è costruito lato server, mai preso dall'URL.

### Campi

```
Game.default_result_mode   ffa / teams / coop / none   (default none)
Table.result_mode      ffa / teams / coop / none
Table.game_outcome     esito dei giocatori CONTRO IL GIOCO: won / lost / null
                       coop → obbligatorio (won/lost)
                       ffa  → null di norma; lost = "ha vinto il gioco, avete perso tutti"
                       teams → sempre null
Table.coop_score       int null, solo coop (es. Hanabi 0–25)
                       PROPOSTA (da confermare): eliminarlo e ripetere il punteggio di gruppo
                       su Player.score di ogni giocatore, come per le squadre → regola unica
                       "il punteggio sta sempre su Player.score"

Player.team            etichetta/numero gruppo, vuoto in ffa e coop
Player.position        posizione valida per le medaglie (vedi sotto)
                       in teams = posizione DELLA SQUADRA, ripetuta su ogni membro
                       null = non compilata / nessuna medaglia  (pulizia: oggi 99)
Player.score           invariato (diventa inseribile da UI, facoltativo)
```

### `position` è sempre "posizione per le medaglie"

Niente campo separato: è la **UI di compilazione** a scrivere `position` già corretta
per ogni modalità, così oro/argento/bronzo restano `position=1/2/3` e le query
esistenti non cambiano.

| Caso                         | Cosa chiede la UI                      | `position` scritta                         |
|------------------------------|----------------------------------------|--------------------------------------------|
| `ffa`                        | posizione per giocatore                | come inserita (pari merito ok)             |
| `ffa` + ha vinto il gioco    | solo l'interruttore                    | null a tutti                               |
| `teams`                      | squadra + posizione della squadra      | posizione della squadra su ogni membro     |
| `coop` vinto                 | solo vinto/perso                       | 1 a tutti (**vittoria coop = oro**)        |
| `coop` perso                 | solo vinto/perso                       | null a tutti                               |

Costo accettato: quando vince il gioco non si registra l'ordine dei giocatori (non conta comunque).

### Esito normalizzato (salvato su `Player`)

Campo **derivato e persistito**, così le aggregazioni restano lato DB (`Count(filter=...)`):

```
Player.outcome    won / lost / draw / null (non compilata)
```

| Caso                      | `outcome`                                                          |
|---------------------------|--------------------------------------------------------------------|
| `ffa`                     | position 1 → won (pari merito al 1° = tutti won); altri → lost; tutti pari → draw |
| `ffa` + ha vinto il gioco | tutti lost                                                         |
| `teams`                   | squadra in pos. 1 → won; altre → lost (tutte pari → draw)          |
| `coop`                    | `game_outcome` per tutti                                           |

Ricalcolo in **un solo punto**: `Table.recompute_outcomes()`, chiamato in transazione
ogni volta che cambia posizione/squadra/`result_mode`/`game_outcome`.

## 2. Season

```
Season
  location     FK Location
  name         "Autunno 2026"
  start_date
  end_date     null finché attiva
  vincolo:     al massimo una season con end_date null per location (partial unique)
  vincolo:     intervalli di date non sovrapposti per location (validazione)

Table.season   FK Season, null
```

### Assegnazione tavolo → season (opzione A)

- Conta la **data del tavolo** (`table.date`), non la data di compilazione della classifica.
- Il FK `Table.season` è salvato (query + stabilità), valorizzato dalla data.
- Tavoli che contano: `event IS NULL` (no tavoli di eventi), esclusi i tornei, e
  `result_mode != none`.
- **Buchi permessi**: si può chiudere una season senza aprirne un'altra (es. pausa
  estiva). I tavoli nel buco hanno `season = null` e contano solo nello storico.
- **Date modificabili**: modificare start/end di una season riassegna i FK dei tavoli
  interessati (ricalcolo).

### Prima season e "Stagione Zero"

- Location senza season: tutto resta com'è (statistiche su tutto lo storico).
- Alla creazione della **prima** season viene creata automaticamente una season passata
  di default **"Stagione Zero"** (*Season Zero*), da data del primo tavolo a
  `start_date nuova − 1 giorno`, e i tavoli precedenti vi vengono associati.

### Permessi

- Season attiva: comportamento attuale (finestra `leaderboard_status`).
- Season chiuse: classifica modificabile **solo da superadmin e manager della Location**.
- Creazione/chiusura/modifica season: manager della Location (area `/manage/`).

### Ospiti

Gli ospiti (`GuestProfile`) entrano in classifica, aggregati per `guest_profile_id`.
Limite accettato: lo stesso amico portato da due utenti diversi = due identità.
Futuro: profilo ospite **riscattabile** da un utente registrato (merge delle partite).

## 3. Statistiche nella pagina Location

| Blocco                                  | Perimetro                                  |
|-----------------------------------------|--------------------------------------------|
| Giochi più giocati, gamers totali, tavoli giocati | **tutto lo storico**              |
| Classifica giocatori (medaglie)         | **season attiva** + selettore per le precedenti |
| Classifica per gioco (top winners)      | **season attiva** + selettore (v1)          |

Location senza season: classifiche su tutto lo storico, come oggi.

**Ordinamento classifica giocatori** (deciso): oro → argento → bronzo → **partite giocate
(più partite = più in alto)**, come oggi.

### Notifiche

Ai **follower della Location** (`LocationFollower`), stesso canale/pattern di `new_table`:

```
NotificationType.SEASON_STARTED   apertura di una season
NotificationType.SEASON_ENDED     chiusura di una season (link alla classifica finale)
```

**Una sola notifica per azione del manager.** Aprire una season quando ce n'è già una attiva
chiude la precedente, ma si invia **solo `SEASON_STARTED`**, con un riferimento alla season
appena conclusa e un link alla sua classifica finale (es. "È iniziata *Inverno 2027*. *Autunno 2026*
è terminata: guarda la classifica finale"). `SEASON_ENDED` parte solo quando una season viene
chiusa **senza** aprirne un'altra (inizio di un buco, es. pausa estiva).

La creazione automatica della "Stagione Zero" **non** notifica.

## 4. UI di compilazione (decisa 2026-10-12, prototipo in corso)

Approccio **A + D**: drag & drop esteso, nella stessa sezione della pagina tavolo.

- **Selettore modalità** in cima (Tutti contro tutti / Squadre / Cooperativo; pulsanti a larghezza proporzionale al testo, così stanno su una riga anche a 320px), precompilato dal gioco.
  Cambiarlo dopo il salvataggio azzera la classifica, previa conferma.
  La modalità resta **libera** (nessun vincolo per gioco): se si sceglie una modalità diversa da
  quella suggerita compare un **avviso ambra** ben visibile con il pulsante "Usa <suggerita>".
- **Tutti contro tutti**: lista trascinabile (SortableJS come oggi) + pulsante **"="** su ogni riga
  (pari merito con chi sta sopra, ranking 1-1-3) + **punteggio facoltativo** per riga con
  **"Ordina per punteggio"** (crea i pari merito in automatico; opzione "vince il più basso") +
  interruttore **"Ha vinto il gioco: avete perso tutti"**.
- **Squadre**: 1) etichette A/B/+ per giocatore (scorciatoia "1 contro tutti"); 2) blocchi squadra
  trascinabili per l'ordine d'arrivo, con "=" e punteggio facoltativo per squadra.
  Validazione: tutti assegnati, almeno 2 squadre.
- **Coop**: pulsanti grandi Vinto / Perso + punteggio di gruppo facoltativo.
- `Player.score` diventa **inseribile da UI, facoltativo**.
- Maniglia di trascinamento = icona **grip a 6 puntini** (non le due linee di oggi, che si confondevano
  con il pulsante "=" del pari merito).

### Permessi

| Azione                    | Chi                                                              |
|---------------------------|------------------------------------------------------------------|
| Cambiare modalità         | superadmin, autore del tavolo, manager della location            |
| Aggiornare la classifica  | superadmin, autore del tavolo, manager della location, giocatori del tavolo |

(Per le season chiuse vale la restrizione del §2: solo superadmin e manager.)

### Endpoint

Nuovo endpoint unico **"salva risultato"** al posto di `update_player_position`: riceve tutto
insieme e chiama `recompute_outcomes()` una sola volta in transazione.

```json
{ "result_mode": "teams", "game_outcome": null, "coop_score": null,
  "players": [ { "id": 1, "team": "A", "position": 1, "score": 12 }, … ] }
```

### Prototipo

Pagina **`/dummy-table/`** (include anche "Senza classifica" tra le modalità di default del gioco) (pubblica anche in produzione per farla provare agli utenti, `X-Robots-Tag: noindex`;
`static_page_views.dummy_table`,
template `staticpages/dummy_table.html`): stato tutto lato client, pannello per simulare
ruolo / modalità di default del gioco / numero giocatori / ospite, e anteprima del payload.
Da rimuovere quando la UI viene portata nella pagina tavolo reale.

Comportamenti confermati sul prototipo: trascinare una riga le toglie il "=" (il pari merito
non segue chi viene spostato); cambiare modalità azzera squadre, pari merito ed esito coop ma
conserva punteggi e ordine dei giocatori.

## 5. Rilascio in produzione (deciso 2026-10-12)

Requisito: **massima retrocompatibilità, nessun risultato perso o alterato**. Principio:
**prima si aggiunge, poi si cambia, solo alla fine si toglie**. Ogni fase è un deploy separato,
verificato prima di passare alla successiva.

Punti del codice che oggi dipendono da `position=99` / `leaderboard_enabled` (da tenere allineati):
`table_views.py` (detail + `leaderboard_visible`), `tables/_table_leaderboard.html`,
`table_detail.html` e **`events/event_table_detail.html`** (stesso endpoint), `location_views.py`
(statistiche medaglie), `profile_views.py` (vittorie), `api/views.py` (`update_player_position`),
`signals.py`, `services/tables.py`, `services/bgg.py`, `admin.py`.

### Fase 0 · Rete di sicurezza
- Backup prima di ogni rilascio che tocca il DB: `heroku pg:backups:capture -a boardgamers`.
- **Fotografia dei risultati**: `python manage.py leaderboard_snapshot` (JSON su stdout: ogni
  Player con tavolo, utente/ospite, posizione normalizzata 99→null, punteggio) e
  `--compare FILE` (esce con errore se un risultato manca o è cambiato; i nuovi giocatori
  sono solo informativi). Il confronto va rifatto dopo ogni fase.
- **Prova generale in locale su copia di produzione** (ripristino del backup nel DB locale)
  prima di ogni fase che tocca i dati.

### Fase 1 · Solo aggiunte al DB (nessun cambiamento visibile)
Nuovi campi facoltativi/con default + modello `Season`. `position`, 99 e `leaderboard_enabled`
restano intatti; il codice si comporta come oggi.

### Fase 2 · Popolamento nuovi campi (dati vecchi non toccati)
- `Table.result_mode` dei tavoli esistenti **ricavato dai loro dati, non dal gioco**: tavolo con
  posizioni compilate → `ffa` (è stato giocato così), anche se il gioco ora suggerisce coop/squadre.
- `Player.outcome` calcolato dalle posizioni esistenti (99 → null).
- `Game.default_result_mode` caricato da **`webapp/data/game_result_modes.csv`** (versionato, solo
  `slug,mode`, dati pubblici; generato dalla revisione di `leaderboard_modes_prod.csv`, che resta
  fuori da git). Prima del caricamento rivedere le 7 righe "DA VERIFICARE".
- Verifica: `leaderboard_snapshot --compare` = OK.

### Fase 3 · Lettura dai nuovi campi, con fallback
- "Non compilato" = 99 **oppure** null (convivenza dati vecchi/nuovi).
- Visibilità classifica da `result_mode` invece che da `leaderboard_enabled`.
- Visualizzazione dei tavoli già compilati identica.
- **Cambiamento visibile da comunicare**: molti giochi oggi senza classifica (Catan, Scythe…)
  inizieranno a mostrarla; sui tavoli passati comparirà "non compilata" (finestra chiusa,
  nessun dato vecchio alterato).

### Fase 4 · Nuova UI di compilazione
- Endpoint "salva risultato" su pagina tavolo **e** tavolo evento.
- **`update-player-position` resta attivo e compatibile** (PWA / pagine aperte da tempo): imposta
  `ffa` e ricalcola gli esiti.
- Rimozione di `/dummy-table/`.

### Fase 5 · Season (rilascio separato)
Gestione manager, "Stagione Zero" automatica, classifiche Location con selettore, notifiche.
Le Location senza season non cambiano.

### Fase 6 · Pulizia (settimane dopo, a sistema stabile)
Nuovo backup → `position=99` diventa null, eliminazione di `leaderboard_enabled` e del vecchio
endpoint. È l'**unica** fase che modifica dati esistenti: per questo va per ultima.

## Fuori scope

- **Tornei** (`docs/tournaments-plan.md`): restano fuori dalle season.
- Punti normalizzati, ELO, win-rate: scartati per ora, si usa il **conteggio medaglie**.
- Più season attive contemporaneamente per Location.
- Profilo ospite riscattabile (feature futura separata).

## Punti ancora da decidere

- Migrazione `leaderboard_enabled` → `default_result_mode` (definita nel principio, dettagli in sviluppo):
  NON si può mappare "spento" → `none` (nel DB locale Catan, Scythe, Root, Risiko… sono spenti: il flag
  partiva off e quasi nessuno lo accendeva). Regola: acceso → `ffa`; spento con `bgg_code` → comando
  una tantum (management command, fuori dalla migrazione: BGG può essere lento/fallire) che applica
  la tabella "Suggerimento automatico da BGG"; spento senza `bgg_code` → `none`. I tavoli esistenti
  prendono `result_mode` dal gioco.
- Migrazione dati (da definire in fase di sviluppo): `position=99` → null (aggiornare anche `leaderboard_visible` in
  `table_views.py` che oggi testa `!= 99`), backfill di `outcome` sui tavoli esistenti (tutti `ffa`).
