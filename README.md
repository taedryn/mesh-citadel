# Mesh-Citadel BBS

This project aims to create a MeshCore-connected BBS, heavily inspired
by the Citadel BBS from the 1980s.  This system is lightweight,
designed to run on a solar-powered Raspberry Pi Zero and a low-power
nRF52-based LoRa node running the USB companion firmware via
py-meshcore.

# In Progress

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

There are _definitely_ still bugs and missing features, both in the BBS
logic, and in the MeshCore integration.  The packet-sending system is
marginal, and I've been testing between nodes that are in the same room.
I can only imagine going across the mesh will be worse.

If you log in to the test system (which I'll announce on the mesh, when
it's ready to try out), you may see doubled messages; this is the
system trying to compensate for MeshCore being kinda mostly ok at DMs,
not a bug.

# How to Citadel

If the system is up, send any text to the node as a DM to start things
off.  It will respond with prompts to log in, but the first time, you'll
want to type "new" as your username, to register as a new user.

Once you're registered, a sysop or aide will need to verify you, which
may take time.  Until it's solid enough to leave up full time, I'm the
only sysop/aide, so have patience.

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
file, and run `python main.py`.

It'll spit out a bunch of logs, and you can call it with the `-d` flag
to get a lot more logs.  It sends an advert on startup, and you can't
DM with it until it sees your advert, so you may have to advert before
it'll respond.

If you have it running locally, you can run the `cli_client.py` script
to get a local console that's a little bit like a MeshCore connection.

Always keep in mind, this is _super duper ALPHA quality software._
That means it's riddled with bugs and problems and missing features,
and it'll probably crash and eat your whole message database.  So,
play, have fun, but don't expect this to be a useful system yet.
