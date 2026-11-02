# Calendar date ranges for controller deployment

Calendar field review now checks each proposed DateRange endpoint before any
fresh controller read or plan allocation. Each endpoint must be a fully specified
real date, including its matching weekday, or wholly unspecified in all four
native fields. A wildcard year with a specific month/day, an unspecified weekday
on an otherwise specific date, and special month/day patterns are not specific
range endpoints. A concrete start must not follow its concrete end.

The standard allows an unspecified start, end or both endpoints. Individual
Date entries retain their distinct date-pattern choices; WeekNDay retains its
separate revision checks. These forms are not silently converted or inferred from
the current computer or controller clock. This guard does not simulate calendar
evaluation or certify a manufacturer's acceptance of every permitted form.

The distinction follows the specific/unspecified date and DateRange rules in
[ASHRAE 135-2008 Addendum ac, clauses 3.2 and 12](https://bacnet.org/wp-content/uploads/sites/4/2022/08/Add-135-2008ac.pdf).
Johnson Controls also documents fully specified range dates, matching weekdays
and wholly unspecified endpoints in
[Metasys 14 Help: Wildcards – Date Range](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Metasys-Site-Management-Portal-Help/14.0/Insert-Menu/Field-Point/Calendar-Object/Scheduling/Scheduling-Concepts/Dates-Calendar-Entry-and-Exception-Schedule/Wildcards-Date-Range).

## Local work and old evidence

Existing captured bytes and local encoding reviews remain readable and
exportable, including older partial range patterns. Their encoding proof does
not supply controller-write authority. The editor explains the stronger field
requirement beside range endpoints; an invalid proposed replacement receives an
error before fresh reads, a token or an intent. Its raw text remains available
through task navigation for correction or exact local export.

An unchanged legacy value can still receive a fresh **no_change** observation.
That response constructs no write request and provides no token. Replacing an
older invalid range with qualified dates or removing it remains possible; the
original source is preserved independently.

Request encoding rechecks new range admission before a changed value can be
dispatched. Existing one-use reviews, route/source checks, request bounds,
durable uncertainty and one-attempt transfer behavior remain intact. No retry,
clock inference, automatic date repair or alternate write route is added.

Historical receipt readback remains read-only. It can compare an older recorded
replacement with actual current bytes without granting a new write or rewriting
the original receipt. Matching those bytes does not retrospectively qualify the
old range semantics. Local draft rules, Calendar write profile/rules hashes and
receipt formats remain unchanged, retaining their source and recovery bindings.

## Qualification

Owned direct/routed UDP cases cover early refusal with zero extra field reads,
no tokens/intents, exact source preservation, fully specified/open-ended/all-
unspecified ranges, leap dates, literal service-15 bytes, one dispatch and
independent readback. Browser cases preserve and export an invalid local range,
show refusal with zero added reads/writes, navigate away and return, then repair
the endpoints and apply the exact reviewed range once. Existing mixed-choice
cases now use explicit matching weekdays instead of wildcard range weekdays.
Phone review also exposed a table-caption sizing issue. One scoped mobile rule
keeps the Calendar caption readable while retaining the existing stacked form;
the other styles and desktop layout remain unchanged.

The actual prior installed package supplies separate historical-receipt
compatibility evidence against an authored peer. The new installed reader
reconciles that original receipt without another write or altered journal bytes.
No site controllers or Bluetooth are involved. General exception/context/link
editing, schedule evaluation, native CAF compilation and physical acceptance
remain separate; SCH-01–SCH-03 stay partial.
