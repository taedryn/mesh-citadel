# Mesh-Citadel BBS

This project aims to create a MeshCore-connected BBS, heavily inspired
by the Citadel BBS from the 1980s.  This system is lightweight,
designed to run on a solar-powered Raspberry Pi Zero and a low-power
nRF52-based LoRa node running the USB companion firmware via
py-meshcore.

# In Progress

Development is still in progress, but the system is nearing the
point of being sort of MVP-level code-complete.  The major remaining
component is the transport layer code, which will focus on a CLI
interface to start with, and expand to include a MeshCore transport
soon after that.  Most of the BBS-side code is in a functional state,
if not fully fleshed out (for instance, there's only a skeleton set of
BBS commands available right now).  It's all in a fairly theoretical
"it does what I want it to do" state, but it remains to be seen if
these are the components of a functional BBS, or merely the start of
those components.

I do expect to be able to interact via CLI fairly soon, which will
quickly prove out the functionality I think I have.  The transport
layer should be easily adaptable to other transport methods, such as
MeshCore, Meshtastic, or telnet/ssh, or even a web client if someone
wanted to go that way.

Check the docs/ directory for documents describing the intended
path of development, with the prompt.md file being an overview, and
the various other files addressing more specific areas.

# Contributions

I'm not yet ready to integrate others' code into this project, I need
to get it to the point of being functional and in an MVP state first.
Feel free to open Issues on this project if you have suggestions, but
expect me to ignore them until we're looking at a functional system
that does roughly what I want it to.

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
