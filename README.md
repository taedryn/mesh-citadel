# Mesh-Citadel BBS (East Troy BBS fork)

This project aims to create a MeshCore-connected BBS, heavily inspired
by the Citadel BBS from the 1980s.  This system is lightweight,
designed to run on a solar-powered Raspberry Pi Zero and a low-power
nRF52-based LoRa node running the USB companion firmware via
py-meshcore.

## About this fork

This is a fork of [taedryn/mesh-citadel](https://github.com/taedryn/mesh-citadel),
running as **East Troy BBS**. Upstream is inactive and not currently
accepting outside contributions, so rather than let fixes and additions
sit idle, they live here instead. What's changed relative to upstream:

**Bug fixes** (all found by getting the dormant test suite running
again and exercising real code paths against it):
* `Room.delete_room()` crashed unconditionally with a `NameError` any
  time it was actually called.
* `SessionManager.expire_session()` raised `UnboundLocalError` instead
  of cleanly returning `False` for a session that didn't exist.
* `SessionManager.is_expired()` mixed naive and timezone-aware
  datetimes and always raised `TypeError` when called.
* `HelpCommand`'s detailed per-command help (e.g. `H G`) was silently
  inert -- it checked its argument as a dict when it's actually always
  a plain string, so it never matched and always fell back to the
  general menu.
* `Room.get_next_unread_message()` never awaited an async call, so a
  room's first-visit-unread detection didn't work correctly.
* `Room.get_unread_message_ids()` compared `message_id > NULL` in SQL
  (always false), so a room you'd never visited before showed *zero*
  unread messages instead of all of them.

**Test suite**: the suite (131 tests) had drifted heavily out of sync
with the actual code -- 52 tests were failing, including one that
couldn't even be collected. All of it now passes against current
behavior; several tests that covered functionality later removed
(the old dict-based command argument/validation system) were rewritten
to cover what actually exists today instead.

**CI**: added a GitHub Actions workflow that runs the test suite on
every push/PR (there wasn't one before).

**New features**:
* **MQTT packet-telemetry publishing** -- replaces the separate
  `meshcore-packet-capture` observer tool with equivalent
  functionality built directly into the BBS, publishing to MQTT
  brokers (rflab, MeshMapper) using on-device Ed25519-signed JWT auth,
  reusing the BBS's existing live radio connection instead of running
  a second process against the same hardware.
* **Local AI question-answering command** (`A <question>`) -- answers
  questions using a locally-hosted Ollama model (default
  `llama3.2:3b`), replying privately to whoever asked. No external API
  or network dependency, in keeping with this project's own
  resilient/infrastructure-free design goals.
* A `CANCEL` fix so it actually escapes an in-progress workflow
  (previously swallowed as literal input, e.g. as a bogus recipient
  username, with no way out short of a server restart).
* A systemd service unit for running the BBS as a proper background
  service that survives reboots.

# In Progress

Last updated Mon Nov  3 10:38:50 PST 2025

**This is ALPHA software!**  It will fail if you look at it wrong.  Not
quite [_Badtimes_ by Laika](https://genius.com/Laika-badtimes-lyrics)
level, but give that a listen anyway.

I've reached the point where this is Very Nearly A Functional BBS.  The
things that are working right now:

* User registration
* Login
* Room navigation
* Reading messages
* Entering messages
* Sending Mail (private messages)
* Permission system
* MeshCore communication

There are _definitely_ still bugs and missing features, both in the BBS
logic, and in the MeshCore integration.  The basic MeshCore
functionality seems to be about as good as I can get it for the moment,
though my location is in a marginal area for consistent contact.

I've got my system up much of the time now, if you're in the PugetMesh
area, look for adverts from Tae's alpha BBS.  It's still missing a lot
of features, and certainly still has bugs.

# How to Citadel (As a User)

1. Advert
2. Send something via DM
3. Login, or register by typing 'new' as the username
4. Wait for the sysop to verify you
5. Log back in
6. Explore

Once you've completed the registration, a sysop or aide will need
to verify you, which may take time.  Until it's solid enough to
leave up full time, I'm the only sysop/aide, so have patience.

Once you're verified, you'll be dropped in the Lobby, which is what it
sounds like.  You might enjoy running the following commands.  Send the
letter in parens as a packet by itself:

### (N)ew messages

Displays messages in the current room that you haven't seen before.
This currently comes as a flood of messages, but will eventually come
as batches of messages.

### (E)nter message

Enter a message in the current room.  Send as much as you want to, and
then send a single . in a packet by itself to end your message entry.
If you're in the Mail room, you'll be asked for a username to send to.
You'll see other users currently online with the (W)ho command, or you
can find usernames from the name in parens on a message.

### (G)oto next room with new messages

This takes you to the next room that has unread messages.  If there are
no more unread messages, it leaves you in the Lobby.  It should tell
you there are new unread messages if someone's entered something while
you were making the circuit.

### (H)elp

Get a list of commands that are currently available.  This list will be
expanding over time.  You can specify a particular command, to get more
detailed help on that command (eg. send "H G" to get more help on the Goto
command).

### (K)nown rooms

Show a list of rooms.  The character before the room is a minus symbol
(-) if there are no new messages, and an asterisk (\*) if you have
unread messages there.  Use G to go quickly to the next room with
unread messages.

### (C)hange room

This command takes an argument, which is the name of the room you want
to go to.  It's case insensitive, but requires an exact match.  This is
how to get to the Mail room to send a private message to someone.  Send
"C Lobby" to change to the Lobby, for instance, or "C mail" to change
to the Mail room.

### (W)ho's online

This shows you _some_ of the people online.  The system attempts to
respect user privacy.  Basically, if you've posted a message recently,
you show up in the Who list when you're connected.  If you haven't
posted recently (within the last 2 weeks), you _don't_ show up in the
Who list.  Sysops and Aides can see everyone who's logged in, though.

### (.C)reate room

Note the leading period before the C.  This will allow you to create a
new room, which will be placed after the system rooms, if you're in
Lobby or Mail, or after the room you're currently in if you're outside
the system rooms.

# Contributions

I'm not yet ready to integrate others' code into this project.  I have
a boatload of features that aren't implemented yet, or are only roughed
in.  I want to get the codebase into a stable place, where I can hand
it off to others to run, and at that point, I'll start considering pull
requests.

If you find bugs, please do create an Issue on this repo.  I'm sure
there's a ton of stuff I haven't considered as far as breaking things
or things being really weird.  Please include your username, the room
you were in, and what you were trying to do.  The system is not yet
very good at sending errors back to mesh users, so the most likely
outcome is that it just stops responding, right now.

# Design Intent

This project is intentionally anachronistic.  It very specifically
invokes much of the flavor of Citadel, which is something that is
likely to be lost on most users.  For them, it will just be a weird
interface.  For those of us who lived through the BBS era, it will be a
blast from the past, even if it comes by way of a very different form
of telephony than we used back then.

Part of this intentional anachronism is that this BBS is not designed to
connect to the internet.  It is only accessible via the mesh.  This is
part of its charm.  It allows younger users to get a taste of the BBS
experience, and it ensures that conversations are reasonably local
(even more so than in the 80s, when rich people could afford to make
long-distance calls to far-off BBSes).  This is very much in keeping
with the nature of the mesh, and satisfies my goals of having a
resilient, infrastructure-free system which can facilitate
communication both in normal times and in emergencies.

# How to Host a Citadel

I need to write a lot more on this, but the basic idea is, you find a
computer (probably a Linux box -- Raspberry Pi Zero is the current
target system, sorry Windows users), hook up a MeshCore USB Companion
radio to it, run `pip install -r requirements.txt`, update the config.yaml
file, and run `python main.py`.  I like to create a virtual environment
with `python -m venv .mesh-citadel` and then `source
.mesh-citadel/bin/activate`, but that's not necessary, particularly if
you're hosting on a Raspberry Pi that's only ever going to be used for
the BBS.

It'll spit out a bunch of logs, and you can call it with the `-d` flag
to get a _lot_ more logs.  It sends an advert on startup, and you can't
DM with it until it sees your advert, so you will have to advert before
it'll respond.

If you have it running locally, you can run the `cli_client.py` script
to get a local console that's a little bit like a MeshCore connection.

The first user to log in is automatically granted sysop powers, so
be sure you log in (probably with the CLI client) _before_ you put it
on the air.  If anything goes sideways, you can always delete the
citadel.db file to start over.

On the first few runs, when setting things up, I strongly recommend *not*
running with the memory-based database (set `database -> use_memory` to
`false` in your `config.yaml` file), to ensure that the setup changes
are immediately written out to the persistent database.  Once everything
seems to be working right, you can re-enable `use_memory`, which will
noticeably speed up slower machines.

**Running as a service (this fork):** `mesh-citadel.service` in the repo
root is a systemd unit for running the BBS unattended and having it
survive reboots. Install it with:

```bash
sudo cp mesh-citadel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mesh-citadel
```

**MQTT and AI config (this fork):** see the `transport.meshcore.mqtt`
and top-level `ai` sections in `config.yaml` for the packet-telemetry
and local-AI-command settings respectively. Both default to disabled
if left unconfigured. The AI command needs
[Ollama](https://ollama.com) installed and running locally
(`ollama pull llama3.2:3b`, or whatever model you set `ai.model` to).

Always keep in mind, this is _super duper ALPHA quality software._
That means it's riddled with bugs and problems and missing features,
and it'll probably crash and eat your whole message database.  So,
play, have fun, but don't expect this to be a useful system yet.

# A Note on In-Memory Database Use

I recently implemented a feature to hold the database in-memory rather
than accessing it on disk.  This is _much_ faster on a low-power
Raspberry Pi with an SD card, but it comes with important caveats.

1. The BBS process will save the database to disk every so often.
   It will _never_ read from disk except at startup.  If you need to
   manually touch the database, stop the BBS process first.
2. If the BBS crashes, recent changes made (messages written,
   configurations changed, user statuses -- like read message
   pointers, etc) will be lost.
3. If you need to kill the BBS process, use ^C like normal, but wait
   for it to completely terminate.  The DB shutdown (which saves what's
   in memory out to disk) is the last thing to run in the shutdown
   process.
4. As mentioned above, when first setting up the BBS, registering the
   sysop user, creating rooms, etc. don't use the memory database, simply
   to ensure that your changes are saved immediately.

If you're running the BBS on a system with a fast disk, I _highly_
recommend not using the in-memory DB.  Likewise, if you have a big
message DB, I recommend getting a fast disk, like an SSD, and using
that, unless you're certain your DB will fit in RAM.

### Quick DB Size Calculation

At the current config defaults (50 rooms, 300 messages per room), and
guessing an average of 150 characters per message with 50 characters of
overhead per message, a full message DB will only hit about 3 MB in
size, and the other stuff in the database is at most a few kB.  So in
theory even a RPi Zero with 512 MB of memory should be fine.  If your
users are wordy, and we have 500 characters per message on average, the
DB could be 7.5 MB.

Note that each room's messages are in a circular buffer, where the newest
message overwrites the oldest one, so you can count on your maximum
values really being the maximum, and not causing problems in active
rooms (though you'll lose older messages over time).
