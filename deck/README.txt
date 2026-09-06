Extra Ops 129 - Steam Deck

Setup

1. In Steam, open Peace Walker > Properties > Installed Files > Browse.
2. Copy the complete Extra Ops 129 folder beside the mgspw folder.
3. Enter Desktop Mode.
4. Open a terminal in the Extra Ops 129 folder.
5. Run: bash deck/setup.sh
6. Choose installation option 1, 2, or 3.
7. In Peace Walker's Steam launch options, enter:

WINEDLLOVERRIDES="winmm=n,b" %command%

Start the game normally. Runtime status is written to mgspw/eo129_deck.log.

The Steam Deck runtime applies the network protocol patch automatically when the game starts. It uses the same reliable-message recovery, five session-opening attempts, automatic broken-session restart, and 60-second Steam Networking timeouts as the Windows network patch.

Windows Defender and other antivirus software may flag the Windows executables in the Windows package because they modify the running game. The network patch executable is the most likely to be flagged. Source and technical details are included with the project.

Uninstall

1. Close Peace Walker.
2. Run: bash deck/setup.sh
3. Choose option 4.
4. Remove the WINEDLLOVERRIDES launch option from Steam.

Save restoration requires Steam to be fully closed and Steam Cloud disabled for Peace Walker.

Requirements

- SteamOS x86_64
- Python 3.8 or newer
- Metal Gear Solid: Peace Walker Steam build 25052315
