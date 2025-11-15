## 0.7.3 (2025-11-15)

### Fix

- **meshcore-engine**: found and fixed more bugs stemming from the meshcore refactor, primarily in the login workflow

## 0.7.2 (2025-11-15)

### Fix

- **meshcore-transport-engine**: updating several missed calls to the transport engine for correct argument order

## 0.7.1 (2025-11-13)

### Fix

- **message-de-duplication**: modified the de-duplication code to take account of the sent message's timestamp.  changed the dedupe window from 10s to 30s.  added the missing background task to clear out expired dedupe entries every 60s
- **logging**: moved log message containing entire outbound message to the DEBUG queue for user privacy during normal operation

## 0.7.0 (2025-11-12)

### Feat

- **message-playback**: implemented a "stop" command to stop messages mid-flow, utilizing new pure msg_queue send structure for meshcore engine
- **sending-multiple-messages**: started on implementation of a reactive multi-message system which will stop if the user sends a stop command
- **meshcore-transport-engine**: implemented simple watchdog timer to restart the meshcore engine if it stops responding
- **watchdog-timer-system**: partially implemented watchdog timer for the meshcore engine.  watchdog itself seems to be in place, but haven't yet determined best way to feed the watchdog from the meshcore engine
- **ACK-handling,-in-memory-database-handling**: start implementing more intelligent ACK handling for sent messages; BBS will now disconnect a user when an ACK isn't received, undoing whatever action was in-progress.  also made the in-memory database more configurable, and updated the README with information on the in-memory DB
- improved language around automatically timed-out sessions.  fixed bug in logout which left previously logged-in sessions active in the password cache.  added notifications for user validation and new mail to meshcore prompt

### Fix

- **contact-management**: fixed contact count function to properly handle bad result from MC firmware
- tweaked a couple small bugs from the refactor
- **message-ACK-handling**: improved message ACK handling logic; it now disconnects at all sensible points where a failed send should disconnect
- **advert-handling**: updated the advert handler to account for situations where the MC node doesn't return contact information, instead of crashing the MC transport engine

### Refactor

- **message-delivery-to-the-user**: modified the meshcore engine so that all messages sent to the user go into the session manager's msg_queue, instead of being directly sent to the user in the moment
- **meshcore-engine**: refactored the meshcore engine to use separate objects for many of its functions, breaking it up into logical sections that should be easier to work with
