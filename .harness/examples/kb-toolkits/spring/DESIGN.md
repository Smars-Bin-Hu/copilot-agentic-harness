# Toolkit design: spring (sample)

Built by following `/generic-kb-toolkit-design` and `/generic-kb-toolkit-build` on [spring-petclinic](https://github.com/spring-projects/spring-petclinic) (commit `500158f`), to check that the method works outside data engineering. The facts are about that repository; a team replaces them with its own.

## Objects

| Type | Defined in | Recognised by |
| --- | --- | --- |
| controller, service, repository, entity, component, class | `src/main/java/**/*.java` | the annotation before the type (`@Controller`, `@Entity` ...); `extends Repository<X, ...>` (also `Jpa`, `Crud`, `PagingAndSorting`, `ListCrud`) makes a repository |
| endpoint | a controller | `@GetMapping("/x")` and the like, under the class's `@RequestMapping` prefix: `endpoint:GET /owners/{ownerId}` |
| view | `src/main/resources/templates/**/*.html` | the path under `templates/` without `.html`: what a controller returns |
| table | `src/main/resources/db/h2/schema.sql` | `CREATE TABLE` (built-in `regex`, `many`) |

## Uses

`handled_by` (endpoint → controller), `renders` (endpoint → view, from `return "x"`, `new ModelAndView("x")` or a `static final String` constant), `uses` (another type of the project named in the class body: the type of a field or of a local variable, `Type name;` or `Type name = ...`, with the types inside its `<...>`, or of a constructor parameter), `reads` (repository → entity), `maps` (entity → table, `@Table(name = ...)`), `extends`. Names: `plain`.

## Entry points

`entry_types: ["controller"]`, not `endpoint`: a controller owns many endpoints, so with endpoints as entry points every controller is reached from many of them, is taken out as shared, and the cut falls apart. `shared_min: 4` keeps the owner, pet and visit controllers together.

## Rounds

1. 9 of 10 facts: `new ModelAndView("owners/ownerDetails")` not known. Also `welcome.html` at the top of `templates/` was not matched by `templates/**/*.html`: fixed in the harness (`**/` stands for no folder too).
2. 10 of 10. An added fact on a view returned through a constant failed; constants are now read. 11 of 11.

## Blind spots

- Join tables named only in `@JoinTable` (`vet_specialties`) have no use.
- Beans wired by the framework (`@Configuration`, formatters) show as `unused`: the framework calls them.
- HTTP calls to other services are not read (petclinic makes none). A service that calls others needs a `calls` use from its HTTP client.
