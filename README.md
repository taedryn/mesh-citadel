# Mesh-Citadel BBS

This project aims to create a MeshCore-connected BBS, heavily inspired
by the Citadel BBS from the 1980s.  This system is lightweight,
designed to run on a solar-powered Raspberry Pi Zero and a low-power
nRF52-based LoRa node running the USB companion firmware via
py-meshcore.

# In Progress

Development is currently in progress, and most of the system has yet to
be fleshed out.  When it's done, it should have a clean, modular design
that will be suitable for its intended purpose, while also being
extensible for those who want to run with more resources, or an
(unplanned, but easily implemented) HTTP transport module, or other
transport methods.

I will update this document as progress is made, but for now, this is
very much a work in progress.

You may enjoy reading the prompt.md file in this directory, which is
the prompt used with Copilot to set the context, and conveys the
architecture of the system very clearly.

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
