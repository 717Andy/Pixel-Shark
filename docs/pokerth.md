# PokerTH as a later cross-platform table

Pixel Shark will eventually point a computer-use agent at a second client, not
only at our own browser table. [PokerTH](https://github.com/pokerth/pokerth) is
the right candidate: AGPL, no real-money play, desktop plus Android and iOS
clients, and a dedicated server you can run yourself. This note records what
was checked for phase 0 and why it is not in `docker-compose.yml` yet.

## What we would run

The current project (2.1.10 and later) builds `pokerth_dedicated_server`. That
process is a lobby, not a GUI. It listens on TCP **7234**. With
`ServerUseWebSocket=1` it also listens on **7233** for the browser client.
There is no MySQL requirement for the dedicated server. The official server
binary (`pokerth_official_server`) adds accounts and is out of scope.

Upstream's own setup notes (`docs/server_setup_howto.txt` on the `stable`
branch) say:

- Build with CMake, a C++23 compiler, Qt 6.7 or newer (6.9.2 is what they
  recommend), Boost 1.83, protobuf, and OpenSSL.
- The dedicated server links only Qt Core, Network, Xml, and Sql, but the
  top-level CMake file still requires the client modules (Qml, Quick, Widgets,
  Svg, Multimedia, WebSockets, Linguist). A server-only image still installs a
  full Qt 6 development stack.
- A release build daemonizes. In Docker it needs a foreground debug build, or
  a process supervisor that follows the pid file.
- The server reads avatars from `AppDataDir/data`. A server-only `cmake
  --install` does not install that data directory. The image has to copy
  `data/` and set `AppDataDir`.
- Clients reject servers below a compiled `MIN_BUILD_ID`. A server and the
  clients under test have to come from the same release train.

## What already exists on Docker Hub

[`baptistecdr/pokerth-server`](https://github.com/baptistecdr/docker-pokerth-server)
is a maintained image (linux/amd64, about 125 MB, updated in the week this
was written). Its Dockerfile is:

```dockerfile
FROM ubuntu:26.04
RUN apt install -y pokerth-server
EXPOSE 7234
```

That is the Ubuntu package, not a build of current upstream. Package versions
at the time of writing:

| Ubuntu | `pokerth-server` |
| --- | --- |
| 24.04 noble | 1.1.2 |
| 25.10 questing | 1.1.2 |
| 26.04 resolute | 2.0.6 |

Upstream's 2026 server guide says distribution packages are behind 2.1.10 and
that current clients answer "version not supported" when the protocol does not
match. 2.0.6 is newer than 1.1.2 and still behind the clients we would use for
Android and iOS. Shipping that image would start a process on port 7234 and
then fail the actual cross-platform test.

The historical `pokerth/pokerth` Dockerfile people still find on the forum
builds the **client**. It exits with `could not connect to display` unless you
change the qmake config to the server target. That thread is about the Qt 5
line and does not help here.

## Why it is not in Compose

`docker compose up` has to bring up our playable table. A from-source PokerTH
image is feasible, but it is a different project from phase 0:

- The image is large (Qt 6 dev packages, Boost, protobuf) and the compile is
  long enough that a cold `docker compose up` stops being a way to open the table.
- The server build has to pin a release tag, vendor or copy `data/`, generate
  a TLS certificate if WebSocket-secure is on, and stay in the foreground.
- We did not want a service that looks healthy on port 7234 while speaking a
  protocol the current Android and iOS clients reject.

So Compose only runs `table`. This is a deliberate gap, not an oversight.

## Next step, when a client test is actually scheduled

1. Pin a PokerTH release tag at or after 2.1.10 (the same tag the Android/iOS
   build under test uses).
2. Add `deploy/pokerth/Dockerfile` that installs the Qt 6 build dependencies,
   configures with Ninja, and builds the `pokerth_dedicated_server` target
   only. Copy `data/` to the path in `AppDataDir`. Run a non-daemonized binary
   (`CMAKE_BUILD_TYPE=Debug`, or the project's documented foreground flag if
   one is added). Publish **7234** and, if the browser client is in the test,
   **7233** with `ServerUseWebSocket=1`.
3. Put that service in a Compose profile named `pokerth` so the default
   `docker compose up` stays the Pixel Shark table:

   ```bash
   docker compose --profile pokerth up
   ```

4. Smoke-test with a matching PokerTH client (manual "network game" to
   `host:7234` with TLS off) before pointing Pixel Shark's device backends at
   it. Do not point the agent at `pokerth.net` or at any ranked public lobby.
   A table we host, or a private game whose players agreed, is the allowed
   target. PokerTH itself is a free client with no real-money play; that is
   why it is on the list.
