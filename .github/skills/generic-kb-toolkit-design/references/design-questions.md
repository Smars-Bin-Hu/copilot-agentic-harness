# Design questions

Answer each from sample files; write the answer and the file it came from into `TOOLKIT-DESIGN.md`.

## Objects

| Question | Data engineering (SQL Server) | Backend service (Java, C#) | Frontend |
| --- | --- | --- | --- |
| Which kinds of object does a person name? | job, package, stored procedure, table, view | service, controller / endpoint, repository, entity / table, message topic | page / route, component, store, API client |
| Which file defines one, and how is it recognised? | `CREATE PROCEDURE` in `.sql`; `sp_add_job` in a job script; one `.dtsx` per package | a class with `@RestController`, `@Repository`, `@Entity` | a file under `pages/`, a default export |
| What is its name, as people and other code say it? | `Db.dbo.usp_x` (database from the project file) | the class name; an endpoint as `GET /owners/{id}` | the route path; the component name |

## Uses

| Question | Examples |
| --- | --- |
| How is one object used by another in the text? | `EXEC dbo.usp_x`; `INSERT INTO dbo.t`; a field typed with another class; `@GetMapping("/x")` called by `restTemplate.getForObject(".../x")`; `import { X } from` |
| Which kinds of use matter? | `calls`, `runs`, `reads`, `writes`; `uses`, `exposes`, `publishes`, `consumes` |
| Is a use written with the full name, or does it need context (current database, package, base URL)? | `names: sql` fills `dbo` and the database; `names: plain` matches the last part |

## Where work starts

Entry points: what a scheduler, a user or another system starts (`job`, an endpoint, a message listener, a route). They become `entry_types`. With none, objects nothing uses but that use something count as entry points.

**Pick the unit that owns the starts**, not each start: a controller, not each of its endpoints; a job, not each step. `kb split` takes out what many entry points reach as shared; when many entry points share one owner, the owner is taken out and the cut falls apart (seen on spring-petclinic, see `toolkit-example-spring/DESIGN.md`).

## Blind spots

- Known only at run time: dynamic SQL, reflection, injection by configuration, URLs from settings. Mark the object `dynamic`.
- Outside the repositories: scheduler settings, rows of configuration tables, another team's code. Name them.
- Retired code kept in folders (`obsolete/`, `archive/`): `obsolete` globs.

## Production list (for `kb gaps`)

Which read-only query or export lists what runs in production, by the same ids: system catalogues, the scheduler's job list, a deployment manifest, the list of deployed services. Names only. A person runs it; the harness never connects.
