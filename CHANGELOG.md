## Unreleased

### Feat

- **ACK-handling,-in-memory-database-handling**: start implementing more intelligent ACK handling for sent messages; BBS will now disconnect a user when an ACK isn't received, undoing whatever action was in-progress.  also made the in-memory database more configurable, and updated the README with information on the in-memory DB
- improved language around automatically timed-out sessions.  fixed bug in logout which left previously logged-in sessions active in the password cache.  added notifications for user validation and new mail to meshcore prompt

### Fix

- **advert-handling**: updated the advert handler to account for situations where the MC node doesn't return contact information, instead of crashing the MC transport engine
