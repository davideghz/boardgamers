# Dark Theme — Piano operativo

> Documento di pianificazione. Nessun codice ancora scritto.
> Stato: **da fare** · Effort stimato: **M–L** · Nessun blocco tecnico.

## 0. Contesto tecnico (importante)

La webapp **non usa Bootstrap** (la memoria vecchia era sbagliata): usa **Tailwind CSS via Play CDN**
(`webapp/templates/base.html:42`), con config a runtime nello `<script>` e **colori hardcoded**.

- `darkMode` **non è configurato**; nessuna variante `dark:` esiste oggi (si parte pulito).
- Esistono già token semantici custom (`background/foreground/muted/border/sidebar`), ma **quasi nessun
  template li usa** — si scrive quasi tutto in `slate`/`white` raw.
- Nessun build step: le utility (incluse `dark:`) sono generate a runtime dal DOM. Vantaggio: attivare
  il dark è banale. Vincolo: niente purge/JIT compilata.

### Numeri (base per il lavoro)

| Metrica | Valore |
|---|---|
| Template totali | 98 (66 estendono `base_webapp.html`, l'app shell) |
| Utility di colore totali | ~3.289 |
| Famiglie: slate / white / blue / red / accenti | 2.150 / 387 / 325 / 261 / ~170 |
| Blocchi `<style>` | 11 file |
| Gradienti `linear-gradient` | 19 in 10 file |
| `style="…"` inline | 98 |
| CSS esterni solo-light | flatpickr, select2, intl-tel-input |
| Preferenza tema su `UserProfile` | **assente** (esiste solo `preferred_language`) |
| `<meta theme-color>` PWA | hardcoded `#ffffff` |

## 1. Strategia: token semantici + swap via CSS variables

Non "sprinklare" `dark:` su 3.000 classi. Invece: pochi token-superficie come CSS variables che si
invertono su `.dark`, poi find/replace mirato che collassa lo slate/white raw sui token.
Gli accenti (blue/red/amber/green) restano quasi uguali o con ritocco minimo in dark.

### 1.1 Palette semantica (da definire in `base.html`)

```css
:root {
  --surface:    #ffffff;   /* card, superfici principali        (era bg-white) */
  --surface-2:  #f8fafc;   /* superfici alternate/hover leggeri (era bg-slate-50/100) */
  --surface-3:  #f1f5f9;   /* input, chip                       (era bg-slate-100/200) */
  --elevated:   #0f172a;   /* CTA/sidebar scuri                 (era bg-slate-900) */
  --border:     #e2e8f0;   /* bordi                             (era border-slate-200) */
  --border-2:   #f1f5f9;   /* bordi tenui / divide              (era border-slate-100) */
  --text:       #0f172a;   /* testo primario                    (era text-slate-900) */
  --text-2:     #475569;   /* testo secondario                  (era text-slate-600) */
  --text-muted: #64748b;   /* testo attenuato                   (era text-slate-500/400) */
}
.dark {
  --surface:    #0f172a;
  --surface-2:  #1e293b;
  --surface-3:  #334155;
  --elevated:   #1e293b;   /* su fondo scuro l'"elevato" schiarisce, non scurisce */
  --border:     #334155;
  --border-2:   #1e293b;
  --text:       #f1f5f9;
  --text-2:     #cbd5e1;
  --text-muted: #94a3b8;
}
```

Poi puntare i colori Tailwind custom (già in config) a queste variabili, così `bg-surface`,
`text-body`, `border-default`, ecc. diventano utility usabili nei template.

### 1.2 `darkMode: 'class'` nella `tailwind.config` (`base.html`)

## 2. Persistenza — DECISIONE DA PRENDERE prima della fase 0

| Opz | Cosa | Backend | Note |
|---|---|---|---|
| **A** | `darkMode: 'media'`, segue l'OS | nessuno | niente toggle, più rapido |
| **B** | toggle + `localStorage`, anti-flash inline | nessuno | tema per-device — **consigliata** come primo step |
| **C** | toggle + campo `UserProfile.theme` | migrazione + form + context | cross-device, coerente con `preferred_language` |

Raccomandazione: **B** ora, con struttura pronta per aggiungere **C** dopo se serve.
> ⚠️ Anti-flash: snippet inline nel `<head>` **prima** di ogni render che legge la preferenza e mette
> `.dark` su `<html>` sincrono, altrimenti flash bianco all'avvio.

## 3. Casi speciali (review manuale — NON find/replace)

### 3.1 `bg-slate-900` = superfici scure (70 occorrenze) → `--elevated`
In dark un sidebar/CTA `slate-900` su fondo `slate-900` **sparisce**. Mappare a `--elevated` (che
schiarisce in dark). File principali:
`accounts/account_index.html` (8), `locations/location_manage_telegram.html` (6),
`events/event_program.html` (5), `staticpages/home.html` (3), `base_webapp.html` (3, sidebar),
`accounts/account_edit_profile.html` (3), `locations/location_manage_members.html` (3),
`locations/location_manage_games.html` (3), + coda di ~20 file con 1-2.

### 3.2 Gradienti (19 in 10 file) — ripensare le versioni dark
`events/event_detail.html`, `events/event_table_detail.html`, `games/game_detail.html`,
`locations/location_detail.html`, `staticpages/about.html`, `staticpages/home.html`,
`tables/table_detail.html`, `tags/event_card.html`, `tags/event_table_card.html`, `tags/table_card.html`.
Il gradient blu scuro (`#0f172a→#1e3a5f→#1e40af`) delle card stat/blocchi tavolo funziona già in dark:
verificare solo il contrasto del testo sopra. I gradient chiari vanno riscuriti.

### 3.3 Blocchi `<style>` con hex hardcoded (11 file)
`base.html` (freccia `select` SVG con `#64748b`), `locations/location_calendar.html`,
`locations/location_manage_game_detail.html`, `locations/location_manage_managers.html`,
`locations/location_manage_member_detail.html`, `events/event_manage_locations.html`,
`events/event_manage_managers.html`, `events/event_manage_table_creators.html`,
`tables/table_players.html`, `partials/intl_tel_input.html`.
(NB: `emails/base/base_email_html.html` è email → **escluso**, vedi §5.)

### 3.4 PWA `<meta name="theme-color">`
Renderlo dinamico (due meta con `media="(prefers-color-scheme: …)"` o aggiornamento via JS al toggle).

## 4. Find/replace guidato (fase di massa)

Pattern dominanti e loro mappatura (dal conteggio reale). Eseguire **per pattern**, con verifica visiva:

| Da (raw) | Occorr. | A (token) |
|---|---|---|
| `bg-white` | 218 | superficie |
| `bg-slate-50` / `bg-slate-100` | 32 / 115 | surface-2 / surface-3 |
| `bg-slate-200` | 24 | surface-3 |
| `text-slate-900` / `-800` / `-700` | 278 / 29 / 99 | text |
| `text-slate-600` | 174 | text-2 |
| `text-slate-500` / `-400` | 299 / 287 | text-muted |
| `border-slate-200` / `-300` | 274 / 23 | border |
| `border-slate-100` | 34 | border-2 |
| `divide-slate-100` | 14 | divide token |
| `hover:bg-slate-50` / `-100` | 78 / 29 | hover surface |
| `hover:bg-slate-700` | 57 | hover su elevated (CTA scuri) |
| `hover:border-slate-300` | 46 | hover border |
| `text-white` / `hover:text-white` | 149 / 11 | resta (su superfici scure) — verificare |

Accenti (blue 325, red 261, amber 80, green 58, …): in genere **restano**; se un accento è usato come
sfondo tenue (`bg-blue-50`) valutare `dark:` puntuale.

## 5. Fuori scope

- **Email** (`webapp/templates/emails/*`): dark-mode email è inaffidabile tra client → lasciare com'è.
- Pagine statiche a bassissimo traffico: in coda.

## 6. Librerie 3rd-party (solo-light)

Override CSS mirato sotto `.dark` per: **flatpickr** (`base.html:34`, CDN), **select2** (dal/dal_select2),
**intl-tel-input** (`partials/intl_tel_input.html`). La freccia `select` nativa (SVG in `base.html`) usa
`#64748b`: ok in entrambi, ma valutare schiarirla in dark.

## 7. Fasi & effort

| Fase | Contenuto | Effort |
|---|---|---|
| 0 | `darkMode:'class'`, CSS vars, mapping token custom, anti-flash, toggle | **S** |
| 1 | `base_webapp.html` (sidebar/header/nav) — massimo ritorno visivo | **S/M** |
| 2 | Find/replace guidato §4 su ~66 template + verifica pagina-per-pagina | **L** (il grosso) |
| 3 | Casi speciali §3 (bg-slate-900, gradienti, `<style>`, theme-color) | **M** |
| 4 | Librerie 3rd-party §6 | **S/M** |
| 5 | Rifiniture: contrasto/a11y (WCAG), QA cross-pagina in entrambi i temi | **S** |
| 6 | Persistenza: A≈0 · B=S · C=M (§2) | var. |

**Il costo nascosto più grande è il QA visivo**: ogni pagina va guardata in entrambi i temi.

## 8. Rischi

- **Play CDN**: le `dark:` funzionano a runtime, ma la CDN resta subottimale in prod. Il dark è un buon
  momento per *valutare* il passaggio a Tailwind compilato — **non è un prerequisito**.
- **Flash of light** senza anti-flash inline nel `<head>`.
- **Contrasto**: `text-slate-500` su fondo scuro e gradient scuri vanno verificati (WCAG AA).

## 9. Ordine di esecuzione consigliato

1. Decidere persistenza (§2 → B).
2. Fase 0 + toggle → verificare lo switch su `base_webapp.html`.
3. Fase 1 (app shell) come pilota end-to-end.
4. Fase 2 a blocchi di cartelle (`tables/` → `locations/` → `events/` → `accounts/` → `staticpages/`),
   committando per cartella.
5. Fasi 3-4-5 di consolidamento.
