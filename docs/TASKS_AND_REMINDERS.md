# Task and reminder voice commands — Module 12.7.5

Verification: **837 tests passed in 106.83 seconds** (742 baseline tests plus
95 new lifecycle/voice regression cases). All tests use isolated storage; audio
integration uses mocked device boundaries.

Say `Nova,` before these commands in always-on mode. Text mode accepts the same
commands without the wake phrase. Background task/event observations remain
historical memories: they never create actionable tasks or scheduled reminders.

## Tasks

| Action | Example |
| --- | --- |
| Add | Add a task to finish my project. |
| Review | Show my pending tasks. |
| Next page | Show my pending tasks page 2. |
| Complete | Mark my project task as completed. |
| Complete by ID | Complete task number 3. |
| Delete | Delete my project task. |
| Rename | Rename my project task to finish the API integration. |

Records retain SQLite identifiers such as `task:3` and `reminder:2`; these are
separate namespaces from `passive:3`, notes and confirmed fact keys. Commands also
accept `Complete task:3` or `Delete reminder:2`. Review shows at most three records
per page with bounded previews. Completed tasks are excluded from pending lists.
Completion is idempotent: repeating it on an already completed task changes nothing.

## Reminder creation and review

- Remind me to call Mom tomorrow at 6 PM.
- Remind me to take a break at 4 PM.
- Remind me about the meeting on October 15 at 10 AM.
- Remind me to drink water in 30 minutes.
- Remind me to stretch in 2 hours.
- Remind me to check email on 2027-01-15 at 12:05 AM.
- Show my upcoming reminders.
- Show my upcoming reminders page 2.

`Remind me in 30 minutes` asks for the missing reminder message and saves nothing.
Reminder creation is an explicit scheduling command and does not need an additional
confirmation. Notification delivery still requires the always-on application's
scheduler and functioning speaker. A saved reminder is not proof of live playback.

## Local time and supported date formats

Set `REMINDER_TIMEZONE` to an IANA name in `.env`, for example `Asia/Kolkata`
(the default), `UTC` or `America/New_York`. It is independent of the operating
system timezone. An invalid zone fails clearly during tool initialization.
Windows requires the `tzdata` project dependency; once installed, parsing uses local
data and makes no network requests. Changing the configured zone changes display
and interpretation of new commands, not existing UTC reminder instants.

Calendar syntax is `[today|tomorrow|on DATE] at H[:MM] AM|PM`. `DATE` accepts
`YYYY-MM-DD` or a full English month name and day, optionally a four-digit year
(`October 15`, `October 15 2026`, `October 15, 2026`). A time without a date means
today in the configured zone. A month/day without a year means this local year.
The save response displays the resolved full date, local time and timezone.
Past times are rejected; Nova does not silently roll them into tomorrow or next
year. Numeric slash dates, abbreviated months, weekdays, timezone abbreviations,
24-hour time, missing AM/PM and missing clock times are unsupported.

Relative delays use elapsed UTC minutes/hours, including across daylight-saving
changes. Calendar times in a daylight-saving gap or repeated hour are rejected:
choose another time. Stored timestamps remain timezone-aware UTC. Tests inject a
clock, including the local-day boundary and leap years.

## Reminder changes

- Cancel my reminder to call Mom.
- Delete reminder number 2.
- Snooze my reminder for 10 minutes.
- Snooze reminder number 2 for 1 hour.
- Reschedule my meeting reminder to tomorrow at 11 AM.

Cancel marks a reminder inactive while preserving its record. Delete removes the
record. The existing completion flag represents either delivery or cancellation;
there is no separate delivery-history table. Already inactive cancellation changes
nothing. Due and inactive reminders can be snoozed or rescheduled, reactivating the
same stable ID. Snooze is anchored to the command time, not the later confirmation
time. A proposed time that becomes due before confirmation is rejected. Review
includes pending due reminders with a `due` label, and upcoming ones, but excludes
inactive reminders.

## Confirmation and concurrency

Complete, rename, delete, cancel, snooze and reschedule ask for confirmation.
Use `Nova, Yes`, `Nova, No` or `Nova, Cancel`. An action-specific reply such as
`Yes delete` is also accepted only for that pending action. Compound replies,
`Yeah` and `Go ahead` do not approve these operations. Ordinary fact confirmation
keeps its existing vocabulary. Pending operations expire after 120 seconds, live
only in RAM, and are discarded on restart. An unrelated request cancels the old
operation; a repeated command proposes a new one. Memory, task/reminder and fact
confirmations cannot remain pending together.

Matching first resolves explicit IDs, then an exact title, then literal title-word
matches. It does not use model guesses or unrestricted semantic similarity.
Multiple matches require an ID and make no changes. A bare `my reminder` works
only if there is one matching record; it does not guess the most recent alert.
Transactions compare the complete reviewed row, including a revision counter,
before writing. A changed/deleted record cancels the operation; database failures
roll back. Unrelated tasks, reminders, memories, notes and conversation history
remain unchanged.

The scheduler atomically claims the due record's version before notification.
Competing schedulers and stale due snapshots cannot deliver an active claim.
In-flight delivery prevents user changes; repeat the command after delivery
finishes. A renewable five-minute lease protects notifications waiting in the
audio queue, including long mute waits. Failed/cleanly interrupted delivery releases
the claim for retry. After a process crash, an abandoned claim becomes eligible
after lease expiry. A successful acknowledgment is persisted before later polls.

Exactly-once audible delivery cannot be guaranteed across a crash between playback
and SQLite completion, or database failures that prevent renewal/completion.
Such a reminder may be delivered again after recovery. No claim is made of an
atomic transaction spanning SQLite and physical speaker playback.

## Privacy and limitations

Shared credential protection applies to creation and rename. Legacy credential
contents are hidden from lists/confirmation previews and speech. Operational logs
contain state, record IDs and error categories, not task/reminder messages.
Software mute and accepted passive-work behavior retain their existing semantics.
Task/reminder confirmations do not authenticate a speaker. Logical SQLite deletion
does not securely erase WAL/journal files, backups or storage media.

No recurring reminders, task deadlines, multi-task bulk operations, arbitrary
calendar language or notification history UI are introduced here. Review scans the
local tables; very large archives have not been stress-profiled. Physical Windows
microphone/speaker validation remains a separate manual check. Module 12.8 and
Raspberry Pi deployment are outside this module.

## Manual Windows check

1. Set `REMINDER_TIMEZONE`, start the always-on application and add a task by voice.
2. Review its ID, rename it and confirm; complete it twice and check idempotency.
3. Request deletion, cancel, review again, then repeat and confirm deletion.
4. Create a one-minute reminder; review its local time and hear one notification.
5. Snooze that inactive reminder, confirm and verify one later notification.
6. Create a tomorrow reminder, reschedule/cancel it, and verify persistence on restart.
7. Mute before a reminder becomes due and validate the existing notification/mute
   behavior; confirm muted speech produces no new tasks or memories.
8. Try ambiguous titles and a past time, verifying clarification and no unintended changes.
