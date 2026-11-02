# Explicit matching weekday assistance

Calendar date fields and Schedule exception date fields now offer **Set weekday to
Monday**, or the matching day for the entered civil date. Choose the action to
change that date's weekday. Merely entering a date, opening a source or changing
a different field never sets the weekday automatically.

The action is available for a specific, valid year from 1900 through 2154, month
from 1 through 12 and real day of that month. Gregorian leap-year rules include
2000 as a leap year, and exclude 1900 and 2100. An already matching weekday needs
no change. Wildcard years, odd/even month patterns, last/odd/even day patterns,
impossible dates and unfinished text leave the action unavailable and stay intact.
WeekNDay patterns keep their separate controls and meaning.

Each DateRange endpoint has its own action. Setting the start weekday leaves the
end, other date fields, event order, priority and all other entries unchanged.
The result uses a civil Gregorian weekday calculation; it reads no current
computer/controller clock and infers no timezone, DST policy or schedule result.

The shared controls work within the existing Calendar and Schedule exception
editors after either controller or local CAF/graph entry. Raw source-specific
drafts remain in their existing workspaces. An explicit changed weekday uses the
normal draft-edit path: pending encoding reviews, exports and field reviews retire,
and another review is required. This action grants no transfer authority and
sends no field request. Existing native validation, source capture bytes, profile
rules, one-use field reviews and durable receipts remain unchanged.

The [Calendar DateRange rules](native-calendar-date-ranges.md) explain why specific
range endpoints require their matching weekday. The helper supplies a deliberate
editing aid; it does not relax those rules or silently repair original evidence.
The broader SCH-01–SCH-03 roadmap retains context/link editing, execution/timezone
semantics, native CAF integration and physical acceptance work.
