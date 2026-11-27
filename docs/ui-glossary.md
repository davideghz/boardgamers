# UI glossary

One word for each concept in the Italian interface. The English msgids stay as they are, unless
they are ambiguous in English too; the URLs (`/locations/`, `/events/`, …) don't change.

## Concepts

| Concept (code) | Italian | Avoid | Notes |
|---|---|---|---|
| `Location` | **Sede**, plural **Sedi** | Location, locations, luogo | The place registered on Board Gamers: association, game library, shop. |
| Menu entry and index of the locations | **Dove giocare** | Locations | `{% trans "Locations" context "navigation" %}`. The plain "Locations" msgid is «Sedi». |
| Where an event takes place (`venue_*`) | **Luogo** | Sede, when it is not a registered one | A registered location is «Sede ospitante». |
| `organizer_location` | **Sede organizzatrice** | | |
| Who runs an event or a manifestation | **Organizzatore** | Owner, creator | |
| `Location.creator` | **Titolare** | Owner | The titolare is one of the gestori. «Trasferisci la titolarità». **Proprietario** is the owner of a game in the ludoteca. |
| `Location.managers`, `Event.managers` | **Gestore**, plural **Gestori** | Manager, managers, admin | «Solo i gestori» covers the titolare too. |
| `Member` | **Socio** | Associato/a, membro | |
| `Membership` | **Adesione** | Membership, iscrizione | «Diventa socio», «Richiedi l’adesione», «Le mie adesioni», «Libro soci». |
| Joining a table or registering for an event | **Iscriversi**, **iscrizione** | | Only for tables and events, never for membership. |
| `LocationGame` (the games of a location) | **Ludoteca** | Libreria | «Ludoteca della sede organizzatrice». As a kind of venue, write «ludoteca» only in prose. |
| `Event` | **Evento** | | An event of a location, also over several days. |
| `MasterEvent` | **Manifestazione** | | Groups events of different organizers. |
| Home page | **Home** | Homepage | |
| `cover` (the image of a location, table, event, festival) | **Copertina**, in forms «Immagine di copertina» | Cover | |

## States

| State | Italian |
|---|---|
| Draft | **Bozza** |
| Published | **Pubblicato** (feminine for a manifestation: «Pubblicata») |
| Past tables and events | **Passati** («Passate» for activities) |
| Upcoming | **In programma** |
| Open (a table with free seats) | **Aperto** |
| Full | **Completo** |

## Page titles

Views set only the page part of the title, in `meta.title`; `base.html` adds
« – Board-Gamers.com». Parts of a title are joined by an en dash: «Stazioni – Circolo Demo».
Pages built from a model (`as_meta()`) use its name. `test_ui_smoke` checks that the main
pages have their own title.

## Back links

The label of `{% back_link %}` names the page it leads to: «Gestione» for the management index
of a location or an event, the location or event name for its public page, «Dove giocare» for
the index of the locations.
