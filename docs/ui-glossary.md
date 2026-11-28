# UI glossary

One word for each concept of the interface, in Italian and in English (the msgids). Only the
words the user reads follow it: the code keeps its names (`Location`, `Event`, `MasterEvent`), and
the URLs (`/locations/`, `/events/`, `/master-events/`, …) don't change.

The names the user reads and the code's names differ for the appointments: an `Event` is a
**gathering** («ritrovo»), a `MasterEvent` is an **event** («evento»).

## Concepts

| Concept (code) | Italian | English | Avoid | Notes |
|---|---|---|---|---|
| `Location` | **Associazione**, plural **Associazioni** | Location | Sede, luogo | The place registered on Board Gamers: association, game library, shop. |
| The viewer's locations (`viewer.my_locations`) | **Le associazioni che frequenti** | | Le tue sedi | Every tie: created, managed, member, pending, followed. The account page of the ones created or managed is «Associazioni che gestisci». |
| Menu entry and index of the locations | **Dove giocare** | Locations | | `{% trans "Locations" context "navigation" %}`. The plain "Locations" msgid is «Associazioni». |
| Where a gathering takes place (`venue_*`) | **Luogo** | Venue | Associazione, when it is not a registered one | A registered location is «Associazione ospitante». |
| `organizer_location` | **Associazione organizzatrice** | Organizing location | | |
| `Network` (national networks) | **Rete nazionale**, plural **Reti nazionali** | National network | Associazione nazionale | |
| Who runs a gathering or an event | **Organizzatore** | Organizer | Owner, creator | |
| `Location.creator` | **Titolare** | Owner | Proprietario | The titolare is one of the gestori. «Trasferisci la titolarità». **Proprietario** is the owner of a game in the ludoteca. |
| `Location.managers`, `Event.managers` | **Gestore**, plural **Gestori** | Manager | Admin | «Solo i gestori» covers the titolare too. |
| `Member` | **Socio** | Member | Associato/a, membro | |
| `Membership` | **Adesione** | Membership | Iscrizione | «Diventa socio», «Richiedi l’adesione», «Le mie adesioni», «Libro soci». |
| Joining a table or registering for a gathering or an event | **Iscriversi**, **iscrizione** | Join, sign up | | Only for tables, gatherings and events, never for membership. |
| `LocationGame` (the games of a location) | **Ludoteca** | Library | Libreria | «Ludoteca dell'associazione organizzatrice». As a kind of venue, write «ludoteca» only in prose. |
| `Event` | **Ritrovo**, plural **Ritrovi** | Gathering | Evento | A gathering of a location, also over several days. Masculine: «il ritrovo», «del ritrovo». |
| `MasterEvent` | **Evento**, plural **Eventi** | Event | Manifestazione, festival | Groups the gatherings of different organizers. Masculine: «l'evento pubblicato». |
| Home page | **Home** | Home | Homepage | |
| `cover` (the image of a location, table, gathering, event) | **Copertina**, in forms «Immagine di copertina» | Cover | | |

## States

| State | Italian |
|---|---|
| Draft | **Bozza** |
| Published | **Pubblicato**, for tables, gatherings and events alike |
| Past tables, gatherings and events | **Passati** («Passate» for activities) |
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
of a location, a gathering or an event, its name for its public page, «Dove giocare» for the
index of the locations.
