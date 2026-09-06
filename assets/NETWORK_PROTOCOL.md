# Connection recovery findings

Peace Walker uses `ISteamNetworkingMessages` over Steam Networking Sockets.

The send wrapper at RVA `0x6eac0` queries `GetSessionConnectionInfo`. Vanilla submits the requested payload only in state 3 (`Connected`). In states 1 (`Connecting`) and 2 (`FindingRoute`) it returns success without submitting the payload. Steam supports queuing ordinary reliable messages while connection establishment is in progress.

The r2 hook at RVA `0x6eb2e` preserves vanilla handling for unreliable traffic. Reliable payloads are submitted in states 0 through 5 so an important transition message is not discarded merely because the session is opening or has just failed.

The send-flag hook at RVA `0x6eb5e` adds `k_nSteamNetworkingSend_AutoRestartBrokenSession` to reliable sends. Steam can therefore restart a terminal session and queue the same reliable game payload. Unreliable sends keep their original flags. Existing packet data, peer identity, and channel are unchanged.

The state-maintenance function at RVA `0x6eec0` closes state 5 (`ProblemDetectedLocally`) but ignores state 4 (`ClosedByPeer`). The r2 branch change at RVA `0x6ef89` sends both terminal states through the existing `CloseSessionWithUser` path. The following state 0 pass uses the game's existing session-opening behavior.

The same maintenance path queries a missing session and permits one session-opening resend at RVA `0x6f10f`. r2 permits five. Steam configuration values 24 and 25 set the initial and connected timeout defaults to 60 seconds before users enter a lobby.

No new network message or acknowledgement is introduced, so the wire protocol remains unchanged.
