# Telegram Mini App — "Prenota un tavolo"

Piano di lavoro per portare la prenotazione dei tavoli dentro Telegram, sul modello di
`t.me/GameNightSestoBot/prenota`.

Stato: **fasi 0-4 implementate**; restano la 5 (bot), la 6 (annuncio
automatico) e la 7 (i18n).

Scostamento dalla fase 3: i bottoni Partecipa/Esci stanno **su ogni card**,
non sul `MainButton`. Il MainButton è unico e globale, quindi ha senso nel
dettaglio (fase 4), non su una lista dove le azioni sono N.

---

## 1. Obiettivo

Un utente apre un link Telegram dal gruppo della sua ludoteca, si apre una modale interna a
Telegram (Mini App) con l'elenco dei **tavoli futuri di quella location**, e — se ha già
collegato l'account Board-Gamers a Telegram — può **prenotarsi / disiscriversi** e
**portare ospiti** senza uscire da Telegram.

### Scope v1 (deciso)

| | |
|---|---|
| Lista tavoli futuri della location | ✅ |
| Join / Leave | ✅ |
| Dettaglio tavolo (descrizione, giocatori, link extra) | ✅ |
| Ospiti (`GuestProfile`) | ✅ |
| Creazione tavolo dalla Mini App | ❌ fuori scope |
| Tavoli legati a un `Event` | ❌ esclusi (hanno il loro flusso sul sito) |
| Notifica nel gruppo a ogni iscrizione | ❌ (solo annuncio alla **creazione** del tavolo) |

---

## 2. Cosa esiste già

- **Bot unico** `TELEGRAM_BOT_TOKEN` / `TELEGRAM_BOT_USERNAME`, webhook in
  `webapp/api/telegram_views.py` con `/setup <token>` e `/tables`.
- **`TelegramGroupConfig`**: `chat_id` (+ `message_thread_id`) → `Location`. La mappa
  gruppo → location esiste già ed è alimentata da `/setup`.
- **Sync account**: `social-auth` backend `telegram` →
  `UserSocialAuth(provider='telegram', uid=<telegram_user_id>)`. È la stessa identità che
  arriva dentro `initData` di una Mini App: **il collegamento account non va reinventato**.
- **Regole di join**: `JoinTableView` (`webapp/views/table_views.py:525`) — email verificata,
  `is_session_active`, `table_join_permission == members_only`, doppio join, posti
  disponibili, `Comment` di sistema `PLAYER_IN:`, warning overlap eventi.
- Pagina **Manage › Telegram** (`locations/location_manage_telegram.html`) con generazione
  token e lista gruppi connessi.

---

## 3. Vincoli Telegram (verificati sulla documentazione)

1. **Il path multi-segmento non esiste.** I Direct Mini App link sono
   `t.me/<bot_username>/<short_name>?startapp=<param>` (oppure
   `tg://resolve?domain=…&appname=…&startapp=…`). `t.me/<bot>/<slug>/tavoli` non è un formato
   valido. Ogni `short_name` va creato a mano in BotFather con `/newapp`.
   → **Decisione: un solo short name, location sempre in `startapp`.**
   Link finale: `https://t.me/board_gamers_bot/join?startapp=<location-slug>`.
   Short name `join`, non `tavoli`: il bot ha già un comando `/tables` che fa
   un'altra cosa (lista testuale nel gruppo), e `join` è la parola che il
   prodotto usa già per questa azione (`join_table`, "Join this table").
   Il charset ammesso da `startapp` (`A-Za-z0-9_-`) è compatibile con `SlugField`.
2. **Un solo URL per short name**, configurato in BotFather. La Mini App è quindi una
   singola pagina che si auto-configura da `start_param`.
3. **Telegram Web incapsula la Mini App in un `<iframe>`.** Django ha
   `X_FRAME_OPTIONS = 'DENY'` di default e `XFrameOptionsMiddleware` è attivo
   (`boardGames/settings.py:51`) → serve `@xframe_options_exempt` sulla view della Mini App,
   altrimenti su desktop si vede una pagina bianca.
4. **Cookie di terze parti inaffidabili** dentro l'iframe di Telegram Web → **non** basiamo
   l'autenticazione sulla sessione Django. Ogni chiamata porta `initData` in un header.
5. **Bottoni `web_app` inline non sono ammessi nei gruppi**, solo in chat privata. Nei gruppi
   si usa un **URL button** verso `https://t.me/board_gamers_bot/join?startapp=<slug>`: apre comunque
   la Mini App.

---

## 4. Architettura

### 4.1 Autenticazione — `initData`

Nuovo modulo `webapp/services/telegram.py` (ci spostiamo anche `_send_message`, oggi
duplicabile):

```python
def validate_init_data(raw: str, max_age=timedelta(hours=24)) -> dict | None
    # data_check_string = campi ordinati "k=v" separati da \n, escluso `hash`
    # secret_key = HMAC_SHA256(key=b"WebAppData", msg=bot_token)
    # confronto con hmac.compare_digest; verifica auth_date
def profile_from_init_data(data: dict) -> UserProfile | None
    # UserSocialAuth.objects.get(provider='telegram', uid=str(data['user']['id']))
```

Decorator `@telegram_miniapp_auth` in `webapp/views/decorators.py`: legge
`X-Telegram-Init-Data`, valida, popola `request.telegram_user` (payload) e
`request.telegram_profile` (`UserProfile` o `None`), risponde 401 se la firma non è valida.

**CSRF**: gli endpoint sono `@csrf_exempt` ma sicuri — l'autorizzazione dipende da un header
custom che un sito terzo non può impostare senza preflight CORS, e il payload è firmato da
Telegram. Il replay è mitigato dal controllo su `auth_date`.

### 4.2 Struttura pagina — single page + JSON API

Una sola pagina HTML (server-rendered per le stringhe statiche i18n), il resto client-side:

```
GET  /telegram/app/                                → shell HTML (xframe exempt, no auth)
GET  /api/telegram/app/bootstrap/                  → {linked, telegram_user, location, tables[]}
GET  /api/telegram/app/tables/<slug>/              → dettaglio
POST /api/telegram/app/tables/<slug>/join/
POST /api/telegram/app/tables/<slug>/leave/
POST /api/telegram/app/tables/<slug>/guests/add/
POST /api/telegram/app/tables/<slug>/guests/remove/
```

Coerente con la convenzione del progetto: **`JsonResponse` puro, niente DRF** (DRF resta
riservato alla API pubblica del widget).

La location si risolve così, in ordine: `initData.start_param` → `?tgWebAppStartParam=` →
errore "location non specificata" con istruzioni.

### 4.3 UI

Look nativo Telegram, **niente Tailwind CDN** (compilazione a runtime + ~100 KB dentro una
webview mobile): ~150 righe di CSS che usano le variabili di tema esposte da Telegram
(`--tg-theme-bg-color`, `--tg-theme-text-color`, `--tg-theme-button-color`, …), così la Mini
App segue automaticamente tema chiaro/scuro dell'utente.

Elementi:
- header compatto con nome + logo location;
- lista raggruppata per giorno: gioco/titolo, ora, `n/max` posti, avatar giocatori;
- tap → dettaglio (stessa pagina, vista sostituita);
- `Telegram.WebApp.MainButton` per l'azione principale ("Prenota" / "Annulla prenotazione");
- `HapticFeedback` sul successo, `showAlert` sugli errori;
- banner sticky per utente non collegato.

### 4.4 Utente non collegato

`bootstrap` ritorna `linked: false` + il nome Telegram. La lista resta visibile in sola
lettura; il bottone "Collega il tuo account" fa
`Telegram.WebApp.openLink('https://<domain>/account/connect/telegram/')` — apre il browser
esterno, dove il flusso OAuth funziona (dentro la webview no).
⚠️ `connect_telegram_page` è `@login_required`: l'utente non loggato finisce sul login e poi
va riportato indietro → usare `?next=` / verificare il redirect post-login.
Al rientro nella Mini App basta un pull-to-refresh: il bootstrap rifà il lookup.

---

## 5. Refactor necessario (il pezzo più importante)

Le regole di join/leave/ospiti oggi vivono **dentro le view**, mischiate a `messages` e
`redirect`. Riscriverle nell'API Telegram significherebbe duplicare 5 controlli di
sicurezza destinati a divergere.

→ Estrarre in `webapp/services/tables.py` funzioni pure, che sollevano un'eccezione
tipizzata (`TableActionError(code, message)`):

```python
join_table(profile, table)          # verified email, session active, members_only,
                                    # doppio join, posti, Comment PLAYER_IN, overlap
leave_table(profile, table)         # + cascade ospiti, Comment PLAYER_OUT
add_guest(profile, table, guest)
remove_guest(profile, table, player)
```

`JoinTableView`, `LeaveTableView`, `AddGuestToTableView`, `RemoveGuestFromTableView`
diventano wrapper sottili che traducono l'eccezione in `messages.error` + redirect; gli
endpoint Telegram la traducono in `{"error": code, "detail": …}`.

**Nessun cambio di comportamento sul sito**: è la garanzia da verificare con i test
esistenti prima di collegare la Mini App.

---

## 6. Lato bot

1. **Comando `/prenota`** (+ alias): nel gruppo configurato risponde con un URL button
   `📅 Prenota un tavolo` → `https://t.me/board_gamers_bot/join?startapp=<location.slug>`.
   Aggiungere lo stesso bottone in coda alla risposta di `/tables`.
2. **`setMyCommands`**: registrare `/tables` e `/prenota` (management command
   `setup_telegram_bot`, sulla falsariga di `setup_ses_template`).
3. **Manage › Telegram**: mostrare il link della Mini App della location con bottone "copia",
   pronto da pinnare nel gruppo o mettere in bio.
4. **Annuncio automatico alla creazione tavolo**: signal `post_save` su `Table` (`created`,
   `event_id is None`, `location` con `TelegramGroupConfig` attive) → messaggio nel gruppo
   (rispettando `message_thread_id`) con il bottone della Mini App.
   ⚠️ Non c'è Celery: la chiamata HTTP a Telegram è dentro la request di creazione tavolo.
   Mitigazione v1: `timeout=3`, `try/except` con log (stesso pattern di `_send_message`), e
   il signal non deve mai far fallire il salvataggio. Se dovesse pesare, il passo successivo
   è una tabella outbox drenata dallo Heroku Scheduler.

---

## 7. Configurazione / prerequisiti

- BotFather: `/setdomain` sul dominio di produzione, poi `/newapp` con short name `join` e
  URL `https://<domain>/telegram/app/`.
- `settings.py`: nessuna nuova variabile obbligatoria (si riusa `TELEGRAM_BOT_TOKEN` /
  `TELEGRAM_BOT_USERNAME`); aggiungere `TELEGRAM_MINIAPP_SHORT_NAME` (default `join`) per
  costruire i link.
- Verificare che il dominio di staging non serva la Mini App con un bot diverso (BotFather
  ammette un solo dominio per bot).

---

## 8. Fasi

| Fase | Contenuto | Esito verificabile |
|---|---|---|
| **0** | `webapp/services/telegram.py`: `validate_init_data`, `profile_from_init_data`, `send_message` condivisa. Test unitari su firma valida / manomessa / scaduta. | test verdi, zero impatto runtime |
| **1** | Refactor §5 in `webapp/services/tables.py` + view web riscritte come wrapper. | i test esistenti passano, sito invariato |
| **2** | Shell `/telegram/app/` (`@xframe_options_exempt`) + `bootstrap` + lista read-only con CSS tema Telegram. | apertura da `t.me/board_gamers_bot/join?startapp=<slug>` mostra i tavoli |
| **3** | Endpoint join/leave + `MainButton`, gestione utente non collegato. | prenotazione end-to-end da Telegram |
| **4** | Dettaglio tavolo + ospiti. | |
| **5** | Bot: `/prenota`, bottone su `/tables`, `setMyCommands`, link in Manage › Telegram. | |
| **6** | Annuncio automatico nuovo tavolo. | |
| **7** | i18n (`preferred_language`, fallback `user.language_code`), `docs/`, test end-to-end. | |

Le fasi 0–3 sono il minimo rilasciabile e possono andare in produzione da sole.

---

## 9. File toccati (previsione)

**Nuovi**
- `webapp/services/telegram.py`
- `webapp/services/tables.py`
- `webapp/views/telegram_app_views.py`
- `webapp/api/telegram_app_api.py`
- `webapp/templates/telegram/miniapp.html`
- `staticFiles/telegram/miniapp.css` + `miniapp.js`
- `webapp/management/commands/setup_telegram_bot.py`
- `webapp/tests/test_telegram_miniapp.py`

**Modificati**
- `webapp/views/table_views.py` (join/leave/guest → wrapper)
- `webapp/api/telegram_views.py` (`/prenota`, bottone su `/tables`, import da services)
- `webapp/urls.py`, `webapp/api/urls.py`
- `webapp/signals.py` (annuncio nuovo tavolo)
- `webapp/templates/locations/location_manage_telegram.html` (link Mini App)
- `boardGames/settings.py` (`TELEGRAM_MINIAPP_SHORT_NAME`)

---

## 10. Rischi e punti aperti

- **Un bot per tutte le location**: chiunque conosca uno slug apre la Mini App di qualsiasi
  location. Accettabile — i tavoli sono già pubblici sul sito — e `members_only` continua a
  bloccare il join. Da confermare che non esistano location "private".
- **Email verificata**: i profili creati via Telegram nascono con `is_email_verified=True`
  (`webapp/pipeline.py`), ma un utente registrato via email non verificata vedrà l'errore.
  Serve un messaggio chiaro dentro la Mini App, non un fallimento muto.
- **`tgWebAppStartParam`**: la fonte primaria è `initData.start_param` letto via JS; il
  fallback su query string va verificato sul campo (Telegram lo passa anche nel fragment).
- **Telegram Desktop vecchie versioni**: `MainButton` e `themeParams` sono supportati da
  Bot API 6.0+; degradare con un bottone HTML normale.
- **Replay di `initData`**: finestra `auth_date` a 24h. Se si vuole stringere, servirebbe un
  nonce lato server — sovradimensionato per la v1.
