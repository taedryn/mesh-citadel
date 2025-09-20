# PROMPT INTRODUCTION

i would like to consult with you on a new project i'd like to work on.
this document describes it in the best detail i can think of, but it's
very important that you ask me clarifying questions at every step,
to ensure that we're making the highest quality software possible.
always follow the best standards possible for code quality, including
PEP8, and always suggest well-known patterns to solve the problems that
will be uncovered in this process.

# OVERVIEW

the name of this project is Mesh-Citadel.  the system will be a bulletin
board system, but designed in such a way that the protocol layer will
intially communicate with users via a MeshCore USB companion.  the look
and feel will be inspired by the Citadel BBS system from the 1980s.
the goal is to produce a small, efficient message-sharing system which
can be easily and conveniently accessed over a low-bandwidth connection
by multiple concurrent users.

the system will be written in python, in strict adherence to PEP8
standards, utilizing a minimal number of external modules and libraries.
it will run on a raspberry pi zero with minimal resources, and will
utilize solar power, so power efficiency is important.  the first
targeted communication protocol will utilize a MeshCore USB companion
connected by serial port to the pi.  it will use SQLite databases, with
enough abstraction that Postgres or MySQL could be swapped in later.
depending on design choices yet to be made, it may make sense to keep
separate databases, or multiple tables in a single database.  my general
preference is for a single database.

because meshcore communication is slowed considerably by its transit
time across the mesh, response times under about 5 seconds are acceptable
for this system, though we should strive for the best response times we
can without creating undue complexity, or requiring higher-performance
hardware.

in order to avoid scope creep, this project is currently limited to
creating python code and SQL suitable for creating a bulletin board
system similar to the capabilities of a mulit-line Citadel BBS, and the
python necessary for this to work over MeshCore.  other capabilities
and features should be avoided.

this project will proceed in small phases, with all code to be reviewed
and approved by a human.  appropriate tests must be created alongside
code, and a test-driven development approach would be well suited to
this project.  in tests, avoid the mindset that every aspect of the
code must be under test, if doing so would result in very complex or
fragile tests.  we want the tests, just like the code itself, to be
flexible where possible, and as lightweight as possible.

as much as is possible, each module or manager should have a clean
separation of concerns to simplify testing and reasoning about code
execution: the User object only concerns itself with a single user, the
MessageManager only deals with messages, not rooms, the Config
singleton only parses and dispenses configuration information, and so
on, for all the modules in the system.  where concerns are mixed, the
module which needs a service from an external module should use that
module's API.  direct database access outside a module's main area of
concern is to be avoided wherever possible.

security is important to this project, but it should be considered
carefully against the implicit security of MeshCore.  striving for
security beyond that provided by the underlying protocol is wasted effort.
we can reasonably assume that the computer running this code will
be physically secure, but care should be taken that the over-the-air
interface into our BBS is resistant to attacks, such as SQL injection,
buffer overflow via unusual character encoding (MeshCore messages are
limited in length, so "way too much data" isn't a likely attack vector),
or similar means.  security testing must be part of the tests written
for this code.

an important goal of this project is that it should operate completely
independent of an internet connection.  although the system may have
access at some times, it must be able to operate without it.  features
which require internet access must be secondary to the system.

# CODING STANDARDS

always follow PEP8, and in particular, never catch Exception unless
it's absolutely necessary.  always catch specific exceptions. code
inside try blocks should be only the code we expect to throw
exceptions, nothing more.  this project follows the pattern of
instantiating objects in the entrypoint, and then passing objects to
other functions and objects.  for instance, the config object should be
passed in, rather than instantiated within a separate module.  this
helps simplify testing, and makes it clear what each module depends
upon.

# UI STANDARDS

the nature of mesh communications is that a all communications are
packet-based.  packets are limited to 184 characters or less.
this differs from the modems and direct communications originally used by
Citadel systems, which were more interactive, so we will need to adopt
some different UI conventions.

* where the original Citadel would have used a CR, use a single period (.)
* all interactions scoped with the understanding of USB companion packet
  length
* expect that long output will be chunked by the transport layer

# ARCHITECTURE

the software architecture is split into multiple conceptual domains.
all aspects of the system should log significant events.  entering a
message doesn't count as a significant event, since we have the
timestamped message already.  each domain should be specific, and
self-contained to the extent possible, dealing with its own data and
functionality, and making calls into other domains where necessary.
the user module shouldn't deal with authentication, and the rooms
module shouldn't be directly dealing with messages.

## BBS DOMAIN

the most important domain is the bbs logic.  this will handle receiving
parsed commands from the protocol layer, and performing actions based
on those commands.  it will depend on several different self-contained
manager subsystems.

these subsystems will manage:

* rooms
* authentication and user management
* connected sessions
* messages
* database access
* user interaction
* configuration

the bbs domain is agnostic about the protocol layer, with the intention
that any protocol may be added later.

### Rooms Subsystem

citadel boards are organized into sequential rooms.  each room has a name
and a set of messages associated with it, and we will need to keep track
of a last-read marker for the user, per-room.  it will be possible to
read messages in some rooms and not others on a given visit.  for now,
there is a single layer of rooms, but a future improvement (not to be
implemented now) might be to have floors as an organizing unit for rooms.
rooms also have a description associated with them.  rooms always appear
in the same order, and the order should be editable and selectable upon
room creation.

the rooms system is solely responsible for handling the relationship
between messages and rooms, utilizing the messages system to post,
read, and delete messages, but handling the room association of those
messages itself.

the rooms system should track the following data in a database:

* room id (integer)
* room name
* description
* last-read message per user
* messages in the room
* room state (read-only or read-write)

this list of information to track does not constitute a single table in
a database.  rather, we should use the relational features of SQL to
link from one table to another where appropriate.  the rooms manager
should utilize the User, MessageManager, and Config objects (and any
others which end up being needed) where appropriate, to enforce the
separation of concerns.

the rooms system should be able to perform the following actions:

* report a room id given a name
* report a room name given an id
* report the last-read message id given a username
* report a room's description
* deliver the next message given a username (automatically updating the
  user's last-read marker)
* create a room
* update a room's name
* update a room's description
* update a room's state
* delete a room (which also deletes messages associated with a room)

in the case where a user's last-read message has been deleted, it
should automatically default to the next message after the one which
has been deleted.

the following rooms must exist, and can't be deleted:

* Lobby (name can be changed via config file)
* Mail
* Aides

### Users Subsystem

the users system maintains knowledge about users.  it doesn't deal with
authentication or authorization directly, though it provides
information that may be used in those systems.

users will be stored in a database, which includes the following
information:

* username
* display name
* hashed password
* password salt
* last login
* user permission level
* blocked users

passwords must be stored in a one-way hash which is secure, with a
secondary goal of being computationally lightweight.  display name will
default to username, if one is not specified.

the users system should be able to provide the following functions:

* update a user's password
* update a user's display name
* register a new user
* update a user's permission level
* report a user's permission level
* add someone to the user's block list
* remove someone from the block list

#### User Blocking

the system should allow users to block other users.  this would have
the effect of preventing the blocked user from seeing the messages of
the person who blocked them, without notifying the user who's been
blocked.  if a blocked user sends a private message to the user who
blocked them, the message will be recorded as normal, but the blocking
user won't receive a notification, and won't see the message in their
PM list unless they unblock the user.  users who have aide
or sysop access cannot be blocked, and cannot block anyone themselves.

### Authorization/Authentication Subsystem

the authx subsystem will maintain knowledge and methods for authenticating
and authorizing users.  authentication will involve a username and
password combination.  it most likely won't store any data directly,
but rather will leverage other systems to provide data, with which it
will make decisions and give answers.  this system should be able to:

* log a user in with a username and password
* log a user out
* report whether a user is logged in or not
* validate a user's permission to perform an action
* maintain the map of which actions are allowed under which permission
  level
* handle a single permission level, but be expandable so a user may
  have multiple permissions in the future

#### Permissions

the system will have the following permission levels:

* unverified -- basically no access
* twit -- limited access
* user -- normal access
* aide -- moderator access
* sysop -- all permissions

the system will also maintain a list of actions in the config file, and
which permission levels allow which actions.  we will certainly want to
keep track of the following actions, in relationship to permission
levels:

* post messages
* post messages in a specific room
* post private messages
* read all messages
* read messages in a specific room
* see other users' last login time and currently logged-in state
* create new rooms
* delete own messages
* delete others' messages
* edit rooms
* block other users
* modify other users' permission level

### Sessions Subsystem

the sessions system will track connected users.  because of the
multi-connection nature of MeshCore, we will need to track these
sessions to understand the user's current state, rather than being able
to depend on a single connection as the original citadel system did.
sessions will be stored in a database, which includes the following
information:

* username
* session start time
* last activity time
* current room
* current session state (idle, or entering a message)

the sessions system will need to be able to perform the following
actions.  all actions should be indexed on username.

* add a new session
* remove an existing session
* report a current session's state (idle/entering message)
* report a current session's room
* automatically time-out a user who has been inactive too long

### Messages Subsystem

messages in a citadel BBS are in a circular buffer, so there is a set
limit to the number of messages in a room, and a new message overwrites
the oldest message.  this saves storage, and honors the low-bandwidth,
resource-constrained nature of old BBSes.  the messages system is only
concerned with message handling, and leaves the room:message
association and handling to the rooms system.  each message includes
metadata, as described below.  the message system should track the
following information:

* message id
* message sender (by username)
* message recipient (for private messages)
* message contents
* timestamp

the message system should be able to perform the following actions:

* given an id, return the message contents as a data structure
* create a new message
* delete a message

messages should be transmitted to the transport layer as a data
structure, and contain whether a sender is blocked or not, though it
will be the responsibility of the transport layer to decide how to act
on this information.  some will simply not display it, some will show
it with some kind of obscuring technique, some will choose to display
that a message from a blocked sender is not being displayed.

deleted messages, whether deleted by the sender or an aide/sysop,
should have their contents completely removed, without any attempt to
save a backup.  there should be two levels of message deletion: if a
user still exists, and the room still exists, a deleted message should
just contains the text "[deleted]" but otherwise remain in place, with
sender and timestamp intact.  if a room is deleted, the messages
associated with that room should be completely removed from the
messages table.  the message manager should provide two different
message-delete functions, a soft delete which leaves the [deleted]
marker behind, and a hard delete which completely removes the message
from the system.

#### Private Messages

private messages are a special form of message, which contains a
recipient, and may only be sent and read in the Mail room.  private
messages may only be read by the recipient (this means the sysop also
can't read private messages which aren't addressed to them).  they
should still be stored in plaintext, and the help text for new users
should make it clear that private messages are accessible to the sysop
via the database if necessary.

### Database Subsystem

the database system should manage database connections, primarily to
ensure that there's a single point of contact for the database(s).  it
must be thread-safe, and should lock access, so there's no chance of
simultaneous modification (if this isn't already a feature of the
database engine).  it should provide an interface for other systems in
the BBS layer to execute arbitrary SQL.

the database system doesn't need to keep track of any information in a
database, itself, but it should provide the following services:

* open the database(s) on instantiation
* lock database access automatically on write
* queue write operations which occur during lock
* execute a given SQL statement/query
* report number of queued requests

write requests which arrive while the database is already locked for
write will be queued, and processed in the background, so that calling
code may be reasonably assured that any write call will be processed no
matter the system load.  read calls which occur while the database is
locked should be added to the queue, and returned in the order of
arrival, interleaved with write calls, so that a given read receives
data which was current as of when it was made.

### User Interaction Subsystem

the interaction system handles actual interactions with the user, in a
split fashion -- the presentation of information to the user, and
reception of commands and message contents from the user will be
handled in the transport protocol layer, but the UI system should
execute user commands once they're parsed and sanitized by the protocol
layer.  it should include the ability to give the user hints and menus
if requested, as well as manage entering messages.  the UI system
shouldn't need to store much in the database (this is up for
discussion), but should provide the following services:

* execute user actions
* accept message input interaction
* provide a menu on request
* send output to the protocol layer as data structures
* interact with other subsystems to execute user actions

the command structure of a citadel BBS is based on single-charater
commands, which sometimes take an argument.  commands are not case
sensitive.  the commands we will implement are as follows:

G - Go to the next room (advances to the next room in the room list
which has unread messages)
E - Enter a new message (compose and post a message to the current room)
R - Read messages in the current room (read a specific message if ID
provided)
N - Read new messages since last visit
L - List rooms (see the available rooms)
I - Ignore or unignore current room
Q - Quit or log off
S - Scan messages (shows message headers or summaries)
C - Change rooms (choose a room by name or number)
H - Help (display command help)
M - Mail (go to the Mail room to send/receive private messages)
W - Who’s online (list active users)
D - Delete a message
B - Block or unblock another user

in addition, we will have some dot commands for actions which
are less common, or more associated with administration than daily use
of the board:

.C - create a new room
.ER - edit a room's characteristics
.EU - edit a user's characteristics
.FF - fast-forward to the latest message in a room

some commands will take arguments if they're provided -- for instance,
the E command will take the new message to be entered after a space
character, or the .EU command will take a username/display name.  if a
command needs further input, it will issue a prompt for what's needed.

### Configuration Subsystem

this system should be fairly simple, but it needs to provide reasonable
defaults for config options, read a config file (probably YAML format),
and override options with environment variables.  it should be a
singleton object.  at least the following options should be available
in the config file, though there are most likely others we will want to
track as well:

* bbs
** system name
** maximum messages per room (0 for unlimited on all limit options)
** maximum number of rooms
** maximum number of Mail messages per user
** maximum number of users
** starting room
* authentication
** session inactivity timeout
** max password length
** max username length
* transport
** serial port
** baud rate
* database
** path to db file(s)
* logging
** default log level
** log file path

## TRANSPORT DOMAIN

the transport doamin focuses on sending data to and from the user,
according to how they are connected to the BBS.  for our purposes, we will
focus only on MeshCore, but the transport domain should be created in such
a way that adding new transport protocols is relatively straightforward.

the transport layer is concerned with parsing incoming commands and
data and passing it to the BBS, and presenting BBS output to the user.
it also facilitates the protocols necessary to communicate using the
specific transport in use.

### MeshCore Room Server Protocol

we will use a MeshCore room server node as our communication method.
this comes with specific communications protools, and will be connected
via a serial connection over Bluetooth, connected through the
serial_asyncio module in python.  note that this means the entire
package must be set up for async operations.  because of name ambiguity,
please refer to this as the meshcore section, and leave the term "room"
to be used by the BBS layer.

the meshcore protocol will need to be asynchronous, and react to
incoming messages as they occur.  i don't expect the performance of
a single-threaded application to cause bottlenecks given the traffic
volume anticipated (on the order of 10-20 users accessing the system
per hour, at peak), though we should scale things such that hundreds
of users accessing the system at once is possible, even if it's laggy.
ideally the system will have a limited awareness of response lags, and
we can limit connections if we exceed parameters set in the config file.

for the meshcore protocol, we will not expect users to supply a username.
rather, their node ID, which is unique per network node, will act as
their username for BBS purposes.  therefore, a login command from a
MeshCore node would only need to include a password, with the node ID
wrapped in the login instruction to the BBS layer.

### Command Line Interface

i would like to develop a CLI which allows a user logged into the host
system to interact with the BBS as if it were over the mesh.  this would
be at the same protocol level as MeshCore, and would present a similar
interface.  this would be used for manual testing, as well as interacting
with the system as a regular user.

## EXTERNAL SYSTEMS

we will need a number of external systems and scripts to support this BBS.

### Administration Interface

a CLI which allows for administration of the BBS will be necessary.
this would perform functions like reporting on system usage and limits
(disk usage, database usage, CPU usage, etc.), and adjusting configurable
options on the fly (although this might be as simple as signaling the
running system to reload its config file).  user administration might
also be performed with this CLI.  # FUTURE CONSIDERATIONS

everything in this section represents information about possible future
paths for the Mesh-Citadel system, not instructions to build these
features.  knowledge of these intentions may, however, inform how we
structure the first iteration of our system.

## NETWORKING

multiple Mesh-Citadel systems may wish to link together to share messages.
if this happens, it will be on a per-room basis, so that a given room
can be set to share its messages and receive remote messages, either
with a given set of remote systems, or with any system which connects.

this will involve transmitting messages during periods of low mesh
activity, either pausing when other traffic starts appearing, or
developing a knowledge of low-traffic times and transferring messages
during that time.  for transports which are higher-bandwidth, this will
not be a concern.

## ADVANCED AUTHENTICATION

no one enjoys having to remember passwords.  there may be future
developments in MeshCore that allow for transparent-to-the-user PKI
exchanges which will have a similar effect to password authentication.
we may also want to use an external 2FA system.  i am also open to
suggestions for ways to authenticate users which produce a smaller load
on the user, or are substantially more secure.

## DOOR GAMES

later BBS systems included what were called door games, effectively
outlets to external programs.  although i don't want that yet, it may
make sense in the future to allow access to external processes which
could look up information on the internet, or provide functionality not
available in our system.

# CONCLUSION

this represents a good initial description of the Mesh-Citadel system
i'd like to create, but i don't assume it's complete.  please ask me
questions, help me clarify things which aren't clear enough, or expand
with information i haven't yet provided.  the goal of our first phase
should be to develop a complete understanding of the system without
creating any code, and document that understanding clearly and concisely.
this is a personal project, so while considerations of development time
and effort are important, there's no need to quantify development costs
or anything that a corporate manager might be interested in.

what questions do you have for me?
